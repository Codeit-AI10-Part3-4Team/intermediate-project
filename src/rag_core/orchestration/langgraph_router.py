# mypy: ignore-errors
"""
src/rag_core/orchestration/langgraph_router.py

LangGraph 기반 Router: 사용자 질문을 유형별로 분류하고 적절한 처리 노드로 분기한다.
Retriever(Hybrid RRF) + Ollama(exaone3.5:7.8b) 실제 연동 버전.

분류 기준은 골든 데이터셋(golden_dataset_v2.csv) question_type 실측 분포를 따른다:
    단일문서_사실추출      37건
    단일문서_세부요구사항   36건
    다중문서_비교            8건
    다중문서_종합            6건
    멀티턴_후속질의          7건
    모른다_테스트            7건

사용법:
    from rag_core.orchestration.langgraph_router import build_graph
    app = build_graph(chroma_dir="/data/vector_db/vector_db_v9")
    result = app.invoke(
        {"question": "이 사업의 예산은?", "history": []},
        config={"configurable": {"thread_id": "session_1"}}
    )
    print(result["answer"])
"""

from __future__ import annotations

import os
from typing import Any, Literal, Optional, TypedDict

import requests
from langgraph.checkpoint.memory import MemorySaver  # type: ignore[import-not-found]
from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]

from rag_core.retrieval.retriever import Retriever
from rag_core.llm.pipeline import (
    ask_exaone_from_docs,
    is_score_prediction_question,
    score_prediction_guardrail_answer,
    split_comparison_entities,
    retrieve_multi_query,
    dedup_docs_by_doc_id,
)
from rag_core.prompts.builder import build_prompt as _builder_build_prompt
from rag_core.exceptions import LLMConnectionError, LLMTimeoutError


# ──────────────────────────────────────────────
# RetrievedChunk → pipeline.py 호환 어댑터
# ──────────────────────────────────────────────


class _DocAdapter:
    """
    Retriever.retrieve()가 반환하는 RetrievedChunk를
    pipeline.py의 format_rag_context()가 기대하는
    (page_content, metadata) 인터페이스로 변환한다.
    """

    def __init__(self, chunk):
        self.page_content = chunk.chunk.text
        self.metadata = chunk.chunk.metadata


def _to_docs(retrieved: list) -> list:
    return [_DocAdapter(r) for r in retrieved]


# ──────────────────────────────────────────────
# 설정 (환경변수로 주입, 기본값 제공)
# ──────────────────────────────────────────────

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "exaone3.5:7.8b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
CHROMA_DIR_DEFAULT = os.getenv("CHROMA_DIR", "/data/vector_db/vector_db_v9")
TOP_K_DEFAULT = int(os.getenv("TOP_K", "10"))
TOP_K_REQUIREMENT = int(os.getenv("TOP_K_REQUIREMENT", "15"))

# ──────────────────────────────────────────────
# State 정의
# ──────────────────────────────────────────────


class RagState(TypedDict, total=False):
    """LangGraph 전체 파이프라인에서 공유되는 상태."""

    question: str
    rewritten_question: str
    question_type: str
    doc_id_hint: Optional[str]
    compare_targets: list[str]
    retrieved_chunks: list[str]
    retrieved_sources: list[dict]
    answer: str
    related_questions: str  # 지우님 generate_followup() 결과
    style_prompt: str  # 문체 변환 유도 문구
    history: list[dict]
    error: Optional[str]
    # 업로드 임시 DB 전용
    upload_collection: Optional[str]  # 업로드된 임시 ChromaDB collection 이름
    # 입찰 적합도 분석 전용
    company_info: Optional[str]  # 사용자 입력 회사 정보 (없으면 A만 실행)
    bid_analysis: Optional[dict]  # 분석 결과 (항목별 점수, 종합 점수, 리스크 등)


QuestionType = Literal[
    "single_doc_fact",
    "single_doc_requirement",
    "multi_doc_compare",
    "multi_doc_summary",
    "multiturn",
    "guardrail",
    "bid_analysis",  # 입찰 적합도 분석
    "rewrite",  # 문체 변환
]

# ──────────────────────────────────────────────
# 1차 분류 — 키워드 기반
# ──────────────────────────────────────────────

