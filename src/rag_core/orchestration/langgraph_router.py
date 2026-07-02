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
    app = build_graph(chroma_dir="/data/vector_db/vector_db_v4")
    result = app.invoke(
        {"question": "이 사업의 예산은?", "history": []},
        config={"configurable": {"thread_id": "session_1"}}
    )
    print(result["answer"])
"""

from __future__ import annotations

import collections
import os
import sys
from typing import Any, Literal, Optional, TypedDict

import requests  # type: ignore[import-untyped]
from langgraph.checkpoint.memory import MemorySaver  # type: ignore[import-not-found]
from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]

sys.path.insert(0, "src")
from rag_core.retrieval.retriever import Retriever
from rag_core.llm.pipeline import (
    ask_exaone_from_docs,
    is_score_prediction_question,
    score_prediction_guardrail_answer,
)
from rag_core.prompts.prompt import exaone_rag_qa_prompt, exaone_multi_doc_prompt  # type: ignore[import-untyped]


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
CHROMA_DIR_DEFAULT = os.getenv("CHROMA_DIR", "/data/vector_db/vector_db_v4")
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
# LLM 호출 (Ollama → OpenAI fallback)
# ──────────────────────────────────────────────


def call_ollama(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """Ollama로 LLM 호출. 실패 시 RuntimeError 발생."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["response"].strip()
    except Exception as e:
        raise RuntimeError(f"Ollama 호출 실패: {e}") from e


def call_llm_with_fallback(prompt: str) -> str:
    """Ollama 1차 시도 → 실패 시 OpenAI fallback."""
    try:
        return call_ollama(prompt)
    except RuntimeError as e:
        print(f"[LLM] Ollama 실패 → OpenAI fallback: {e}")
        try:
            from openai import OpenAI

            client = OpenAI()
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                timeout=60,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e2:
            return f"죄송합니다. 현재 답변 생성에 실패했습니다. ({e2})"


# ──────────────────────────────────────────────
# 프롬프트 구성
# ──────────────────────────────────────────────


def build_prompt(question: str, chunks: list[str], question_type: str) -> str:
    """지우님 prompt.py 최종본 import 버전."""
    context = "\n\n".join(chunks) if chunks else "검색된 문서가 없습니다."

    if question_type in ("multi_doc_compare", "multi_doc_summary"):
        template: str = str(exaone_multi_doc_prompt)
    else:
        template = str(exaone_rag_qa_prompt)

    return template.format(context=context, question=question)


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
    """단일문서_사실추출: Hybrid RRF 검색 top_k=10."""
    question = state.get("rewritten_question", state["question"])
    try:
        retriever = get_retriever()
        retrieved = retriever.retrieve(question, top_k=TOP_K_DEFAULT)
        chunks = [r.chunk.text for r in retrieved]
        sources = [{"doc_id": r.chunk.doc_id, "score": r.score} for r in retrieved]
        return {"retrieved_chunks": chunks, "retrieved_sources": sources}
    except Exception as e:
        print(f"[Router] Retrieval 오류: {e}")
        return {"retrieved_chunks": [], "retrieved_sources": [], "error": str(e)}


def single_doc_requirement_node(state: RagState) -> dict:
    """단일문서_세부요구사항: top_k=15로 더 넓게 검색."""
    question = state.get("rewritten_question", state["question"])
    try:
        retriever = get_retriever()
        retrieved = retriever.retrieve(question, top_k=TOP_K_REQUIREMENT)
        chunks = [r.chunk.text for r in retrieved]
        sources = [{"doc_id": r.chunk.doc_id, "score": r.score} for r in retrieved]
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
        return [question]


