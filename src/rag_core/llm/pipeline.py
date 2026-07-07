"""
exaone3.5:7.8b 기반 RAG 파이프라인 핵심 함수 모음.

쿼리 구성, 검색, 답변 생성, 후처리, 가드레일 함수를 포함합니다.
"""

import os
import re
import time
from typing import Optional

import requests

from rag_core.prompts.builder import TARGET_MODEL, build_prompt as _build_prompt_from_template
from rag_core.exceptions import LLMConnectionError, LLMError, LLMTimeoutError

# Ollama 엔드포인트 환경 변수로 주입 (기본값: http://127.0.0.1:11434)
_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


# ─────────────────────────────────────────────
# Ollama 연동
# ─────────────────────────────────────────────


def get_model_options(model: str) -> dict:
    return {
        "temperature": 0.1,
        "num_predict": 1024,
        "top_p": 0.9,
    }


def ask_ollama(model, prompt):
    """Ollama API를 호출해 답변을 생성합니다.

    관측성/예외 매핑 개선 반영: 예전에는 연결 실패든 타임아웃이든
    모든 예외를 여기서 삼켜 {"answer": f"오류 발생: {e}"} 문자열로 뭉개서
    반환했습니다. 이러면 API 계층에서 "요청 문제(422)"인지 "Ollama 연결
    문제(502)"인지 "타임아웃(504)"인지 구분할 방법이 없었습니다.
    이제는 requests의 예외를 rag_core.exceptions의 도메인 예외로 변환해
    던지고, API 계층(api/errors.py)이 이 타입만 보고 HTTP 상태 코드로
    번역합니다. 이 함수는 더 이상 연결/타임아웃 오류를 리턴값으로 감추지
    않으므로, 호출부는 이 함수가 예외를 던질 수 있다는 전제로 호출해야
    합니다(재시도가 필요하면 호출부에서 LLMConnectionError/LLMTimeoutError를
    잡아 처리하세요. ask_exaone_from_docs()가 그 예시입니다).
    """
    url = f"{_OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
        "options": get_model_options(model),
    }
    start = time.perf_counter()
    try:
        res = requests.post(url, json=payload, timeout=300)
    except requests.exceptions.Timeout as e:
        raise LLMTimeoutError(
            f"Ollama({_OLLAMA_BASE_URL}) 응답이 제한 시간(300s) 내에 오지 않았습니다: {e}"
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise LLMConnectionError(
            f"Ollama({_OLLAMA_BASE_URL}) 서버에 연결할 수 없습니다: {e}"
        ) from e
    except requests.exceptions.RequestException as e:
        # 위 두 경우 외의 requests 예외(잘못된 URL 등)도 도메인 예외로 변환해
        # 원본 예외를 그대로 흘리지 않습니다.
        raise LLMError(f"Ollama 요청 중 오류가 발생했습니다: {e}") from e

    elapsed = round(time.perf_counter() - start, 2)
    if res.status_code == 200:
        try:
            answer_text = res.json().get("response", "").strip()
        except ValueError as e:
            raise LLMError(f"Ollama 응답을 JSON으로 해석할 수 없습니다: {e}") from e
        return {
            "model": model,
            "answer": answer_text,
            "elapsed_sec": elapsed,
            "attempt": 1,
        }
    return {
        "model": model,
        "answer": f"HTTP {res.status_code}",
        "elapsed_sec": elapsed,
        "attempt": 1,
    }


def unload_ollama_model(model_name: str):
    try:
        requests.post(
            f"{_OLLAMA_BASE_URL}/api/generate",
            json={"model": model_name, "prompt": "", "keep_alive": 0},
            timeout=10,
        )
        print(f"{model_name} 언로드 완료")
    except Exception:
        pass


# ─────────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────────


def format_money(value):
    try:
        v = float(value)
        if v <= 0:
            return "metadata 미확인"
        return f"{int(v):,}원"
    except Exception:
        return "metadata 미확인"


def format_rag_context(docs) -> str:
    blocks = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        block = f"""[검색 결과 {i}]
문서명: {meta.get("문서명", "미확인")}
사업명: {meta.get("사업명", "미확인")}
발주기관: {meta.get("발주기관", "미확인")}
사업금액: {format_money(meta.get("사업금액", 0))}
입찰참여시작일: {meta.get("입찰참여시작일", "<unknown>")}
입찰참여마감일: {meta.get("입찰참여마감일", "<unknown>")}
섹션: {meta.get("header_path", "미확인")}
내용:
{doc.page_content[:800]}"""
        blocks.append(block)
    return "\n\n---\n\n".join(blocks)


def dedup_docs_by_doc_id(docs) -> list:
    """doc_id 기준으로 중복 문서를 제거합니다."""
    seen = set()
    result = []
    for doc in docs:
        doc_id = doc.metadata.get("doc_id", "")
        if doc_id not in seen:
            seen.add(doc_id)
            result.append(doc)
    return result


# ─────────────────────────────────────────────
# 검색
# ─────────────────────────────────────────────

TABLE_REQUIREMENT_KEYWORDS = (
    "요구사항 목록 요구사항 총괄표 "
    "SFR 기능 요구사항 "
    "PSR 성능 요구사항 "
    "ISR 인터페이스 요구사항 "
    "SER 보안 요구사항 "
    "ECR 제약사항 "
    "DAR 데이터 요구사항 "
    "TAR 테스트 요구사항 "
    "COR 프로젝트 관리 요구사항 "
    "PMR 프로젝트 지원 요구사항"
)

REQ_TABLE_TRIGGERS = [
    "요구사항",
    "기능 요구사항",
    "성능 요구사항",
    "연계",
    "연계 시스템",
    "인터페이스",
    "시스템 범위",
    "구축 범위",
    "개선 범위",
    "기능개선",
]


def expand_requirement_table_query(query: str) -> str:
    """표/요구사항 계열 질문에만 요구사항 표 키워드를 보강합니다."""
    query = str(query)

    if any(trigger in query for trigger in REQ_TABLE_TRIGGERS):
        if "SFR" not in query and "PSR" not in query:
            return f"{query} {TABLE_REQUIREMENT_KEYWORDS}"

    return query


class _RetrievedDocAdapter:
    """RetrievedChunk(.chunk.text/.chunk.metadata) -> 기존 코드가 기대하는
    doc.page_content / doc.metadata 형태로 변환하는 어댑터.

    Retriever.retrieve()가 RRF 하이브리드(벡터+BM25) 검색 결과를 도입하면서
    RetrievedChunk 리스트로 반환하게 되었고, 다운스트림 함수(format_rag_context,
    dedup_docs_by_doc_id 등)를 건드리지 않기 위해 추가함.
    """

    def __init__(self, retrieved_chunk):
        self.page_content = retrieved_chunk.chunk.text
        self.metadata = retrieved_chunk.chunk.metadata
        self.score = retrieved_chunk.score


def retrieve_multi_query(
    queries: list, retriever, k_each: int = 3, max_chunks_per_doc: Optional[int] = None
) -> list:
    """RRF 하이브리드 검색(벡터 + BM25) 기반 반영.
    retriever는 rag_core.retrieval.retriever.Retriever 인스턴스여야 하며,
    호출 전 retriever.load()가 한 번 실행되어 있어야 합니다.

    버그 수정(2026-06-30): 기존에는 dedup 키를 (doc_id, header_path)만으로 구성해서,
    같은 섹션 안에 여러 청크가 존재하는 경우(예: 표 제목 청크 + 표 본문 청크처럼
    header_path는 같지만 내용이 전혀 다른 케이스) 먼저 들어온 청크만 남고 나머지가
    유실됐다. 실제로 D037 문서의 "(서두) > 1. 요구사항 목록" 섹션에서 표 제목만 있는
    빈 청크(69자)에 가려 SFR/PER/...등 전체 요구사항 표(2170자)가 후보에서 통째로
    사라지는 사례를 확인함. page_content 앞부분을 키에 포함시켜 내용이 다른 청크는
    서로 다른 것으로 인식하도록 수정.

    Args:
        max_chunks_per_doc: 한 쿼리당 특정 doc_id에서 가져올 청크 수 상한.
            None(기본값)이면 제한 없음 — retrieve_single_doc_chunks_v5()처럼
            한 문서를 깊게 파야 하는 단일문서 검색은 반드시 이 기본값을 써야
            합니다. 다중문서 비교/종합 질문(예: "울산광역시와 평택시 ~ 차이점은?")
            에서는 한 문서의 청크가 스코어 상위권을 독점해서 비교 대상 문서가
            top-k 밖으로 밀려나는 현상이 확인되어(Q061), 호출부가 이 값을
            명시적으로 지정해 문서 다양성을 확보할 수 있게 했습니다. 제한을
            걸 때는 후보를 더 넉넉히 가져온 뒤(top_k*4) 상한을 적용합니다.
    """
    all_docs = []
    seen = set()
    for q in queries:
        expanded_q = expand_requirement_table_query(q)
        fetch_k = k_each * 4 if max_chunks_per_doc else k_each
        retrieved = retriever.retrieve(expanded_q, top_k=fetch_k)
        docs = [_RetrievedDocAdapter(rc) for rc in retrieved]

        per_doc_count: dict = {}
        added_this_query = 0
        for doc in docs:
            meta = doc.metadata
            doc_id = meta.get("doc_id", "")

            if max_chunks_per_doc and per_doc_count.get(doc_id, 0) >= max_chunks_per_doc:
                continue

            key = (doc_id, meta.get("header_path", ""), doc.page_content[:50])
            if key not in seen:
                all_docs.append(doc)
                seen.add(key)
                per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1
                added_this_query += 1

            if max_chunks_per_doc and added_this_query >= k_each:
                break

    return all_docs


def retrieve_multi_query_majority(
    queries: list,
    retriever,
    k_each: int = 10,
    max_chunks_per_doc: int = 2,
    top_n_docs: int = 1,
) -> list:
    """다중문서 비교/종합 질문 전용: 쿼리별 top-k 후보 중 doc_id 다수결로
    노이즈 문서를 걸러냅니다.

    retrieve_multi_query()는 max_chunks_per_doc로 "한 문서가 청크를 몇 개
    가져갈지"는 제한하지만, "애초에 몇 개의 서로 다른 문서가 섞여 들어올지"는
    제한하지 않습니다. 실제로 split_comparison_entities()가 만든 서브쿼리
    (예: "한국철도공사 예약발매시스템 개량 ISMP 용역 사업금액 사업목적
    주요내용")로 top-10을 가져오면, 목표 문서(D017) 외에 무관한 문서 4~6개가
    함께 후보에 섞여 들어오는 현상이 확인됐습니다. 이 노이즈가 실제로
    답변 hallucination으로 이어진 사례도 재현됨(한국철도공사 사업금액을
    답변에서 엉뚱한 노이즈 문서인 D010의 금액 316,800,000원으로 답함 —
    실제 정답은 470,000,000원).

    "1등 문서만 채택"(top-1) 방식도 시도했으나, 쿼리 1등과 2등의 검색
    점수 차이가 근소하고 실제로는 2등 문서가 정답인 경우(대검찰청 케이스:
    1등 D046 0.0292 vs 2등이자 정답인 D053 0.0268, 그러나 top-10 중
    8개가 D053)가 확인되어 정답을 통째로 놓치는 부작용이 있었습니다.
    그래서 "1등"이 아니라 "top-k 후보 안에서 가장 많이 등장한 doc_id"를
    채택하는 다수결 방식으로 변경했습니다. Golden QA 다중문서 비교/종합
    케이스(Q010, Q036, Q057, Q061, Q062, Q089) 및 한국철도공사 vs 대검찰청
    케이스에서 노이즈 없이 목표 문서만 정확히 채택되는 것을 확인했습니다.

    Args:
        queries: split_comparison_entities() 등이 생성한 서브쿼리 리스트.
        k_each: 서브쿼리 하나당 가져올 후보 청크 수(다수결 판단용 표본).
        max_chunks_per_doc: 채택된 doc_id에서 실제로 담을 청크 수 상한.
        top_n_docs: 서브쿼리 하나당 채택할 doc_id 개수(기본 1개).
            3개 이상 엔티티를 비교하는 질문은 이 함수의 대상이 아닙니다
            (split_comparison_entities()가 A/B 2개까지만 분리합니다).
    """
    from collections import Counter

    picked: list = []
    seen_keys = set()
    for q in queries:
        expanded_q = expand_requirement_table_query(q)
        retrieved = retriever.retrieve(expanded_q, top_k=k_each)
        docs = [_RetrievedDocAdapter(rc) for rc in retrieved]
        if not docs:
            continue

        counts = Counter(doc.metadata.get("doc_id", "") for doc in docs)
        top_doc_ids = [doc_id for doc_id, _ in counts.most_common(top_n_docs)]

        for doc_id in top_doc_ids:
            count = 0
            for doc in docs:
                if doc.metadata.get("doc_id", "") != doc_id:
                    continue
                key = (doc_id, doc.metadata.get("header_path", ""), doc.page_content[:50])
                if key in seen_keys:
                    continue
                picked.append(doc)
                seen_keys.add(key)
                count += 1
                if count >= max_chunks_per_doc:
                    break

    return picked


# ─────────────────────────────────────────────
# 쿼리 구성
# ─────────────────────────────────────────────

MULTI_DOC_TYPES = {"다중문서_비교", "다중문서_종합"}


def is_multi_doc_row(row) -> bool:
    """Golden QA row 기준으로 다중문서 질문 여부를 판단합니다."""
    question = str(row.get("question", ""))
    question_type = str(row.get("question_type", ""))

    if "다중문서" in question_type:
        return True

    multi_keywords = [
        "비교",
        "두 사업",
        "다른 기관",
        "다른 사업",
        "비슷한",
        "공통점",
        "차이점",
        "전체",
        "가장",
    ]
    return any(keyword in question for keyword in multi_keywords)


# 도메인 동의어 확장 사전 — 특정 기관명이 아니라 주제어 기반으로 검색 recall을
# 보강합니다. TABLE_REQUIREMENT_KEYWORDS(요구사항 표 확장)와 같은 원리로,
# "이 도메인이면 이런 유사 용어들도 같이 검색하라"는 일반 규칙입니다.
# 예전에는 "고려대학교 차세대 포털...", "국민연금공단 이러닝시스템..."처럼
# 벡터DB에 실제로 존재하는 특정 기관명·사업명을 그대로 문자열로 박아넣었는데,
# 이러면 그 문서들이 있을 때만 동작하고 새로운 기관의 문서가 들어오면 전혀
# 도움이 안 됩니다. 도메인 동의어는 특정 문서 존재 여부와 무관하게 항상
# 유효한 확장이라 일반화 성능이 더 좋습니다.
DOMAIN_QUERY_EXPANSIONS = [
    (("교육", "학습", "이러닝", "LMS"), "교육 학습 이러닝 LMS 학사 정보시스템 교육콘텐츠"),
    (("보안",), "정보보안 개인정보보호 보안 요구사항 보안관리 RFP"),
    (("재난", "안전"), "재난 안전 재난관리 재난안전데이터 위기대응"),
]


def expand_domain_query(question: str) -> str:
    """질문에 특정 도메인 키워드가 있으면 그 도메인의 일반 동의어를 덧붙여
    검색 recall을 높입니다.

    특정 기관명이나 사업명을 하드코딩하지 않으므로, 벡터DB에 새 기관의
    문서가 추가돼도 계속 동작합니다(일반화 성능 확보).
    """
    question = str(question)
    for triggers, synonyms in DOMAIN_QUERY_EXPANSIONS:
        if any(t in question for t in triggers):
            return f"{question} {synonyms}"
    return question


def build_queries_for_row(row) -> list:
    question = str(row.get("question", ""))
    org = str(row.get("발주기관", ""))
    project = str(row.get("사업명", ""))

    if is_multi_doc_row(row):
        return [f"{org} {project} {question}", expand_domain_query(question)]
    return [f"{org} {project} {question}"]


_COMPARISON_CONJUNCTION_PATTERN = re.compile(
    r"(.+?)(?:와|과)(?!학)\s*(.+?)(?:의)?\s*(?:차이점|차이|공통점|비교|각각)"
)


def split_comparison_entities(question: str) -> list:
    """ "A와 B의 차이점은?"류 질문에서 A, B를 분리해 서브쿼리를 만듭니다.

    두 대상을 한 문장으로 검색하면 한쪽 문서의 청크가 검색 결과 상위권을
    독점해서 다른 쪽 문서가 top-k 밖으로 밀려나는 현상이 확인됐습니다(Q061:
    "울산광역시와 평택시 ~ 차이점은?" 검색 시 top-20 중 18개가 평택시 청크로
    채워지고 울산 문서는 19~20위로 겨우 걸림). 특정 기관명을 하드코딩하지
    않고, 질문의 접속사 구조("A와 B")만으로 일반화된 방식입니다.

    처음에는 각 엔티티 뒤에 원본 질문 전체를 그대로 붙였으나("{entity} {question}"),
    이러면 상대방 엔티티 이름이 노이즈로 함께 딸려 들어가 검색이 그쪽으로
    완전히 쏠리는 더 심한 문제가 확인됐습니다(Q010: "고려대학교 차세대 포털
    사업과 광주과학기술원 학사시스템 사업을 비교해줘"에서 "광주과학기술원"
    쿼리로 검색했는데도 "고려대학교"가 함께 붙어 top-20 전부가 고려대 문서로
    채워짐 — Q061보다 심한 완전 잠식). 그래서 원본 질문 대신 비교 의도를
    나타내는 짧고 중립적인 접미사만 붙이는 방식으로 변경했습니다. 상대방
    엔티티 이름이 전혀 섞이지 않아 서로 간섭하지 않습니다.

    Returns:
        분리에 성공하면 [A 관련 쿼리, B 관련 쿼리], 실패하면 빈 리스트.
    """
    question = str(question)
    m = _COMPARISON_CONJUNCTION_PATTERN.search(question)
    if not m:
        return []

    entity_a, entity_b = m.group(1).strip(), m.group(2).strip()
    if len(entity_a) < 2 or len(entity_b) < 2:
        return []

    return [
        f"{entity_a} 사업금액 사업목적 주요내용",
        f"{entity_b} 사업금액 사업목적 주요내용",
    ]


def build_multi_queries_v4(row, context_hint: str = "") -> list:
    """v4: 다중문서 비교/종합 질문의 쿼리를 구성합니다.

    Args:
        context_hint: "두 사업의 예산 규모를 비교해줘"처럼 질문 자체에는
            비교 대상 기관/사업명이 명시되지 않는 멀티턴 후속 질문의 경우,
            이전 턴에서 확인된 기관·사업명을 대화 맥락(LangGraph의 conversation
            memory)에서 전달받아 채워 넣는 용도입니다. 비워두면(기본값) 질문
            원문만으로 검색합니다.

    예전에는 골든 QA의 특정 id(예: qid == "Q063")를 직접 확인해서 정답
    기관명을 하드코딩한 쿼리를 반환했습니다. 이건 평가셋 정답을 몰래
    엿보는 것과 같아서 실제 서비스에서는 전혀 재현되지 않는 방식이었습니다
    (실사용자의 질문에는 골든 QA id가 없습니다). 여기서는 그 대신 호출부가
    실제 대화 맥락을 context_hint로 넘겨주는 방식으로 바꿨습니다 — 맥락이
    없으면 정직하게 "이 질문만으로는 검색이 부정확할 수 있다"는 상태를
    그대로 노출합니다(하드코딩으로 감추지 않습니다).

    질문 자체에 비교 대상이 명시된 경우(예: "울산광역시와 평택시 ~ 차이점은?")는
    split_comparison_entities()로 엔티티별 서브쿼리를 만들어 검색 다양성을
    높입니다. 이 서브쿼리들은 retrieve_multi_query() 호출 시 max_chunks_per_doc
    옵션과 함께 써야 실제 효과가 있습니다(한쪽 문서 독점 방지).
    """
    question = str(row.get("question", ""))

    if context_hint:
        return [f"{context_hint} {question}", expand_domain_query(question)]

    comparison_queries = split_comparison_entities(question)
    if comparison_queries:
        return comparison_queries

    return [expand_domain_query(question)]


def get_first_available_value(row, candidates) -> str:
    for col in candidates:
        if col in row.index:
            value = row.get(col, "")
            if value is not None and str(value).strip() not in ["", "nan", "None"]:
                return str(value).strip()
    return ""


def build_single_doc_query_base(row) -> str:
    """단일문서 질문에서 기준 문서를 좁히기 위한 query base를 생성합니다."""
    doc_id = get_first_available_value(
        row, ["doc_id", "target_doc_id", "source_doc_id", "document_id"]
    )
    org = get_first_available_value(row, ["발주기관", "기관명"])
    project = get_first_available_value(row, ["사업명", "용역명", "사업명_원문"])
    file_name = get_first_available_value(row, ["file_name", "doc_name", "문서명"])

    parts = [p for p in [doc_id, org, project, file_name] if p]
    return " ".join(parts).strip()


def build_multi_queries_v5(row) -> list:
    """v5: v4 보정을 유지하되, 단일문서 질문에 doc_id/발주기관/사업명을 query에 포함합니다."""
    question = str(row.get("question", ""))
    question_type = str(row.get("question_type", ""))

    if "단일문서" in question_type:
        base = build_single_doc_query_base(row)
        if base:
            return [
                f"{base} {question}",
                base,
            ]

    return build_multi_queries_v4(row)


# ─────────────────────────────────────────────
# 문서 수 제한
# ─────────────────────────────────────────────


def limit_docs_for_question(question, docs) -> list:
    """보안 유사 사업 질문은 상위 5개 문서만 사용합니다."""
    question = str(question)
    if "보안" in question and ("비슷한" in question or "다른 사업" in question):
        return docs[:5]
    return docs


def limit_docs_for_question_v5(question, docs, row=None) -> list:
    """단일문서 질문은 기준 문서 정보가 있는 경우 상위 1개 문서만 사용합니다."""
    question_type = str(row.get("question_type", "")) if row is not None else ""

    if "단일문서" in question_type:
        base = build_single_doc_query_base(row)
        if base:
            return docs[:1]

    return limit_docs_for_question(question, docs)


def retrieve_single_doc_chunks_v5(row, retriever, k_each: int = 12, max_chunks: int = 8):
    """단일문서 질문용 검색 함수. 기준 문서의 chunk를 여러 개 유지합니다."""
    queries = build_multi_queries_v5(row)
    raw_docs = retrieve_multi_query(queries, retriever, k_each=k_each)

    if not raw_docs:
        return [], queries, None

    selected_vector_doc_id = raw_docs[0].metadata.get("doc_id")
    same_doc_chunks = [
        doc for doc in raw_docs if doc.metadata.get("doc_id") == selected_vector_doc_id
    ]
    same_doc_chunks = same_doc_chunks[:max_chunks]

    return same_doc_chunks, queries, selected_vector_doc_id


# ─────────────────────────────────────────────
# 프롬프트 구성
# ─────────────────────────────────────────────


def build_doc_metadata_table(docs) -> str:
    rows = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        rows.append(
            f"{i}. doc_id: {meta.get('doc_id')}\n"
            f"   - 발주기관: {meta.get('발주기관')}\n"
            f"   - 사업명: {meta.get('사업명')}\n"
            f"   - 사업금액: {meta.get('사업금액')}\n"
            f"   - 파일명: {meta.get('file_name')}"
        )
    return "\n".join(rows)


def build_exaone_prompt_from_docs(question, docs, is_multi_doc=False) -> str:
    """검색된 docs를 직접 context로 사용하여 프롬프트를 구성합니다.
    templates/ 폴더의 .txt 파일을 읽어서 프롬프트를 생성합니다.
    """
    context = format_rag_context(docs)
    doc_list = build_doc_metadata_table(docs)
    return _build_prompt_from_template(
        question=question,
        context=context,
        doc_list=doc_list,
        is_multi_doc=is_multi_doc,
    )


def generate_followup(question: str, answer: str) -> str:
    """답변 후 연관 질문 3개와 문체 변환 유도 문구를 생성합니다.

    템플릿 파일(prompt_template_followup_v1.txt)을 읽어서 프롬프트를 구성하고,
    모델 호출 결과를 그대로 반환합니다. 실패 시 빈 문자열을 반환합니다.
    """
    try:
        from pathlib import Path

        template_path = (
            Path(__file__).parent.parent
            / "prompts"
            / "templates"
            / "prompt_template_followup_v1.txt"
        )
        with open(template_path, encoding="utf-8") as f:
            template = f.read()
        prompt = template.format(question=question, answer=answer)
        result = ask_ollama(TARGET_MODEL, prompt)
        return result.get("answer", "") or ""
    except Exception as e:
        print(f"[generate_followup 오류] {e}")
        return ""


def ask_exaone_from_docs(question, docs, is_multi_doc=False, max_retries=2) -> dict:
    """검색된 docs를 직접 context로 사용하여 답변을 생성합니다.

    ask_ollama()가 연결 실패/타임아웃 시 예외(LLMConnectionError/
    LLMTimeoutError)를 던지도록 바뀌었으므로(관측성/예외 매핑 개선 대응), 여기서는
    그 예외를 잡아 max_retries만큼 재시도하고, 재시도를 다 써도 실패하면
    예외를 그대로 위(API 계층)로 전파합니다. API 계층은 이 타입을 보고
    502/504로 매핑합니다 — 여기서 빈 답변으로 조용히 넘기면 그 매핑이
    동작하지 않습니다.
    """
    prompt = build_exaone_prompt_from_docs(question, docs, is_multi_doc=is_multi_doc)

    answer = ""
    elapsed = 0.0
    attempt = 0
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = ask_ollama(TARGET_MODEL, prompt)
        except (LLMConnectionError, LLMTimeoutError) as e:
            last_error = e
            print(f"  attempt {attempt + 1} 재시도 (사유: {e})")
            continue

        last_error = None
        answer = result.get("answer", "") or ""
        elapsed = result.get("elapsed_sec") or 0.0
        if len(answer.strip()) >= 10:
            break
        print(f"  attempt {attempt + 1} 재시도")

    if last_error is not None and not answer.strip():
        raise last_error

    post = postprocess_exaone(answer)
    post_answer = postprocess_answer_format(post["processed"])
    post_answer = postprocess_model_answer(post_answer, question)

    if not str(post_answer).strip():
        post_answer = (
            "확인 가능한 근거가 부족합니다.\n"
            "문서에는 질문한 항목이 명시되어 있지 않습니다.\n"
            "문서에서 확인 가능한 관련 내용도 없습니다."
        )
        post["flags"].append("empty_answer_fallback")

    amount_check = validate_amounts_against_metadata(post_answer, docs)
    org_check = detect_unlisted_orgs(post_answer, docs)
    combined_flags = post["flags"] + amount_check["flags"] + org_check["flags"]

    followup = generate_followup(question, post_answer)

    return {
        "model_answer": post_answer,
        "elapsed_sec": elapsed,
        "attempt": attempt,
        "post_flags": combined_flags,
        "amount_mismatches": amount_check["mismatches"],
        "unlisted_orgs": org_check["unlisted_orgs"],
        "guardrail_applied": None,
        "related_questions": followup,
        "style_prompt": "💡 이 내용을 다른 문체로 변환해 드릴 수 있어요. 원하시는 형식을 선택해 주세요: [공문서체] [사업제안서체] [보고서체]",
    }


# ─────────────────────────────────────────────
# 후처리
# ─────────────────────────────────────────────


def clean_markdown_bullets(text: str) -> str:
    """문체 변환 결과에서 줄 시작의 중복 하이픈 목록을 정리합니다."""
    text = str(text)

    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        while stripped.startswith("- -"):
            stripped = "- " + stripped[3:].lstrip()

        lines.append(indent + stripped)

    return "\n".join(lines)


_FORECAST_OVERCLAIM_PATTERN = re.compile(
    r"[^,.!?\n]*(향상|개선|효율성|효과적|안정성|보안성|편의성|신뢰성)[^,.!?\n]*"
    r"(것으로 보입니다|것으로 보임|것으로 보여짐|것으로 보이나|것으로 예상|것으로 기대|"
    r"기대됩니다|기대되나|기대되며|기대된다|기대됨|기대할 수 있습니다|"
    r"판단됩니다|판단됨|사료됩니다|사료됨)"
    r"[,.!?]?"
)

# "완료"는 두 가지 얼굴로 나타난다.
# (1) "1. 복수의결권주식 기능 개선 완료"처럼 정당한 목록 항목 끝에 붙는 경우 -
#     이 경우 문장/줄 전체를 지우면 항목 내용까지 통째로 사라진다(Q082 1차 회귀).
# (2) "완료됨에 따라, ~향상될 것으로 보임"처럼 완료를 전제로 한 결론 절을
#     이끄는 경우 - 이 경우는 "완료됨에 따라" 같은 연결어미까지 통째로 걸어야
#     "완료"만 지웠을 때 "됨에 따라"처럼 조사만 붕 뜨는 문제(Q082 2차 회귀)가
#     안 생긴다.
# 그래서 (2)의 흔한 연결어미 조합을 먼저 구 단위로 제거하고, 그 다음 (1)처럼
# 단독으로 남은 "완료"를 경계 기준 토큰 단위로 제거한다. 문장 전체를 지우지
# 않으므로 목록 항목의 나머지 내용은 보존된다. 이후 이어지는 결론 문장이
# 여전히 "~향상될 것으로 보임"처럼 근거 없는 전망이면 _FORECAST_OVERCLAIM_PATTERN이
# 문장 단위로 마저 제거한다.
_COMPLETION_CLAUSE_PATTERN = re.compile(
    r"완료(?:됨에\s*따라|됨으로써|함에\s*따라|함으로써|되어|되며|"
    r"되었으며|하였으며|되었으나|하였으나|되었지만|하였지만|"
    r"되었습니다|하였습니다)\s*,?\s*"
)
_COMPLETION_TOKEN_PATTERN = re.compile(r"\s*완료(?=[\s\)\-\n]|[.,!?]|$)")
_IN_PROGRESS_TOKEN_PATTERN = re.compile(r"\s*진행\s*중(?=[\s\)\-\n]|[.,!?]|$)")


def clean_rewrite_overstatements(text: str, style: str) -> str:
    """문체 변환 결과에서 원문보다 강한 단정/과장 표현을 원문 수준으로 되돌립니다.

    - 사업제안서체: "명시되어 있습니다"가 "충족"처럼 이행 완료를 뜻하는 단정
      표현으로 바뀌는 문제를 되돌립니다. 처음에는 "응답 시간 충족"과 같은
      구(phrase) 단위 문자열 치환으로 처리했으나, 모델이 "응답 시간" 충족"처럼
      따옴표를 사이에 끼워 넣는 변형을 만들어내 필터를 피해가는 사례(Q011)가
      확인되어, "충족"이라는 단어 자체를 문맥과 무관하게 "명시"로 치환하는
      방식으로 변경했습니다.
    - 공통: "안정성과 보안성이 향상될 것으로 보입니다"처럼 매번 표현이 조금씩
      달라지는 결론부 과장 문장을 정규식으로 탐지해 문장 단위로 제거합니다.
      "보입니다" 외에 "보임"처럼 구어체 종결어미로 바뀌는 변형(Q082)도
      추가로 대응했습니다.
    - 공통: 원본에는 없던 완료/진행 상태 단정("구현 완료", "완료됨에 따라" 등)을
      임의로 추가하는 사례가 반복적으로 관찰되어(Q082), "완료"의 흔한 연결어미
      조합은 구 단위로, 단독으로 남은 "완료"/"진행 중"은 토큰 단위로 제거합니다.
      한때 문장 전체를 지우는 방식으로 처리했으나, 목록 항목 끝에 "완료"가
      붙는 경우 항목 내용까지 통째로 사라지는 부작용이 있어(Q082 재발) 이
      방식으로 되돌렸습니다.
    """
    text = str(text)

    if style == "사업제안서":
        text = re.sub(r"충족", "명시", text)

    forbidden_phrases = {
        "효율성과 안정성 향상": "효율성과 안정성 관련 요구사항 명시",
        "효율성 향상": "효율성 관련 요구사항 명시",
        "안정성 향상": "안정성 관련 요구사항 명시",
        "사용자 경험 개선": "사용자 입력 간소화 관련 내용 명시",
        "방안 마련 필요": "방안 제시 필요",
        "시스템 고도화 계획": "시스템 관련 요구사항 명시",
    }
    for src, dst in forbidden_phrases.items():
        text = text.replace(src, dst)

    text = _COMPLETION_CLAUSE_PATTERN.sub("", text)
    text = _COMPLETION_TOKEN_PATTERN.sub("", text)
    text = _IN_PROGRESS_TOKEN_PATTERN.sub("", text)

    text = _FORECAST_OVERCLAIM_PATTERN.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def strip_ungrounded_duration_mention(rewritten: str, last_answer: str) -> str:
    """원본(last_answer)에 없는 "다년 사업"/"3개년" 언급이 문체 변환 결과에만
    나타나면 해당 문장을 제거합니다.

    Q042("담당 PM의 이름은 누구인가?") 사례에서, 원본 답변은 "확인 가능한
    근거가 부족합니다."뿐인데도 사업제안서체 변환 결과의 "추진 내용"에
    "문서에서는 다년 사업임을 언급하고 있습니다."가 삽입되는 현상이 확인됐습니다.
    원인은 rewrite 템플릿 지시문 안에 있던 리터럴 예시 문장을 모델이 조건과
    무관하게 암기해 복사한 것으로 보입니다. 템플릿에서 해당 리터럴 문장은
    제거했지만, 프롬프트 수정만으로 완전히 막힌다는 보장이 없어 이 함수를
    이중 방어로 추가했습니다.
    """
    rewritten = str(rewritten)
    last_answer = str(last_answer)

    duration_markers = ("다년 사업", "3개년")
    if any(m in rewritten for m in duration_markers) and not any(
        m in last_answer for m in duration_markers
    ):
        sentences = re.split(r"(?<=[.!?])\s+|\n+", rewritten)
        filtered = [s for s in sentences if not any(m in s for m in duration_markers)]
        result = " ".join(s.strip() for s in filtered if s.strip())
        rewritten = re.sub(r"\s{2,}", " ", result).strip()

    return rewritten


def rewrite_answer_style(last_answer: str, style: str) -> str:
    """원본 답변을 지정된 문체(공문서/사업제안서/보고서)로 변환하고,
    변환 과정에서 생기는 과장/단정 표현까지 후처리한 최종 결과를 반환합니다.

    문체 변환은 지금까지 노트북 테스트 루프와 LangGraph 노드 양쪽에서 각자
    템플릿을 읽고 ask_ollama()를 호출한 뒤, clean_markdown_bullets()/
    clean_rewrite_overstatements()를 개별적으로(그리고 종종 빠뜨린 채) 적용하는
    구조였습니다. 후처리 호출이 호출부마다 따로 관리되면 한쪽에서 잡은 문제가
    다른 쪽엔 반영되지 않는 위험이 있어(예: 노트북에서는 "충족"/"완료" 필터를
    적용했는데 LangGraph 노드는 원본 rewrite 템플릿 결과만 그대로 반환하는 경우),
    문체 변환 + 후처리를 이 함수 하나로 캡슐화했습니다. 호출하는 쪽은 style만
    지정해서 이 함수를 부르면 되고, 후처리 누락 걱정을 하지 않아도 됩니다.

    Args:
        last_answer: 문체 변환 대상이 되는 원본(RAG) 답변
        style: "공문서" | "사업제안서" | "보고서"

    Returns:
        문체 변환 + 과장/단정 표현 후처리가 끝난 최종 문자열.
        템플릿 파일이 없거나 호출 실패 시 빈 문자열을 반환합니다.
    """
    from pathlib import Path

    try:
        template_path = (
            Path(__file__).parent.parent
            / "prompts"
            / "templates"
            / f"prompt_template_rewrite_{style}_v1.txt"
        )
        with open(template_path, encoding="utf-8") as f:
            template = f.read()

        prompt = template.format(last_answer=last_answer)
        result = ask_ollama(TARGET_MODEL, prompt)
        rewritten = result.get("answer", "") or ""

        rewritten = clean_markdown_bullets(rewritten)
        rewritten = clean_rewrite_overstatements(rewritten, style)
        rewritten = strip_ungrounded_duration_mention(rewritten, last_answer)

        return rewritten
    except Exception as e:
        print(f"[rewrite_answer_style 오류] style={style}: {e}")
        return ""


def postprocess_exaone(text: str) -> dict:
    """외국어 혼입, 금액 환산, 빈 답변 등을 점검하고 정제합니다."""
    result: dict = {"original": text, "processed": text, "flags": [], "blocked": False}

    foreign_patterns = {
        "중국어": r"[\u4e00-\u9fff]",
        "일본어": r"[\u3040-\u30ff]",
        "키릴": r"[\u0400-\u04ff]",
    }
    detected = [lang for lang, pat in foreign_patterns.items() if re.search(pat, text)]
    if detected:
        result["flags"].append(f"foreign_mix:{','.join(detected)}")
        lines = text.split("\n")
        clean_lines = [
            line
            for line in lines
            if not any(re.search(pat, line) for pat in foreign_patterns.values())
        ]
        cleaned = "\n".join(clean_lines).strip()
        result["processed"] = cleaned if len(cleaned) >= 20 else text

    money_patterns = [
        r"약\s*\d+억\s*원",
        r"약\s*\d+조\s*원",
        r"\(\s*약\s*\d+억",
        r"\(\s*약\s*\d+조",
    ]
    if any(re.search(p, result["processed"]) for p in money_patterns):
        result["flags"].append("money_conversion_risk")

    for pat in [r"\[문서 근거 부족\]", r"\[검색결과\s*\d+\]", r"판단\s*:\s*", r"출력\s*:\s*"]:
        result["processed"] = re.sub(pat, "", result["processed"]).strip()

    if not result["processed"].strip():
        result["processed"] = (
            "죄송합니다. 답변을 생성하는 중 오류가 발생했습니다. 다시 질문해 주세요."
        )
        result["flags"].append("empty_response")
        result["blocked"] = True

    return result


def postprocess_answer_format(answer) -> str:
    """금액 앞에 붙은 '약' 표현을 제거합니다."""
    if not isinstance(answer, str):
        return answer
    answer = re.sub(r"약\s+([0-9,]+원)", r"\1", answer)
    answer = re.sub(r"약([0-9,]+원)", r"\1", answer)
    return answer.strip()


def validate_amounts_against_metadata(answer: str, docs) -> dict:
    """답변에 등장하는 금액(N원)이 검색된 문서의 metadata 사업금액과
    자릿수 단위로 일치하는지 점검합니다.

    exaone이 큰 금액(10자리 이상)을 그대로 옮겨 적는 과정에서 자릿수를
    잘못 불리는(예: 14억 -> 140억/1,400억) 환각이 관찰되어 추가한 검증입니다.
    metadata 자체가 정답이라는 보장은 없지만, 적어도 모델이 검색된 문서의
    숫자를 임의로 바꿔 쓰지 않았는지는 확인할 수 있습니다.

    리포팅 정확도 개선(2026-07-03): 기존에는 "가장 가까운" metadata 값을
    절대값 차이(min(valid_amounts, key=lambda v: abs(v - amt)))로 골라
    mismatches에 담았습니다. 그런데 이 "가장 가까운 값"이 실제로 10배/100배
    관계에 있는 값이 아닐 수 있습니다(Q045: 답변 90,000,000원의 실제 원인은
    900,000,000원이 10배 축소된 것인데, 절대값상 더 가까운 100,000,000원이
    엉뚱하게 보고됨). 그래서 이제는 절대값이 아니라 실제로 10배/100배 배율
    관계가 성립하는 후보들만 골라 리스트로 보고합니다. 여러 문서가 우연히
    같은 배율 관계를 만족하면 후보가 여러 개일 수 있으므로, 하나로 단정하지
    않고 전부 보여줍니다.

    Returns:
        dict: {"flags": [...], "mismatches": [(answer_amount, [magnitude_match_candidates]), ...]}
    """
    result: dict = {"flags": [], "mismatches": []}
    if not isinstance(answer, str) or not answer.strip():
        return result

    valid_amounts = set()
    for doc in docs:
        raw = doc.metadata.get("사업금액")
        try:
            v = int(float(raw))
            if v > 0:
                valid_amounts.add(v)
        except (TypeError, ValueError):
            continue

    if not valid_amounts:
        return result

    answer_amounts = [int(m.replace(",", "")) for m in re.findall(r"[\d,]+(?=원)", answer)]

    for amt in answer_amounts:
        if amt in valid_amounts:
            continue
        # 실제로 10배/100배 배율 관계가 성립하는 후보만 수집 (절대값 최근접 아님)
        magnitude_matches = [
            v
            for v in valid_amounts
            if amt == v * 10 or amt == v * 100 or v == amt * 10 or v == amt * 100
        ]
        if magnitude_matches:
            result["flags"].append("amount_magnitude_mismatch")
            result["mismatches"].append((amt, sorted(magnitude_matches)))

    return result


_ORG_SUFFIX_PATTERN = re.compile(
    r"[가-힣A-Za-z0-9]{2,20}(?:부|처|청|원장|공사|공단|진흥원|재단|협회|센터|위원회|대학교|대학원|"
    r"연구원|연구소|의료원|박물관|재활원|평가원|관리원|협력단|산학협력단)"
)

_ORG_STOPWORDS = {
    "검색문서목록",
    "검색결과",
    "발주기관",
    "확인가능한근거",
    "질문한항목",
}


def detect_unlisted_orgs(answer: str, docs) -> dict:
    """답변에 등장하는 기관명이 검색된 문서 목록에 실제로 존재하는지 점검합니다.

    카테고리형 질문("의료 관련 기관이 발주한 IT 사업은?")에서 검색이 목표
    문서를 충분히 찾지 못하면(Q057: top-10이 전부 한 문서의 청크로 채워짐),
    "검색되었으나 관련 근거가 부족합니다"라고 답하는 대신 문서에 없는
    기관명을 일반 상식으로 나열하는 hallucination이 확인됐습니다(보건복지부,
    질병관리청, 국립암센터 등 — [검색 문서 목록]에 없는 기관명, 2번/15번/17번
    규칙을 동시에 위반).

    이 문제의 근본 원인(검색 단계에서 문서 다양성이 확보되지 않는 것)은
    langgraph_router.py의 검색 로직 개선이 필요한 별개 사안이라 이 함수만으로
    해결되지 않습니다. 다만 검색이 빈약한 상황에서도 최소한 답변에 없는
    기관명이 새로 만들어져 나가는 것은 막을 수 있어, 방어선으로 추가합니다.

    금액 검증(validate_amounts_against_metadata)과 마찬가지로 플래그만
    남기고 답변 자체를 임의로 고치지는 않습니다 — 기관명이 포함된 문장을
    통째로 삭제하면 문장 구조가 부자연스러워지거나 다른 유효한 내용까지
    같이 날아갈 위험이 있고, 정규식 기반 기관명 추출은 완벽하지 않아
    오탐(false positive) 가능성도 있기 때문입니다. 대신 이 flag를 근거로
    사람이 검토하거나, 추후 반복 재현 시 프롬프트/검색 개선의 근거로
    사용합니다.

    Returns:
        dict: {"flags": [...], "unlisted_orgs": [...]}
    """
    result: dict = {"flags": [], "unlisted_orgs": []}
    if not isinstance(answer, str) or not answer.strip():
        return result

    valid_orgs = set()
    for doc in docs:
        org = str(doc.metadata.get("발주기관", "")).strip()
        if org:
            valid_orgs.add(org)

    if not valid_orgs:
        return result

    candidates = set(_ORG_SUFFIX_PATTERN.findall(answer))

    unlisted = []
    for cand in candidates:
        if cand in _ORG_STOPWORDS:
            continue
        # 답변의 기관명이 valid_orgs 중 하나에 부분 포함되거나(반대 방향 포함)
        # 이미 알려진 기관과 일치하면 정상으로 간주
        if any(cand in org or org in cand for org in valid_orgs):
            continue
        unlisted.append(cand)

    if unlisted:
        result["flags"].append("unlisted_org_mentioned")
        result["unlisted_orgs"] = sorted(set(unlisted))

    return result


def remove_unasked_contact_info(answer: str, question: str) -> str:
    """질문이 연락처를 묻지 않는 경우 답변에서 연락처/문의 안내를 제거합니다."""
    answer = str(answer)
    question = str(question)

    contact_question_keywords = ["연락처", "전화", "이메일", "메일", "담당자", "문의처", "문의"]
    if any(k in question for k in contact_question_keywords):
        return answer

    filtered_lines = []
    for line in answer.splitlines():
        if re.search(r"\b\d{2,3}-\d{3,4}-\d{4}\b", line):
            continue
        if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", line):
            continue
        if any(
            k in line
            for k in [
                "담당",
                "담당자",
                "주무관",
                "전화번호",
                "이메일",
                "연락처",
                "직접 문의",
                "문의하",
            ]
        ):
            continue
        filtered_lines.append(line)

    return "\n".join(filtered_lines).strip()


def enforce_insufficient_answer_policy(answer: str, question: str) -> str:
    """근거 부족 답변에서 일반론, 예시 목록, 문의 안내가 생성되면 보수 답변으로 교정합니다."""
    answer = str(answer).strip()
    question = str(question)

    insufficient_markers = [
        "명시적으로 언급되어 있지 않습니다",
        "명확하게 명시되어 있지 않습니다",
        "명시되어 있지 않습니다",
        "확인 가능한 근거가 부족합니다",
        "구체적인 범위에 대한 정보가",
        "구체적인 정보가",
    ]

    forbidden_markers = [
        "정확히 파악하려면",
        "다음과 같은 정보가 필요",
        "필요할 것입니다",
        "일반적으로",
        "가능성이 높습니다",
        "예상됩니다",
        "추정",
        "직접 문의",
        "문의하는 것이",
        "관련 섹션",
        "첨부 문서",
        "시스템 구성 요소",
        "기능 및 서비스",
        "데이터 흐름",
        "사용자 및 이해관계자",
        "기술 스택",
    ]

    has_insufficient = any(m in answer for m in insufficient_markers)
    has_forbidden = any(m in answer for m in forbidden_markers)

    if has_insufficient and has_forbidden:
        return (
            "확인 가능한 근거가 부족합니다.\n"
            "문서에는 질문한 항목이 명시되어 있지 않습니다.\n"
            "문서에서 확인 가능한 관련 내용도 없습니다."
        )

    return answer


def suppress_duration_estimation(answer: str) -> str:
    """3개년/다년 사업을 개월 수로 환산·추정하는 문장을 통째로 제거합니다.

    prompt_template_v1.txt의 18/19번 규칙("3개년"을 "36개월"로 환산하지 말 것)이
    실제 프롬프트에는 정상 반영되지만, 모델이 이를 무시하고 환산하는 사례(Q107)가
    관찰되어 추가한 후처리 가드레일입니다.

    구(phrase) 단위로만 지우면 "이는 사업이  정확한 개월 수는..."처럼 주어만 남고
    문장이 끊기는 문제가 있어, 해당 표현이 포함된 문장을 통째로 제거하는 방식으로
    변경했습니다.
    """
    answer = str(answer)

    duration_estimation_markers = [
        "36개월",
        "최소 3년",
    ]

    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    filtered = [
        s for s in sentences if not any(marker in s for marker in duration_estimation_markers)
    ]
    result = " ".join(s.strip() for s in filtered if s.strip())
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip()


_SPECULATIVE_CONTENT_MARKERS = [
    "것으로 예상됩니다",
    "것으로 보입니다",
    "것으로 사료됩니다",
    "것으로 추정됩니다",
    "것으로 판단됩니다",
    "예상되는",
    "포함하고 있을 것",
    "다루고 있을 것",
    "가능성이 높습니다",
    "일 가능성이 있습니다",
]


def suppress_speculative_document_content(answer: str) -> str:
    """문서에 실제로 있는 내용을 인용하는 대신, 사업 유형(신규/고도화 등)에
    대한 일반 상식만으로 "RFP에 이런 내용이 있을 것"이라고 추측하는 문장을
    제거합니다.

    Q044("신규 구축 사업과 고도화 사업의 RFP 구성 방식 차이는?")에서 검색된
    문서(인천공항운영서비스 ERP 구축, 한국농수산식품유통공사 고도화 용역)의
    실제 본문 내용은 인용하지 않고, "신규 구축이니 이런 내용을 다루고 있을
    것으로 예상됩니다", "고도화 사업이니 이런 내용을 포함하고 있을 것으로
    보입니다"처럼 사업 유형에 대한 일반 지식만으로 답변을 채우는 사례가
    확인됐습니다. 이는 3번 규칙("검색된 문서에 없는 내용을 일반적인
    사례처럼 보충하지 마세요")과 17번 규칙("가능성이 높습니다" 등 추측
    표현 금지)을 동시에 위반합니다.

    suppress_duration_estimation(), suppress_unrequested_amount_diff()와
    같은 성격의 문제 — 프롬프트에 이미 명시된 규칙을 모델이 무시하는
    경우에 대한 후처리 가드레일입니다. 문장 단위로 제거해 주어만 남고
    문장이 끊기는 것을 방지합니다.

    참고: 근거 부족 상황에서 사용되는 정상적인 안내 문구(예: "확인 가능한
    근거가 부족합니다")는 이 마커들과 겹치지 않으므로 영향받지 않습니다.
    """
    answer = str(answer)

    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    filtered = [
        s for s in sentences if not any(marker in s for marker in _SPECULATIVE_CONTENT_MARKERS)
    ]
    result = " ".join(s.strip() for s in filtered if s.strip())
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip()


_AMOUNT_DIFF_SENTENCE_PATTERN = re.compile(
    r"[^.!?\n]*(?:보다|대비)[^.!?\n]*[\d,]+\s*원[^.!?\n]*(?:더\s*(?:큽니다|많습니다|높습니다)|더\s*(?:작습니다|적습니다|낮습니다))[^.!?\n]*[.!?]?"
)


def suppress_unrequested_amount_diff(answer: str, question: str) -> str:
    """사용자가 명시적으로 차액을 묻지 않았는데도 모델이 두 금액의 차이를
    직접 계산해서 제시하는 문장을 제거합니다.

    prompt_template_multi_v1.txt의 21번 규칙("사용자가 명시적으로 '차이가
    얼마인가요?'라고 묻지 않는 한 뺄셈 결과를 답변에 넣지 마세요")이 실제
    프롬프트에는 정상 반영되지만, 모델이 이를 무시하고 "OO가 OO보다
    12,549,600원 더 큽니다"처럼 계산 결과를 그대로 제시하는 사례가
    반복 확인되어 추가한 후처리 가드레일입니다(suppress_duration_estimation()과
    동일한 성격의 문제 — 프롬프트 규칙만으로는 완전한 통제가 안 됨).

    질문에 "차이가 얼마", "차이는 얼마" 등 차액을 명시적으로 요청하는
    표현이 있으면 이 가드레일을 적용하지 않습니다(21번 규칙 자체가
    그 경우엔 뺄셈 결과 제시를 허용하기 때문입니다).
    """
    answer = str(answer)
    question = str(question)

    explicit_diff_request_markers = ["차이가 얼마", "차이는 얼마", "차액이 얼마", "얼마나 차이"]
    if any(marker in question for marker in explicit_diff_request_markers):
        return answer

    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    filtered = [s for s in sentences if not _AMOUNT_DIFF_SENTENCE_PATTERN.search(s)]
    result = " ".join(s.strip() for s in filtered if s.strip())
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip()


_BROKEN_BOLD_REPEAT_PATTERN = re.compile(r"(\*\*\s*){2,}")


def clean_broken_markdown_bold(text: str) -> str:
    """중첩된 목록 생성 시 깨지는 마크다운 강조(**)를 정리합니다.

    exaone이 깊게 중첩된 목록(대분류 안에 소분류, 그 안에 또 하위 항목)을
    줄바꿈 없이 한 문단으로 생성할 때, "** **", "** ** **"처럼 강조 표시의
    열림/닫힘 상태를 놓치는 현상이 관찰됐습니다(Q033, Q074). 내용 자체(항목
    이름, 순서, 개수)는 정확하고 순수하게 표시(서식)만 깨지는 문제입니다.

    1) "** **"처럼 반복되는 빈 강조를 "**" 하나로 정리합니다.
    2) 정리 후에도 "**" 개수가 홀수(짝이 안 맞음)면, 어느 부분이 진짜
       강조였는지 텍스트만으로는 판단할 수 없으므로, 깨진 별표가 그대로
       노출되는 것보다 안전하게 "**"를 전부 제거합니다(굵게 표시 스타일은
       잃지만 내용은 그대로 보존됩니다).
    """
    text = str(text)
    text = _BROKEN_BOLD_REPEAT_PATTERN.sub("**", text)
    if text.count("**") % 2 != 0:
        text = text.replace("**", "")
    return text.strip()


def postprocess_model_answer(answer: str, question: str) -> str:
    """RAG 원본 답변 후처리."""
    answer = remove_unasked_contact_info(answer, question)
    answer = enforce_insufficient_answer_policy(answer, question)
    answer = suppress_duration_estimation(answer)
    answer = suppress_unrequested_amount_diff(answer, question)
    answer = suppress_speculative_document_content(answer)
    answer = clean_broken_markdown_bold(answer)
    return answer


# ─────────────────────────────────────────────
# 가드레일
# ─────────────────────────────────────────────


def is_score_prediction_question(question) -> bool:
    """기술점수/가격점수 예측형 질문 여부를 판단합니다."""
    question = str(question)
    score_keywords = [
        "기술점수",
        "가격점수",
        "몇 점",
        "점수는",
        "점수 받을",
        "선정 가능성",
        "우선협상",
    ]
    return any(keyword in question for keyword in score_keywords)


def score_prediction_guardrail_answer(question) -> str:
    """점수 예측형 질문에 대한 고정 안내 답변을 반환합니다."""
    return (
        "확인 가능한 근거가 부족합니다.\n\n"
        "기술점수나 가격점수는 실제 제안서 내용, 평가위원 판단, 경쟁사 제안 수준, "
        "정량평가 증빙자료, 가격 산식 등이 함께 반영되어 결정되므로 문서 내용만으로 "
        "특정 점수를 예측하거나 단정할 수 없습니다.\n\n"
        "다만 확인해야 할 항목은 다음과 같습니다.\n"
        "1. 제안요청서의 기술능력평가 배점\n"
        "2. 정량평가 항목과 증빙자료\n"
        "3. 정성평가 항목과 평가 기준\n"
        "4. 가격평가 산식\n"
        "5. 경쟁 입찰자의 제안 수준\n\n"
        "따라서 특정 점수를 제시하기보다는 평가 기준과 준비해야 할 증빙자료를 기준으로 "
        "제안 전략을 점검하는 것이 적절합니다."
    )
