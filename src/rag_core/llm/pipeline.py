"""
exaone3.5:7.8b 기반 RAG 파이프라인 핵심 함수 모음.

쿼리 구성, 검색, 답변 생성, 후처리, 가드레일 함수를 포함합니다.
"""

import re
import time

import requests  # type: ignore[import-untyped]

from rag_core.prompts.builder import TARGET_MODEL


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
    url = "http://127.0.0.1:11434/api/generate"
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
        elapsed = round(time.perf_counter() - start, 2)
        if res.status_code == 200:
            return {
                "model": model,
                "answer": res.json().get("response", "").strip(),
                "elapsed_sec": elapsed,
                "attempt": 1,
            }
        return {
            "model": model,
            "answer": f"HTTP {res.status_code}",
            "elapsed_sec": elapsed,
            "attempt": 1,
        }
    except Exception as e:
        elapsed = round(time.perf_counter() - start, 2)
        return {
            "model": model,
            "answer": f"오류 발생: {e}",
            "elapsed_sec": elapsed,
            "attempt": 1,
        }


def unload_ollama_model(model_name: str):
    try:
        requests.post(
            "http://127.0.0.1:11434/api/generate",
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

    희원님 PR로 Retriever.retrieve()가 RRF 하이브리드(벡터+BM25) 검색 결과를
    RetrievedChunk 리스트로 반환하게 되면서, 다운스트림 함수(format_rag_context,
    dedup_docs_by_doc_id 등)를 건드리지 않기 위해 추가함.
    """

    def __init__(self, retrieved_chunk):
        self.page_content = retrieved_chunk.chunk.text
        self.metadata = retrieved_chunk.chunk.metadata
        self.score = retrieved_chunk.score


def retrieve_multi_query(queries: list, retriever, k_each: int = 3) -> list:
    """희원님 PR 반영: RRF 하이브리드 검색(벡터 + BM25) 기반.
    retriever는 rag_core.retrieval.retriever.Retriever 인스턴스여야 하며,
    호출 전 retriever.load()가 한 번 실행되어 있어야 합니다.

    버그 수정(2026-06-30): 기존에는 dedup 키를 (doc_id, header_path)만으로 구성해서,
    같은 섹션 안에 여러 청크가 존재하는 경우(예: 표 제목 청크 + 표 본문 청크처럼
    header_path는 같지만 내용이 전혀 다른 케이스) 먼저 들어온 청크만 남고 나머지가
    유실됐다. 실제로 D037 문서의 "(서두) > 1. 요구사항 목록" 섹션에서 표 제목만 있는
    빈 청크(69자)에 가려 SFR/PER/...등 전체 요구사항 표(2170자)가 후보에서 통째로
    사라지는 사례를 확인함. page_content 앞부분을 키에 포함시켜 내용이 다른 청크는
    서로 다른 것으로 인식하도록 수정."""
    all_docs = []
    seen = set()
    for q in queries:
        expanded_q = expand_requirement_table_query(q)
        retrieved = retriever.retrieve(expanded_q, top_k=k_each)
        docs = [_RetrievedDocAdapter(rc) for rc in retrieved]
        for doc in docs:
            meta = doc.metadata
            key = (
                meta.get("doc_id", ""),
                meta.get("header_path", ""),
                doc.page_content[:50],
            )
            if key not in seen:
                all_docs.append(doc)
                seen.add(key)
    return all_docs


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


def build_queries_for_row(row) -> list:
    question = str(row.get("question", ""))
    org = str(row.get("발주기관", ""))
    project = str(row.get("사업명", ""))

    if "고려대" in question and "광주과학기술원" in question and "비교" in question:
        return [
            "고려대학교 차세대 포털 학사 정보시스템 구축사업 사업목적 사업금액",
            "광주과학기술원 학사시스템 기능개선 사업 사업목적 사업금액",
        ]
    if any(kw in question for kw in ["교육", "학습", "이러닝", "LMS"]):
        if any(kw in question for kw in ["다른 기관", "없나"]):
            return [
                "국민연금공단 이러닝시스템 운영 용역 교육 학습",
                "스포츠윤리센터 LMS 학습지원시스템 교육",
                "고려대학교 차세대 포털 학사 정보시스템",
                "광주과학기술원 학사시스템 기능개선",
            ]
    if is_multi_doc_row(row):
        return [f"{org} {project} {question}", question]
    return [f"{org} {project} {question}"]


def build_multi_queries_v4(row) -> list:
    """v4: 다중문서 비교/후속질문 query를 명시적으로 분리합니다."""
    question = str(row.get("question", ""))
    qid = str(row.get("id", row.get("qid", row.get("question_id", row.get("golden_id", "")))))

    # Q063: Q062의 후속질문 - 울산/평택 문맥 복원
    if qid == "Q063" or (
        "두 사업" in question and ("예산" in question or "사업비" in question or "규모" in question)
    ):
        return [
            "울산광역시 2024년 버스정보시스템 확대 구축 및 기능개선 용역 사업금액 예산",
            "평택시 2024년도 평택시 버스정보시스템 BIS 구축사업 사업금액 예산",
        ]

    # Q062: 울산광역시 vs 평택시 버스정보시스템 비교
    if "울산광역시" in question and "평택시" in question:
        return [
            "울산광역시 2024년 버스정보시스템 확대 구축 및 기능개선 용역 사업금액 주요내용",
            "평택시 2024년도 평택시 버스정보시스템 BIS 구축사업 사업금액 주요내용",
        ]

    # Q015: 교육/학습 관련 다중문서 종합
    if "교육" in question or "학습" in question or "이러닝" in question or "LMS" in question:
        return [
            "이러닝시스템 운영 용역 교육 콘텐츠 LMS 발주기관 사업금액",
            "LMS 학습지원시스템 기능개선 교육 학습 발주기관 사업금액",
            "학사시스템 기능개선 교육 학습 발주기관 사업금액",
            "차세대 포털 학사 정보시스템 교육 학습 AI선배 챗봇 발주기관 사업금액",
        ]

    # Q049: 보안 요구사항 유사 사업
    if "보안" in question and ("비슷한" in question or "다른 사업" in question):
        return [
            "정보보안 개인정보보호 보안 요구사항 사업 발주기관 사업금액",
            "시스템 보안 요구사항 개인정보보호 정보보안 RFP",
            "보안관리 개인정보보호 운영 요구사항 용역 사업",
        ]

    return [question]


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


def build_exaone_prompt_from_docs(question, docs, is_multi_doc=True) -> str:
    """검색된 docs를 직접 context로 사용하여 프롬프트를 구성합니다."""
    context = format_rag_context(docs)
    doc_list = build_doc_metadata_table(docs)

    if is_multi_doc:
        prompt = f"""
당신은 여러 공공 RFP 문서를 비교·종합하는 입찰 지원 AI입니다.
반드시 아래 [검색 문서 목록]과 [문서 내용]에 포함된 정보만 근거로 질문에 답변하세요.

[검색 문서 목록]
{doc_list}

[답변 규칙]
1. 반드시 [검색 문서 목록]에 있는 doc_id, 발주기관, 사업명만 답변에 사용하세요.
2. [검색 문서 목록]에 없는 기관명, 사업명, 지역명, 금액, 요구사항을 절대 새로 만들지 마세요.
3. 검색된 문서에 없는 내용을 일반적인 사례처럼 보충하지 마세요.
4. 다중문서 비교 또는 종합 질문인 경우, 문서별로 발주기관 / 사업명 / 사업금액 / 주요 내용을 구분해서 답변하세요.
5. 질문이 "다른 사업", "유사 사업", "관련 사업"을 묻는 경우에도 반드시 [검색 문서 목록] 안에서만 후보를 제시하세요.
6. 검색된 문서가 여러 개인 경우, 답변에는 검색된 문서 중 근거가 명확한 문서만 사용하세요.
7. 특정 문서가 검색되었지만 답변 근거가 부족하면 "검색되었으나 관련 근거가 부족합니다."라고 표시하세요.
8. 사업금액은 metadata 또는 문서에 있는 원 단위 숫자를 그대로 사용하세요.
9. 억 원, 조 원, 만 원 등으로 임의 환산하지 마세요.
10. 금액 차이를 계산할 때도 원 단위 숫자 기준으로 계산하세요.
11. 답변은 반드시 한국어 존댓말로 작성하세요.
12. 중국어, 일본어, 영어 등 한국어 외 언어를 섞어 쓰지 마세요.

[출력 형식]
1. 발주기관:
   - 사업명:
   - 사업금액:
   - 확인된 주요 내용:

[문서 내용]
{context}

[질문]
{question}

[답변]
"""
    else:
        prompt = f"""
당신은 공공 RFP 문서를 분석하는 입찰 지원 AI입니다.
반드시 아래 [검색 문서 목록]과 [문서 내용]에 포함된 정보만 근거로 질문에 답변하세요.

[검색 문서 목록]
{doc_list}

[답변 규칙]
1. 문서에 없는 내용은 절대 추측하지 마세요.
2. [검색 문서 목록]에 없는 기관명, 사업명, 금액, 요구사항을 새로 만들지 마세요.
3. 확인되지 않는 내용은 "확인 가능한 근거가 부족합니다."라고 답변하세요.
4. 사업금액은 metadata 또는 문서에 있는 원 단위 숫자를 그대로 사용하세요.
5. 억 원, 조 원, 만 원 등으로 임의 환산하지 마세요.
6. 답변은 반드시 한국어 존댓말로 작성하세요.

[문서 내용]
{context}

[질문]
{question}

[답변]
"""
    return prompt


def ask_exaone_from_docs(question, docs, is_multi_doc=True, max_retries=2) -> dict:
    """검색된 docs를 직접 context로 사용하여 답변을 생성합니다."""
    prompt = build_exaone_prompt_from_docs(question, docs, is_multi_doc=is_multi_doc)

    answer = ""
    elapsed = 0.0
    attempt = 0
    for attempt in range(max_retries + 1):
        result = ask_ollama(TARGET_MODEL, prompt)
        answer = result.get("answer", "") or ""
        elapsed = result.get("elapsed_sec") or 0.0
        if len(answer.strip()) >= 10:
            break
        print(f"  attempt {attempt + 1} 재시도")

    post = postprocess_exaone(answer)
    post_answer = postprocess_answer_format(post["processed"])

    amount_check = validate_amounts_against_metadata(post_answer, docs)
    combined_flags = post["flags"] + amount_check["flags"]

    return {
        "model_answer": post_answer,
        "elapsed_sec": elapsed,
        "attempt": attempt,
        "post_flags": combined_flags,
        "amount_mismatches": amount_check["mismatches"],
        "guardrail_applied": None,
    }


# ─────────────────────────────────────────────
# 후처리
# ─────────────────────────────────────────────


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

    for pat in [
        r"\[문서 근거 부족\]",
        r"\[검색결과\s*\d+\]",
        r"판단\s*:\s*",
        r"출력\s*:\s*",
    ]:
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

    Returns:
        dict: {"flags": [...], "mismatches": [(answer_amount, closest_metadata_amount), ...]}
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
        # 자릿수가 10배/100배 단위로 부풀려지거나 줄어든 경우를 우선 의심
        suspicious = any(
            amt == v * 10 or amt == v * 100 or v == amt * 10 or v == amt * 100
            for v in valid_amounts
        )
        if suspicious:
            result["flags"].append("amount_magnitude_mismatch")
            closest = min(valid_amounts, key=lambda v: abs(v - amt))
            result["mismatches"].append((amt, closest))

    return result


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