def multi_doc_compare_node(state: RagState) -> dict:
    """다중문서_비교: 쿼리 분리 후 RRF 병합 검색."""
    question = state.get("rewritten_question", state["question"])
    try:
        sub_queries = generate_sub_queries(question)
        retriever = get_retriever()
        all_retrieved_results = []
        for query in sub_queries:
            retrieved = retriever.retrieve(query, top_k=TOP_K_DEFAULT)
            all_retrieved_results.append(retrieved)

        rrf_k = 60
        rrf_scores: collections.defaultdict[str, float] = collections.defaultdict(float)
        doc_map: dict[str, Any] = {}

        for retrieved_list in all_retrieved_results:
            for rank, r in enumerate(retrieved_list, start=1):
                key = r.chunk.text
                rrf_scores[key] += 1.0 / (rrf_k + rank)
                if key not in doc_map:
                    doc_map[key] = r.chunk

        sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        final_top_k = sorted_docs[:TOP_K_DEFAULT]

        chunks = [doc_map[key].text for key, score in final_top_k]
        sources = [
            {"doc_id": doc_map[key].doc_id, "rrf_score": score} for key, score in final_top_k
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
        retriever = get_retriever()
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
    import requests as req

    try:
        resp = req.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": full_prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        raw = resp.json().get("response", "").strip()

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
    history의 마지막 답변을 지정한 문체로 변환.
    지우님 프롬프트 템플릿 수령 후 교체 예정.
    """
    question = state.get("question", "")
    history = state.get("history", [])

    # 변환할 대상 — history 마지막 답변
    if not history:
        return {
            "answer": "변환할 이전 답변이 없습니다. 먼저 RFP에 대해 질문해주세요.",
        }

    last_answer = history[-1].get("answer", "")
    if not last_answer:
        return {
            "answer": "변환할 이전 답변이 없습니다.",
        }

    # 변환 스타일 감지
    if any(kw in question for kw in ["사업제안서", "제안서"]):
        style = "사업제안서"
        style_desc = "사업제안서 형식 (목적, 추진 배경, 기대효과 구조)"
    elif any(kw in question for kw in ["보고서", "보고"]):
        style = "보고서"
        style_desc = "보고서 형식 (제목, 개요, 세부내용, 결론 구조)"
    else:
        style = "공문서"
        style_desc = "공문서 형식 (제목, 수신, 발신, 내용, 끝 구조)"

    # 프롬프트 (지우님 템플릿 수령 전 임시)
    prompt = f"""당신은 공공기관 문서 작성 전문가입니다.
아래 [원본 내용]을 {style_desc}으로 변환하세요.

[변환 규칙]
1. {style} 형식에 맞는 구조를 갖추세요.
2. 내용은 원본과 동일하게 유지하세요. 추가하거나 빼지 마세요.
3. 한국어 공식 문체로 작성하세요.
4. 수치/금액/날짜는 원본 그대로 유지하세요.

[원본 내용]
{last_answer}

[{style} 형식으로 변환]"""

    try:
        import requests as req

        resp = req.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        converted = resp.json().get("response", "").strip()
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

    # retrieved_chunks(텍스트)를 DocAdapter로 변환
    class _SimpleDoc:
        def __init__(self, text: str):
            self.page_content = text
            self.metadata: dict[str, Any] = {}

    docs = [_SimpleDoc(c) for c in chunks]

    try:
        result = ask_exaone_from_docs(question, docs, is_multi_doc=is_multi)
        answer = result.get("model_answer", "")
        related_questions = result.get("related_questions", "")
        style_prompt = result.get("style_prompt", "")
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


def build_graph(chroma_dir: str = CHROMA_DIR_DEFAULT):
    """
    StateGraph 조립 + MemorySaver 체크포인터로 컴파일.

    Args:
        chroma_dir: ChromaDB 경로 (기본값: /data/vector_db/vector_db_v4)

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

    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


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

        test_cases = [
            ("오늘 날씨 어때?", "guardrail 테스트"),
            ("이 사업의 예산은 얼마인가요?", "단일문서 사실추출 테스트"),
        ]

        for question, desc in test_cases:
            print(f"\n[{desc}]")
            print(f"질문: {question}")
            result = app.invoke(
                {"question": question, "history": []},
                config={"configurable": {"thread_id": f"test_{desc[:5]}"}},
            )
            print(f"유형: {result.get('question_type')}")
            print(f"답변: {result.get('answer', '')[:200]}")
            print("-" * 40)