_EXTREMUM_KEYWORDS = [
    "가장 큰",
    "가장 작은",
    "가장 높은",
    "가장 낮은",
    "최대 예산",
    "최소 예산",
    "최고 예산",
    "최저 예산",
    "예산이 제일",
    "금액이 가장",
]
_MULTI_DOC_KEYWORDS = ["비교", "vs", "VS", "차이", "각각", "두 사업", "여러 사업", "종합"]
_GUARDRAIL_KEYWORDS = ["날씨", "주식", "오늘 뉴스", "너는 누구", "기술점수 몇 점", "당첨 확률"]
_MULTITURN_KEYWORDS = ["그 사업", "그것", "이전 질문", "방금", "그럼"]
_REQUIREMENT_KEYWORDS = ["요구사항", "보안", "성능", "기능", "납품", "사양", "조건"]
_BID_ANALYSIS_KEYWORDS = [
    "입찰 적합도",
    "적합도 분석",
    "입찰 분석",
    "리스크 분석",
    "우리 회사",
    "참여 가능",
    "지원 가능",
    "낙찰 가능성",
]
_REWRITE_KEYWORDS = [
    "문체 변환",
    "공문서",
    "공문서 형식",
    "공식 문서",
    "형식으로 변환",
    "문서 형식",
    "사업제안서",
    "보고서 형식",
    "공식적으로",
]


def classify_question_keyword(question: str, has_history: bool) -> QuestionType:
    q = question.strip()
    if any(kw in q for kw in _GUARDRAIL_KEYWORDS):
        return "guardrail"
    _AMOUNT_KEYWORDS = ["예산", "사업금액", "금액", "사업비"]
    if any(kw in q for kw in _EXTREMUM_KEYWORDS) and any(ak in q for ak in _AMOUNT_KEYWORDS):
        return "metadata_scan"
    if any(kw in q for kw in _REWRITE_KEYWORDS):
        return "rewrite"
    if any(kw in q for kw in _BID_ANALYSIS_KEYWORDS):
        return "bid_analysis"
    if has_history and any(kw in q for kw in _MULTITURN_KEYWORDS):
        return "multiturn"
    if any(kw in q for kw in _MULTI_DOC_KEYWORDS):
        if "종합" in q or "유사" in q:
            return "multi_doc_summary"
        return "multi_doc_compare"
    if any(kw in q for kw in _REQUIREMENT_KEYWORDS):
        return "single_doc_requirement"
    return "single_doc_fact"


# ──────────────────────────────────────────────
# LLM 호출 (Ollama)
# ──────────────────────────────────────────────


def call_ollama(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """Ollama로 LLM 호출. 연결 실패/타임아웃을 도메인 예외로 구분해 던진다 (api 계층 502/504 매핑용)."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["response"].strip()
    except requests.exceptions.ConnectionError as e:
        raise LLMConnectionError(f"Ollama 연결 실패: {e}") from e
    except requests.exceptions.Timeout as e:
        raise LLMTimeoutError(f"Ollama 타임아웃: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama 호출 실패: {e}") from e


def call_llm_with_fallback(prompt: str) -> str:
    """Ollama 호출 (OpenAI fallback 제거 — RFP 외부 유출 방지).

    실패 시 도메인 예외(LLMConnectionError/LLMTimeoutError) 또는 RuntimeError를
    그대로 전파해 api 계층에서 502/504/500으로 매핑되게 한다.
    """
    try:
        return call_ollama(prompt)
    except (LLMConnectionError, LLMTimeoutError, RuntimeError) as e:
        print(f"[LLM] Ollama 호출 실패: {e}")
        raise


# ──────────────────────────────────────────────
# 프롬프트 구성
# ──────────────────────────────────────────────


def build_prompt(question: str, chunks: list[str], question_type: str) -> str:
    """지우님 builder.py 기반 프롬프트 구성."""
    from rag_core.llm.pipeline import format_rag_context, build_doc_metadata_table

    class _SimpleDoc:
        def __init__(self, text: str) -> None:
            self.page_content = text
            self.metadata: dict[str, Any] = {}

    docs = [_SimpleDoc(c) for c in chunks]
    context = format_rag_context(docs)
    doc_list = build_doc_metadata_table(docs)
    is_multi = question_type in ("multi_doc_compare", "multi_doc_summary")
    return _builder_build_prompt(
        question=question,
        context=context,
        doc_list=doc_list,
        is_multi_doc=is_multi,
    )


# ──────────────────────────────────────────────
# Retriever 싱글톤 (앱 시작 시 한 번만 로드)
# ──────────────────────────────────────────────

_retriever: Optional[Retriever] = None


def get_retriever(chroma_dir: str = CHROMA_DIR_DEFAULT) -> Retriever:
    global _retriever
    if _retriever is None:
        print(f"[Router] Retriever 초기화 중 ({chroma_dir})...")
        _retriever = Retriever(chroma_dir=chroma_dir)
        _retriever.load()
        print("[Router] Retriever 초기화 완료")
    return _retriever


# ──────────────────────────────────────────────
# 업로드 임시 Retriever 관리
# ──────────────────────────────────────────────

_upload_retrievers: dict[str, Retriever] = {}


def get_upload_retriever(collection_name: str) -> Optional[Retriever]:
    """업로드된 임시 ChromaDB collection으로 Retriever 반환."""
    return _upload_retrievers.get(collection_name)


def register_upload_retriever(collection_name: str, retriever: Retriever) -> None:
    """임시 Retriever 등록 (업로드 후 호정님 upload.py에서 호출)."""
    _upload_retrievers[collection_name] = retriever
    print(f"[Router] 임시 Retriever 등록: {collection_name}")


def release_upload_retriever(collection_name: str) -> None:
    """임시 Retriever 해제 (세션 종료 시)."""
    if collection_name in _upload_retrievers:
        del _upload_retrievers[collection_name]
        print(f"[Router] 임시 Retriever 해제: {collection_name}")


def _get_active_retriever(state: RagState) -> Retriever:
    """
    업로드 임시 DB 우선 사용, 없으면 기존 vector_db 사용.
    upload_collection이 state에 있으면 임시 Retriever 반환.
    """
    upload_collection = state.get("upload_collection")
    if upload_collection:
        upload_retriever = get_upload_retriever(upload_collection)
        if upload_retriever:
            print(f"[Router] 임시 DB 사용: {upload_collection}")
            return upload_retriever
    return get_retriever()


# ──────────────────────────────────────────────
# 노드 함수
# ──────────────────────────────────────────────


def query_rewriting_node(state: RagState) -> dict:
    """Query Rewriting: doc_id_hint 있으면 query에 포함."""
    question = state["question"]
    doc_id_hint = state.get("doc_id_hint")
    rewritten = f"[{doc_id_hint}] {question}" if doc_id_hint else question
    return {"rewritten_question": rewritten}


def router_node(state: RagState) -> dict:
    """질문 유형 분류 → state에 기록."""
    question = state.get("rewritten_question", state["question"])
    has_history = bool(state.get("history"))
    question_type = classify_question_keyword(question, has_history)
    return {"question_type": question_type}


def route_decision(state: RagState) -> str:
    return state["question_type"]


def single_doc_fact_node(state: RagState) -> dict:
    """단일문서_사실추출: Hybrid RRF 검색 top_k=10. 업로드 임시 DB 우선 사용."""
    question = state.get("rewritten_question", state["question"])
    try:
        retriever = _get_active_retriever(state)
        retrieved = retriever.retrieve(question, top_k=TOP_K_DEFAULT)
        chunks = [r.chunk.text for r in retrieved]
        sources = [
            {
                "doc_id": r.chunk.doc_id,
                "score": r.score,
                "metadata": r.chunk.metadata,
                "text": r.chunk.text,
            }
            for r in retrieved
        ]
        return {"retrieved_chunks": chunks, "retrieved_sources": sources}
    except Exception as e:
        print(f"[Router] Retrieval 오류: {e}")
        return {"retrieved_chunks": [], "retrieved_sources": [], "error": str(e)}


def single_doc_requirement_node(state: RagState) -> dict:
    """단일문서_세부요구사항: top_k=15로 더 넓게 검색. 업로드 임시 DB 우선 사용."""
    question = state.get("rewritten_question", state["question"])
    try:
        retriever = _get_active_retriever(state)
        retrieved = retriever.retrieve(question, top_k=TOP_K_REQUIREMENT)
        chunks = [r.chunk.text for r in retrieved]
        sources = [
            {
                "doc_id": r.chunk.doc_id,
                "score": r.score,
                "metadata": r.chunk.metadata,
                "text": r.chunk.text,
            }
            for r in retrieved
        ]
        return {"retrieved_chunks": chunks, "retrieved_sources": sources}
    except Exception as e:
        print(f"[Router] Retrieval 오류: {e}")
        return {"retrieved_chunks": [], "retrieved_sources": [], "error": str(e)}


def generate_sub_queries(question: str) -> list[str]:
    """LLM으로 질문을 서브 쿼리로 분리."""
    prompt = f"""아래 질문을 검색에 최적화된 2~3개의 세부 질문으로 분리하세요.
각 질문은 줄바꿈으로 구분하고, 번호나 기호 없이 질문만 출력하세요.

질문: {question}

세부 질문:"""
    try:
        raw = call_llm_with_fallback(prompt)
        sub_queries = [q.strip() for q in raw.strip().split("\n") if q.strip()]
        if not sub_queries:
            return [question]
        return sub_queries + [question]
    except Exception:
        # 서브쿼리 생성은 부가 기능 — LLM 장애 시에도 원본 질문으로 검색 계속 (의도적 폴백)
        return [question]


def multi_doc_compare_node(state: RagState) -> dict:
    """다중문서_비교: split_comparison_entities로 기관별 쿼리 분리 후
    retrieve_multi_query(max_chunks_per_doc=2)로 문서 다양성 확보. 업로드 임시 DB 우선.
    한 문서가 top-k를 독점해 상대 문서가 밀려나는 문제(Q061/Q010) 방지."""
    question = state.get("rewritten_question", state["question"])
    try:
        retriever = _get_active_retriever(state)
        queries = split_comparison_entities(question)
        if not queries:
            queries = [question]
        docs = retrieve_multi_query(queries, retriever, k_each=TOP_K_DEFAULT, max_chunks_per_doc=2)
        docs = dedup_docs_by_doc_id(docs)
        chunks = [d.page_content for d in docs]
        # retrieve_multi_query는 RRF 내부 점수를 밖으로 반환하지 않으므로,
        # 반환 순서(관련도 내림차순) 기반으로 표시용 순위 점수를 부여한다.
        sources = [
            {
                "doc_id": d.metadata.get("doc_id", ""),
                "score": round(1.0 / (rank + 1), 4),
                "metadata": d.metadata,
                "text": d.page_content,
            }
            for rank, d in enumerate(docs)
        ]
        return {"retrieved_chunks": chunks, "retrieved_sources": sources}
    except Exception as e:
        return {"retrieved_chunks": [], "retrieved_sources": [], "error": str(e)}


def multi_doc_summary_node(state: RagState) -> dict:
    """다중문서_종합: 다중문서 비교와 동일한 검색."""
    return multi_doc_compare_node(state)


def multiturn_node(state: RagState) -> dict:
    """
    멀티턴: history에서 이전 질문의 핵심 주제를 추출해 현재 질문에 결합.
    "그 사업의 기간은?" → "국민연금공단 이러닝시스템 사업의 기간은?"
    이전 질문 전체를 붙이면 예산/보안 등 이전 키워드가 검색에 영향을 주므로
    대명사/지시어만 제거하고 현재 질문을 보강하는 방식 사용.
    """
    history = state.get("history", [])
    current_q = state.get("question", "")

    if not history:
        return {"rewritten_question": current_q}

    last_turn = history[-1]
    prev_question = last_turn.get("question", "")

    # 이전 질문에서 사업명/기관명 키워드 추출 (조사 제거)
    # "국민연금공단 이러닝시스템 사업의 예산은?" → "국민연금공단 이러닝시스템 사업"
    topic = prev_question
    for suffix in [
        "의 예산은 얼마인가요?",
        "은 얼마인가요?",
        "을 알려주세요",
        "은 무엇인가요?",
        "는 무엇인가요?",
        "을 설명해주세요",
        "이 궁금합니다",
        "?",
    ]:
        topic = topic.replace(suffix, "").strip()

    # 현재 질문의 대명사를 주제로 교체
    rewritten = current_q
    for pronoun in ["그 사업", "그것", "해당 사업", "이 사업"]:
        if pronoun in rewritten:
            rewritten = rewritten.replace(pronoun, topic)
            break

    return {"rewritten_question": rewritten}


def bid_analysis_node(state: RagState) -> dict:
    """
    입찰 적합도 분석 (A + B 통합):
    A. RFP 자체 리스크/난이도 분석 (항상 실행)
    B. 회사 정보 있으면 적합성 비교 추가
    """
    question = state.get("rewritten_question", state["question"])
    company_info = state.get("company_info")

    # 1단계: RFP 문서 검색 (요구사항 섹션 중심으로 더 넓게)
    try:
        retriever = _get_active_retriever(state)
        retrieved = retriever.retrieve(question, top_k=15)
        chunks = [r.chunk.text for r in retrieved]
    except Exception as e:
        chunks = []
        print(f"[BidAnalysis] Retrieval 오류: {e}")

    context = "\n\n".join(chunks) if chunks else "검색된 문서가 없습니다."

    # 2단계: A. RFP 자체 분석 프롬프트 (텍스트 형식)
    rfp_analysis_prompt = f"""당신은 RFP 입찰 전문가입니다. 아래 RFP를 분석하세요.
반드시 아래 형식으로만 답변하세요:
기술요구사항: 15 | 충족가능 | Java/Spring 기반 개발 경험 필요
예산규모: 12 | 충족가능 | 112억 대규모 사업
보안인증: 10 | 확인필요 | CC인증 요건 확인 필요
납품기간: 14 | 충족가능 | 24개월로 여유 있음
자격제한: 16 | 충족가능 | 특별한 지역 제한 없음
종합점수: 67
등급: 검토필요
리스크1: CC인증 EAL4 미보유 시 참여 불가
리스크2: 현장 상주 요건 확인 필요
권고: 보안 인증 현황 확인 후 입찰 참여 여부를 결정하세요.

[RFP 문서 내용]
{context[:2000]}

[분석]"""

    # 3단계: 회사 정보 있으면 프롬프트에 추가
    if company_info:
        full_prompt = (
            rfp_analysis_prompt.rstrip("[분석]").rstrip()
            + f"""

[회사 정보]
{company_info}

[분석]"""
        )
    else:
        full_prompt = rfp_analysis_prompt

    # LLM 호출
    try:
        raw = call_ollama(full_prompt).strip()
        # hallucination 방지 후처리 (지우님 pipeline.py 규칙 적용)
        from rag_core.llm.pipeline import postprocess_exaone, postprocess_answer_format

        _post = postprocess_exaone(raw)
        raw = postprocess_answer_format(_post["processed"])

        import re as _re

        def _extract_line(key: str, text: str, default: str = "확인필요") -> str:
            m = _re.search(rf"{key}:\s*(.+)", text)
            return m.group(1).strip() if m else default

        def _parse_item(key: str, text: str, name: str) -> dict[str, Any]:
            m = _re.search(rf"{key}:\s*(\d+)\s*\|\s*([^|\n]+)\s*\|\s*(.+)", text)
            if m:
                score = int(m.group(1))
                tag_raw = m.group(2).strip()
                reason = m.group(3).strip()
            else:
                score, tag_raw, reason = 10, "확인필요", "세부 확인 필요"

            tag_map = {
                "충족가능": "🟢 충족가능",
                "확인필요": "🟡 확인필요",
                "부분적 확인": "🟡 확인필요",
                "부분적 정보 부족": "🟡 확인필요",
                "정보 부족": "🟡 확인필요",
                "어려움": "🔴 어려움",
                "미충족": "🔴 어려움",
            }
            tag = next((v for k, v in tag_map.items() if k in tag_raw), f"🟡 {tag_raw}")
            return {"name": name, "score": score, "tag": tag, "reason": reason}

        items = [
            _parse_item("기술요구사항", raw, "기술 요구사항"),
            _parse_item("예산규모", raw, "예산/규모"),
            _parse_item("보안인증", raw, "보안/인증"),
            _parse_item("납품기간", raw, "납품 기간"),
            _parse_item("자격제한", raw, "자격/지역 제한"),
        ]

        # 종합점수 — "종합점수: 67" 또는 "종합점수: 67 | 검토필요 | ..." 형태 모두 처리
        total_m = _re.search(r"종합점수:\s*(\d+)", raw)
        total = int(total_m.group(1)) if total_m else sum(i["score"] for i in items)

        # 등급 — "등급: 검토필요" 또는 "등급: 검토필요 | ..." 형태 모두 처리
        grade_m = _re.search(r"등급:\s*(적합|검토필요|미적합)", raw)
        grade_raw = grade_m.group(1).strip() if grade_m else "검토필요"
        grade_map = {"적합": "🟢 적합", "검토필요": "🟡 검토필요", "미적합": "🔴 미적합"}
        grade = grade_map.get(grade_raw, "🟡 검토필요")

        # 리스크 — "리스크1: 내용" 또는 "리스크1: 10 | 높음 | 내용" 형태 모두 처리
        risks = []
        for i in [1, 2]:
            # 파이프 형식: 마지막 파이프 이후 내용 추출
            m_pipe = _re.search(rf"리스크{i}:\s*\d+\s*\|\s*[^|]+\|\s*(.+)", raw)
            # 일반 형식
            m_plain = _re.search(rf"리스크{i}:\s*(?!\d+\s*\|)(.+)", raw)
            if m_pipe:
                risks.append(m_pipe.group(1).strip())
            elif m_plain:
                risks.append(m_plain.group(1).strip())
        if not risks:
            risks = ["세부 요건 확인 필요"]

        # 권고
        rec_m = _re.search(r"권고[:\s]+(.+)", raw)
        recommendation = (
            rec_m.group(1).strip().lstrip("-").strip()
            if rec_m
            else "세부 요건을 확인 후 입찰 참여 여부를 결정하세요."
        )

        bid_result = {
            "items": items,
            "total_score": total,
            "grade": grade,
            "risks": risks,
            "recommendation": recommendation,
        }

    except (LLMConnectionError, LLMTimeoutError):
        # LLM 연결/타임아웃은 삼키지 않고 전파 → api 계층에서 502/504로 매핑
        raise
    except Exception as e:
        print(f"[BidAnalysis] LLM 오류: {e}")
        bid_result = {
            "items": [],
            "total_score": 0,
            "grade": "🟡검토필요",
            "risks": ["분석 중 오류 발생"],
            "recommendation": "문서를 다시 확인해주세요.",
        }

    # 사람이 읽기 좋은 텍스트 답변도 생성
    items_text = "\n".join(
        [
            f"- {item['name']}: {item['score']}점 {item['tag']} — {item['reason']}"
            for item in bid_result.get("items", [])
        ]
    )
    answer = f"""**입찰 적합도 분석 결과**

**종합 점수: {bid_result.get("total_score", 0)}점 / 100점** {bid_result.get("grade", "")}

**항목별 평가:**
{items_text}

**주요 리스크:**
{chr(10).join(["- " + r for r in bid_result.get("risks", [])])}

**권고사항:** {bid_result.get("recommendation", "")}"""

    # 히스토리 업데이트
    history = list(state.get("history") or [])
    history.append(
        {
            "question": state.get("question", ""),
            "answer": answer,
            "doc_id_hint": state.get("doc_id_hint"),
        }
    )

    return {
        "answer": answer,
        "bid_analysis": bid_result,
        "history": history,
    }


def rewrite_node(state: RagState) -> dict:
    """
    문체 변환 노드:
    사용자가 "공문서 형식으로 변환해줘" 등 요청 시
    history의 마지막 답변을 지우님 .txt 템플릿으로 변환.
    """
    from pathlib import Path

    question = state.get("question", "")
    raw_history = state.get("history", [])
    history: list[dict[str, Any]] = list(raw_history) if raw_history else []

    # 변환할 대상 — history 마지막 답변
    if not history:
        return {
            "answer": "변환할 이전 답변이 없습니다. 먼저 RFP에 대해 질문해주세요.",
        }

    last_turn: dict[str, Any] = history[-1]
    last_answer: str = str(last_turn.get("answer", ""))
    if not last_answer:
        return {
            "answer": "변환할 이전 답변이 없습니다.",
        }

    # 변환 스타일 감지 → 템플릿 파일 선택
    templates_dir = Path(__file__).parent.parent / "prompts" / "templates"
    if any(kw in question for kw in ["사업제안서", "제안서"]):
        template_path = templates_dir / "prompt_template_rewrite_사업제안서_v1.txt"
    elif any(kw in question for kw in ["보고서", "보고"]):
        template_path = templates_dir / "prompt_template_rewrite_보고서_v1.txt"
    else:
        template_path = templates_dir / "prompt_template_rewrite_공문서_v1.txt"

    try:
        template = template_path.read_text(encoding="utf-8")
        prompt = template.format(last_answer=last_answer)
    except Exception as e:
        print(f"[Rewrite] 템플릿 로드 오류: {e}")
        prompt = f"아래 내용을 공문서 형식으로 변환하세요.\n\n{last_answer}"

    try:
        converted = call_ollama(prompt).strip()
    except (LLMConnectionError, LLMTimeoutError):
        # LLM 연결/타임아웃은 삼키지 않고 전파 → api 계층에서 502/504로 매핑
        raise
    except Exception as e:
        print(f"[Rewrite] LLM 오류: {e}")
        converted = "죄송합니다. 문체 변환 중 오류가 발생했습니다."

    # 히스토리 업데이트
    history_new = list(history)
    history_new.append(
        {
            "question": question,
            "answer": converted,
            "doc_id_hint": state.get("doc_id_hint"),
        }
    )

    return {"answer": converted, "history": history_new}


def metadata_scan_node(state: RagState) -> dict:
    """전체 metadata 스캔으로 사업금액 최대/최솟값 문서 찾기."""
    question = state.get("rewritten_question", state["question"])
    find_max = any(kw in question for kw in ["가장 큰", "최대", "최고", "가장 높은", "제일 큰"])

    try:
        retriever = _get_active_retriever(state)
        collection = retriever.vectorstore._collection
        results = collection.get(include=["metadatas"])

        MIN_THRESHOLD = 1_000_000
        seen_docs = {}
        for meta in results.get("metadatas", []):
            if not meta:
                continue
            amount = meta.get("사업금액", 0)
            doc_id = meta.get("doc_id", "")
            if amount and amount >= MIN_THRESHOLD and doc_id not in seen_docs:
                seen_docs[doc_id] = meta

        if not seen_docs:
            return {
                "retrieved_chunks": [],
                "retrieved_sources": [],
                "answer": "사업금액 정보를 찾을 수 없습니다.",
            }

        def key_func(item):
            return item[1]["사업금액"]

        _, result_meta = (
            max(seen_docs.items(), key=key_func)
            if find_max
            else min(seen_docs.items(), key=key_func)
        )

        label = "가장 큰" if find_max else "가장 작은"
        answer = (
            f"예산이 {label} 사업은 다음과 같습니다.\n\n"
            f"- 사업명: {result_meta.get('사업명', '정보 없음')}\n"
            f"- 발주기관: {result_meta.get('발주기관', '정보 없음')}\n"
            f"- 사업금액: {result_meta.get('사업금액', 0):,}원"
        )
        return {
            "retrieved_chunks": [],
            "retrieved_sources": [],
            "answer": answer,
            "question_type": "metadata_scan",
        }
    except Exception as e:
        print(f"[MetadataScan] 오류: {e}")
        return {
            "retrieved_chunks": [],
            "retrieved_sources": [],
            "answer": f"metadata 스캔 중 오류가 발생했습니다: {e}",
        }


def guardrail_node(state: RagState) -> dict:
    """가드레일: Retrieval 생략, 고정 응답 반환."""
    return {
        "answer": "죄송합니다. 해당 질문은 RFP 문서 분석 범위를 벗어나거나, "
        "현재 보유한 문서에서 확인할 수 있는 정보가 아닙니다."
    }


def generation_node(state: RagState) -> dict:
    """
    Prompt 구성 + LLM 호출.
    지우님 pipeline.py의 ask_exaone_from_docs() 사용.
    retrieved_chunks를 _DocAdapter로 변환해서 전달.
    """
    question = state.get("rewritten_question", state["question"])
    chunks = state.get("retrieved_chunks", [])
    question_type = state.get("question_type", "single_doc_fact")

    # 가드레일 — 점수 예측 질문
    if is_score_prediction_question(question):
        return {"answer": score_prediction_guardrail_answer(question)}

    is_multi = question_type in ("multi_doc_compare", "multi_doc_summary")

    # retrieved_sources에서 metadata 포함 Doc 객체 생성
    class _SimpleDoc:
        def __init__(self, text: str, metadata: dict):
            self.page_content = text
            self.metadata = metadata

    sources = state.get("retrieved_sources", [])
    if sources and "metadata" in sources[0]:
        docs = [_SimpleDoc(s["text"], s["metadata"]) for s in sources]
    else:
        docs = [_SimpleDoc(c, {}) for c in chunks]

    try:
        result = ask_exaone_from_docs(question, docs, is_multi_doc=is_multi)
        answer = result.get("model_answer", "")
        related_questions = result.get("related_questions", "")
        style_prompt = result.get("style_prompt", "")
    except (LLMConnectionError, LLMTimeoutError):
        # LLM 연결/타임아웃은 삼키지 않고 전파 → api 계층에서 502/504로 매핑
        raise
    except Exception as e:
        print(f"[Router] Generation 오류: {e}")
        answer = "죄송합니다. 현재 답변 생성에 실패했습니다."
        related_questions = ""
        style_prompt = ""

    # 히스토리 업데이트
    history = list(state.get("history") or [])
    history.append(
        {
            "question": state.get("question", ""),
            "answer": answer,
            "doc_id_hint": state.get("doc_id_hint"),
        }
    )

    return {
        "answer": answer,
        "related_questions": related_questions,
        "style_prompt": style_prompt,
        "history": history,
    }


# ──────────────────────────────────────────────
# Graph 빌드
# ──────────────────────────────────────────────


def build_graph(chroma_dir: str = CHROMA_DIR_DEFAULT, use_checkpointer: bool = True):
    """
    StateGraph 조립 + MemorySaver 체크포인터로 컴파일.

    Args:
        chroma_dir: ChromaDB 경로 (기본값: /data/vector_db/vector_db_v9)

    Returns:
        컴파일된 LangGraph 앱
    """
    # Retriever 미리 초기화
    get_retriever(chroma_dir)

    graph = StateGraph(RagState)

    graph.add_node("query_rewriting", query_rewriting_node)
    graph.add_node("router", router_node)
    graph.add_node("single_doc_fact", single_doc_fact_node)
    graph.add_node("single_doc_requirement", single_doc_requirement_node)
    graph.add_node("multi_doc_compare", multi_doc_compare_node)
    graph.add_node("multi_doc_summary", multi_doc_summary_node)
    graph.add_node("multiturn", multiturn_node)
    graph.add_node("bid_analysis", bid_analysis_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("generation", generation_node)
    graph.add_node("metadata_scan", metadata_scan_node)

    graph.set_entry_point("query_rewriting")
    graph.add_edge("query_rewriting", "router")

    graph.add_conditional_edges(
        "router",
        route_decision,
        {
            "single_doc_fact": "single_doc_fact",
            "single_doc_requirement": "single_doc_requirement",
            "multi_doc_compare": "multi_doc_compare",
            "multi_doc_summary": "multi_doc_summary",
            "multiturn": "multiturn",
            "metadata_scan": "metadata_scan",
            "bid_analysis": "bid_analysis",
            "rewrite": "rewrite",
            "guardrail": "guardrail",
        },
    )

    graph.add_edge("guardrail", END)
    graph.add_edge("bid_analysis", END)
    graph.add_edge("rewrite", END)
    graph.add_edge("single_doc_fact", "generation")
    graph.add_edge("single_doc_requirement", "generation")
    graph.add_edge("multi_doc_compare", "generation")
    graph.add_edge("multi_doc_summary", "generation")
    graph.add_edge("multiturn", "single_doc_fact")
    graph.add_edge("generation", END)
    graph.add_edge("metadata_scan", END)

    # 체크포인터는 멀티턴(session_id)용. 불필요하면 붙이지 않아 상태 누적을 원천 차단.
    if use_checkpointer:
        return graph.compile(checkpointer=MemorySaver())
    return graph.compile()


# ──────────────────────────────────────────────
# 단독 테스트 (python3 langgraph_router.py)
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-dir", default=CHROMA_DIR_DEFAULT)
    parser.add_argument(
        "--keyword-only", action="store_true", help="키워드 분류기만 테스트 (Retriever/LLM 없이)"
    )
    args = parser.parse_args()

    if args.keyword_only:
        print("=" * 60)
        print("키워드 기반 1차 분류 테스트 (Retriever/LLM 없이)")
        print("=" * 60)
        test_cases: list[tuple[str, bool, str]] = [
            ("이 사업의 예산은 얼마인가요?", False, "single_doc_fact"),
            ("이 사업의 보안 요구사항은 무엇인가요?", False, "single_doc_requirement"),
            ("고려대학교와 광주과학기술원 사업을 비교해주세요", False, "multi_doc_compare"),
            ("비슷한 사업들을 종합해서 알려주세요", False, "multi_doc_summary"),
            ("그 사업의 기간은 어떻게 되나요?", True, "multiturn"),
            ("오늘 날씨 어때?", False, "guardrail"),
        ]
        correct = 0
        for question, has_history, expected in test_cases:
            result = classify_question_keyword(question, has_history)
            status = "OK" if result == expected else "FAIL"
            if result == expected:
                correct += 1
            print(f"  [{status}] '{question}' → {result}")
        print(f"\n정확도: {correct}/{len(test_cases)}")
    else:
        print("=" * 60)
        print("LangGraph 전체 파이프라인 테스트")
        print("=" * 60)
        app = build_graph(chroma_dir=args.chroma_dir)

        pipeline_test_cases: list[tuple[str, str]] = [
            ("오늘 날씨 어때?", "guardrail 테스트"),
            ("이 사업의 예산은 얼마인가요?", "단일문서 사실추출 테스트"),
        ]

        for question, desc in pipeline_test_cases:
            print(f"\n[{desc}]")
            print(f"질문: {question}")
            result = app.invoke(
                {"question": question, "history": []},
                config={"configurable": {"thread_id": f"test_{desc[:5]}"}},
            )
            print(f"유형: {result.get('question_type')}")
            print(f"답변: {result.get('answer', '')[:200]}")
            print("-" * 40)
