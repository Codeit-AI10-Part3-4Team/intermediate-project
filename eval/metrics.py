"""
metrics.py — RFP RAG 파이프라인 평가 지표 (v2)

평가 지표:
    [Retrieval]
    - retrieval_accuracy    : 정답 doc_id가 retrieved chunks에 포함되는지 여부 (0 or 1)
    - context_recall        : 정답 키워드가 retrieved context에 얼마나 포함되는지
    - context_precision     : retrieved context 중 정답과 관련된 비율 (키워드 2개 이상 or 30% 이상)
    - mrr                   : Mean Reciprocal Rank

    [Generation - 임베딩 유사도]
    - semantic_faithfulness : answer와 context의 임베딩 유사도
                              (논문의 Faithfulness와 다름 — 향후 LLM Judge 방식으로 교체 예정)
    - answer_relevance      : question과 answer의 임베딩 유사도
                              (논문의 Answer Relevance와 다름 — 향후 LLM Judge 방식으로 교체 예정)

    [Generation - rule-based]
    - response_time_ms      : 응답 생성 시간 (ms)
    - response_time_sec     : 응답 생성 시간 (sec)
    - is_empty              : 빈 답변 여부
    - has_foreign_lang      : 일본어/중국어/깨진문자 혼입 여부 (영어는 허용)
    - has_money_risk        : 금액 환산 위험 여부
    - is_too_short          : 답변이 너무 짧은지 여부
    - single_doc_many_docs  : 단일문서 질문인데 여러 문서 검색된 경우

    [실험 메타정보]
    - experiment_name       : 실험 이름 (예: "baseline", "reranker_large")
    - embedding_model       : 임베딩 모델 (예: "bge-m3")
    - chunk_strategy        : 청킹 전략 (예: "D1_overlap100_merge")
    - reranker              : Reranker 모델 (예: "bge-reranker-large", "none")
    - llm                   : LLM 모델 (예: "exaone3.5:7.8b")
    - timestamp             : 평가 실행 시각

    [저장]
    - save_results          : 평가 결과를 CSV로 저장

TODO (Sprint 3):
    - context_recall: kiwipiepy 형태소 분석기 기반으로 개선
    - semantic_faithfulness: LLM Judge 방식으로 교체
    - answer_relevance: LLM Judge 방식으로 교체

사용법:
    from metrics import evaluate_retrieval, evaluate_generation, evaluate_all, save_results
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────
# 임베딩 모델 싱글턴 (bge-m3)
# ──────────────────────────────────────────────

_embedding_model = None


def _get_embedding_model():
    """
    bge-m3 임베딩 모델을 싱글턴으로 로드.
    최초 호출 시 한 번만 로드하고 이후 재사용.
    """
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            print("[metrics] bge-m3 로드 중...")
            _embedding_model = SentenceTransformer("BAAI/bge-m3")
            print("[metrics] bge-m3 로드 완료")
        except Exception as e:
            print(f"[metrics] 임베딩 모델 로드 실패: {e}")
            _embedding_model = None
    return _embedding_model


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """두 벡터의 코사인 유사도 계산."""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


# ──────────────────────────────────────────────
# Retrieval 평가 지표
# ──────────────────────────────────────────────

def retrieval_accuracy(
    golden_doc_id: str,
    retrieved_doc_ids: list[str],
) -> float:
    """
    정답 doc_id가 retrieved chunks에 포함되는지 여부.

    Args:
        golden_doc_id    : 골든 데이터셋의 정답 doc_id (예: "D001")
        retrieved_doc_ids: Retriever가 반환한 doc_id 리스트

    Returns:
        1.0 (포함) or 0.0 (미포함)
    """
    if not golden_doc_id or not retrieved_doc_ids:
        return 0.0
    return 1.0 if golden_doc_id in retrieved_doc_ids else 0.0


def context_recall(
    golden_answer: str,
    retrieved_chunks: list[str],
    min_keyword_len: int = 2,
) -> float:
    """
    정답(golden_answer)의 핵심 키워드가 retrieved context에 얼마나 포함되는지.

    NOTE (Sprint 3 TODO):
        현재 공백 기준 단순 토크나이징 사용.
        kiwipiepy 형태소 분석기 기반으로 개선 예정.
        예) "사업기간은 계약일부터 180일이다" →
            현재: ["사업기간은", "계약일부터", "180일이다"]
            형태소: ["사업", "기간", "계약", "일", "180", "일"]
            → 형태소 기반이 "계약일로부터 180일" 같은 유사 표현도 매칭 가능

    Args:
        golden_answer   : 골든 데이터셋의 정답 텍스트
        retrieved_chunks: Retriever가 반환한 청크 텍스트 리스트
        min_keyword_len : 키워드 최소 길이 (기본값: 2)

    Returns:
        0.0 ~ 1.0 사이의 recall 점수
    """
    if not golden_answer or not retrieved_chunks:
        return 0.0
    keywords = _extract_keywords(golden_answer, min_keyword_len)
    if not keywords:
        return 0.0
    context_text = " ".join(retrieved_chunks)
    matched = sum(1 for kw in keywords if kw in context_text)
    return matched / len(keywords)


def context_precision(
    golden_answer: str,
    retrieved_chunks: list[str],
    min_keyword_len: int = 2,
    min_keyword_count: int = 2,
    min_keyword_ratio: float = 0.3,
) -> float:
    """
    retrieved chunks 중 정답과 관련된 청크의 비율.

    관련 청크 판단 기준 (둘 중 하나 충족 시 relevant):
        - 정답 키워드가 2개 이상 포함
        - 정답 키워드의 30% 이상 포함

    Args:
        golden_answer      : 골든 데이터셋의 정답 텍스트
        retrieved_chunks   : Retriever가 반환한 청크 텍스트 리스트
        min_keyword_len    : 키워드 최소 길이 (기본값: 2)
        min_keyword_count  : relevant 판단 최소 키워드 수 (기본값: 2)
        min_keyword_ratio  : relevant 판단 최소 키워드 비율 (기본값: 0.3)

    Returns:
        0.0 ~ 1.0 사이의 precision 점수
    """
    if not golden_answer or not retrieved_chunks:
        return 0.0
    keywords = _extract_keywords(golden_answer, min_keyword_len)
    if not keywords:
        return 0.0

    relevant_chunks = 0
    for chunk in retrieved_chunks:
        matched = sum(1 for kw in keywords if kw in chunk)
        # 키워드 2개 이상 OR 30% 이상 포함 시 relevant
        if matched >= min_keyword_count or (matched / len(keywords)) >= min_keyword_ratio:
            relevant_chunks += 1

    return relevant_chunks / len(retrieved_chunks)


def mrr(
    golden_doc_id: str,
    retrieved_doc_ids: list[str],
) -> float:
    """
    Mean Reciprocal Rank.
    정답 doc_id가 retrieved 리스트의 몇 번째 순위에 있는지.

    Args:
        golden_doc_id    : 골든 데이터셋의 정답 doc_id
        retrieved_doc_ids: Retriever가 순서대로 반환한 doc_id 리스트

    Returns:
        1/rank (정답이 1번째면 1.0, 2번째면 0.5, 없으면 0.0)

    Example:
        mrr("D001", ["D002", "D001", "D003"])  # → 0.5
        mrr("D001", ["D001", "D002", "D003"])  # → 1.0
        mrr("D001", ["D002", "D003", "D004"])  # → 0.0
    """
    if not golden_doc_id or not retrieved_doc_ids:
        return 0.0
    for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id == golden_doc_id:
            return 1.0 / rank
    return 0.0


# ──────────────────────────────────────────────
# Generation 평가 지표 (임베딩 유사도)
# ──────────────────────────────────────────────

def semantic_faithfulness(
    answer: str,
    retrieved_chunks: list[str],
) -> float:
    """
    answer와 retrieved context의 임베딩 유사도.

    NOTE:
        논문에서 말하는 Faithfulness(답변이 context에 없는 내용을 말했는가)와 다름.
        현재 구현은 Semantic Similarity 방식임.
        향후 LLM Judge 방식으로 교체 예정 (Sprint 3 TODO).

    Args:
        answer          : LLM이 생성한 답변 텍스트
        retrieved_chunks: Retriever가 반환한 청크 텍스트 리스트

    Returns:
        0.0 ~ 1.0 사이의 유사도 점수
        임베딩 모델 로드 실패 시 -1.0 반환
    """
    if not answer or not retrieved_chunks:
        return 0.0
    model = _get_embedding_model()
    if model is None:
        return -1.0
    context_text = " ".join(retrieved_chunks)
    answer_emb = model.encode(answer, normalize_embeddings=True)
    context_emb = model.encode(context_text, normalize_embeddings=True)
    return _cosine_similarity(answer_emb, context_emb)


def answer_relevance(
    question: str,
    answer: str,
) -> float:
    """
    question과 answer의 임베딩 유사도.

    NOTE:
        논문에서 말하는 Answer Relevance와 다름.
        현재 구현은 Semantic Similarity 방식임.
        향후 LLM Judge 방식으로 교체 예정 (Sprint 3 TODO).

    Args:
        question: 사용자 질문 텍스트
        answer  : LLM이 생성한 답변 텍스트

    Returns:
        0.0 ~ 1.0 사이의 유사도 점수
        임베딩 모델 로드 실패 시 -1.0 반환
    """
    if not question or not answer:
        return 0.0
    model = _get_embedding_model()
    if model is None:
        return -1.0
    question_emb = model.encode(question, normalize_embeddings=True)
    answer_emb = model.encode(answer, normalize_embeddings=True)
    return _cosine_similarity(question_emb, answer_emb)


def response_time(start_time: float, end_time: float) -> dict[str, float]:
    """
    응답 생성 시간 (ms, sec 동시 반환).

    Args:
        start_time: time.perf_counter() 시작 시각
        end_time  : time.perf_counter() 종료 시각

    Returns:
        {"response_time_ms": float, "response_time_sec": float}

    Example:
        start = time.perf_counter()
        answer = llm.generate(prompt)
        end = time.perf_counter()
        times = response_time(start, end)
        # {"response_time_ms": 893.0, "response_time_sec": 0.893}
    """
    elapsed = end_time - start_time
    return {
        "response_time_ms" : elapsed * 1000,
        "response_time_sec": elapsed,
    }


# ──────────────────────────────────────────────
# Generation 평가 지표 (rule-based)
# ──────────────────────────────────────────────

def is_empty(answer: str) -> bool:
    """빈 답변 여부."""
    return not answer or not answer.strip()


def has_foreign_lang(answer: str) -> bool:
    """
    일본어/중국어/깨진문자 혼입 여부.

    NOTE:
        영어(ISO, ICT, AI, API, DB, Cloud, GPU 등)는 RFP 도메인 특성상 허용.
        일본어(히라가나/가타카나), 중국어(한자), 기타 비정상 문자만 감지.

    Args:
        answer: LLM이 생성한 답변 텍스트

    Returns:
        True (외국어 혼입) or False
    """
    if not answer:
        return False
    # 일본어: \u3040-\u30FF, 중국어 간체/번체: \u4E00-\u9FFF
    pattern = re.compile(r'[\u3040-\u30FF\u4E00-\u9FFF]')
    return bool(pattern.search(answer))


def has_money_risk(answer: str) -> bool:
    """
    금액 환산 위험 여부.
    '약 X억', '약 X천만' 등 추정 금액 표현 감지.
    """
    if not answer:
        return False
    risk_patterns = [
        r'약\s*\d+\s*억',
        r'약\s*\d+\s*천만',
        r'약\s*\d+\s*백만',
        r'약\s*\d+\s*만\s*원',
        r'추정\s*\d+',
        r'\d+\s*억\s*원\s*내외',
    ]
    return any(re.search(p, answer) for p in risk_patterns)


def is_too_short(answer: str, threshold: int = 10) -> bool:
    """답변이 너무 짧은지 여부 (기본값: 10자 미만)."""
    if not answer:
        return True
    return len(answer.strip()) < threshold


def single_doc_many_docs(
    question_type: str,
    retrieved_doc_ids: list[str],
) -> bool:
    """
    단일문서 질문인데 여러 문서가 검색된 경우.

    Args:
        question_type    : 골든 데이터셋의 question_type 컬럼 값
        retrieved_doc_ids: Retriever가 반환한 doc_id 리스트
    """
    single_doc_types = ["단일문서_사실추출", "single_doc", "factual"]
    is_single = any(t in question_type for t in single_doc_types)
    return is_single and len(set(retrieved_doc_ids)) > 1


# ──────────────────────────────────────────────
# 통합 평가 함수
# ──────────────────────────────────────────────

def evaluate_retrieval(
    golden_doc_id: str,
    golden_answer: str,
    retrieved_doc_ids: list[str],
    retrieved_chunks: list[str],
) -> dict:
    """
    Retrieval 전체 지표를 한 번에 계산.

    Returns:
        {
            "retrieval_accuracy": float,
            "context_recall"    : float,
            "context_precision" : float,
            "mrr"               : float,
        }
    """
    return {
        "retrieval_accuracy": retrieval_accuracy(golden_doc_id, retrieved_doc_ids),
        "context_recall"    : context_recall(golden_answer, retrieved_chunks),
        "context_precision" : context_precision(golden_answer, retrieved_chunks),
        "mrr"               : mrr(golden_doc_id, retrieved_doc_ids),
    }


def evaluate_generation(
    question: str,
    answer: str,
    retrieved_chunks: list[str],
    question_type: str,
    retrieved_doc_ids: list[str],
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    use_embedding: bool = True,
) -> dict:
    """
    Generation 전체 지표를 한 번에 계산.

    Args:
        question         : 사용자 질문 텍스트
        answer           : LLM이 생성한 답변 텍스트
        retrieved_chunks : Retriever가 반환한 청크 텍스트 리스트
        question_type    : 골든 데이터셋의 question_type 컬럼 값
        retrieved_doc_ids: Retriever가 반환한 doc_id 리스트
        start_time       : 응답 시작 시각 (time.perf_counter())
        end_time         : 응답 종료 시각 (time.perf_counter())
        use_embedding    : 임베딩 유사도 지표 사용 여부 (기본값: True)

    Returns:
        {
            "semantic_faithfulness": float or None,
            "answer_relevance"     : float or None,
            "response_time_ms"     : float or None,
            "response_time_sec"    : float or None,
            "is_empty"             : bool,
            "has_foreign_lang"     : bool,
            "has_money_risk"       : bool,
            "is_too_short"         : bool,
            "single_doc_many_docs" : bool,
        }
    """
    rt_ms, rt_sec = None, None
    if start_time is not None and end_time is not None:
        times = response_time(start_time, end_time)
        rt_ms = times["response_time_ms"]
        rt_sec = times["response_time_sec"]

    faith = semantic_faithfulness(answer, retrieved_chunks) if use_embedding else None
    relevance = answer_relevance(question, answer) if use_embedding else None

    return {
        "semantic_faithfulness": faith,
        "answer_relevance"     : relevance,
        "response_time_ms"     : rt_ms,
        "response_time_sec"    : rt_sec,
        "is_empty"             : is_empty(answer),
        "has_foreign_lang"     : has_foreign_lang(answer),
        "has_money_risk"       : has_money_risk(answer),
        "is_too_short"         : is_too_short(answer),
        "single_doc_many_docs" : single_doc_many_docs(question_type, retrieved_doc_ids),
    }


def evaluate_all(
    golden_doc_id: str,
    golden_answer: str,
    retrieved_doc_ids: list[str],
    retrieved_chunks: list[str],
    question: str,
    answer: str,
    question_type: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    use_embedding: bool = True,
    experiment_name: str = "default",
    embedding_model: str = "bge-m3",
    chunk_strategy: str = "D1_overlap100_merge",
    reranker: str = "bge-reranker-large",
    llm: str = "exaone3.5:7.8b",
) -> dict:
    """
    Retrieval + Generation 전체 지표 + 실험 메타정보를 한 번에 계산.

    Args:
        (Retrieval/Generation 인자 생략)
        experiment_name : 실험 이름 (기본값: "default")
        embedding_model : 임베딩 모델명 (기본값: "bge-m3")
        chunk_strategy  : 청킹 전략 (기본값: "D1_overlap100_merge")
        reranker        : Reranker 모델명 (기본값: "bge-reranker-large")
        llm             : LLM 모델명 (기본값: "exaone3.5:7.8b")

    Returns:
        실험 메타정보 + Retrieval 지표 + Generation 지표 통합 딕셔너리

    Example:
        result = evaluate_all(
            ...,
            experiment_name="reranker_large_k20",
            embedding_model="bge-m3",
            chunk_strategy="D1_overlap100_merge",
            reranker="bge-reranker-large",
            llm="exaone3.5:7.8b",
        )
        # CSV 컬럼: experiment_name | embedding_model | chunk_strategy | reranker | llm
        #           | retrieval_accuracy | context_recall | ... | semantic_faithfulness | ...
    """
    experiment_info = {
        "experiment_name": experiment_name,
        "embedding_model": embedding_model,
        "chunk_strategy" : chunk_strategy,
        "reranker"       : reranker,
        "llm"            : llm,
        "timestamp"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    retrieval = evaluate_retrieval(
        golden_doc_id,
        golden_answer,
        retrieved_doc_ids,
        retrieved_chunks,
    )
    generation = evaluate_generation(
        question,
        answer,
        retrieved_chunks,
        question_type,
        retrieved_doc_ids,
        start_time,
        end_time,
        use_embedding,
    )

    return {**experiment_info, **retrieval, **generation}


# ──────────────────────────────────────────────
# 결과 저장
# ──────────────────────────────────────────────

def save_results(
    results: list[dict],
    save_path: str = "./eval/eval_results.csv",
    question_ids: Optional[list[str]] = None,
) -> str:
    """
    평가 결과를 CSV로 저장.

    Args:
        results      : evaluate_all() 결과 딕셔너리 리스트
        save_path    : 저장 경로 (기본값: ./eval/eval_results.csv)
        question_ids : 질문 ID 리스트 (골든 데이터셋의 id 컬럼)

    Returns:
        저장된 파일 경로 문자열

    Example:
        results = []
        for row in golden_df.itertuples():
            result = evaluate_all(
                golden_doc_id=row.doc_id,
                golden_answer=row.answer,
                ...,
                experiment_name="reranker_large_k20",
            )
            result["id"] = row.id
            results.append(result)
        save_results(results, "./eval/eval_results.csv")
    """
    df = pd.DataFrame(results)

    if question_ids is not None:
        df.insert(0, "id", question_ids)

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(save_path, index=False, encoding="utf-8-sig")
    print(f"[metrics] 평가 결과 저장 완료: {save_path}")
    print(f"[metrics] 총 {len(df)}개 항목, {len(df.columns)}개 컬럼")
    return save_path


# ──────────────────────────────────────────────
# 내부 유틸 함수
# ──────────────────────────────────────────────

def _extract_keywords(text: str, min_len: int = 2) -> list[str]:
    """
    텍스트에서 핵심 키워드 추출.
    공백/특수문자 기준으로 분리 후 최소 길이 이상인 토큰만 반환.

    TODO (Sprint 3): kiwipiepy 형태소 분석기 기반으로 교체
    """
    tokens = re.split(r'[\s,.\-/·:;\"\'()\[\]{}]+', text)
    return [t for t in tokens if len(t) >= min_len]


# ──────────────────────────────────────────────
# 동작 확인
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("[1] Retrieval 평가 테스트")
    print("=" * 60)
    retrieval_result = evaluate_retrieval(
        golden_doc_id="D001",
        golden_answer="이 사업의 예산은 500만원이며 발주기관은 고려대학교입니다.",
        retrieved_doc_ids=["D002", "D001", "D003"],
        retrieved_chunks=[
            "고려대학교 차세대포털 사업 예산은 500만원입니다.",
            "발주기관은 고려대학교이며 사업기간은 6개월입니다.",
        ],
    )
    for k, v in retrieval_result.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("[2] Generation rule-based 평가 테스트 (임베딩 제외)")
    print("=" * 60)
    gen_result = evaluate_generation(
        question="이 사업의 예산은 얼마인가요?",
        answer="이 사업의 예산은 500만원입니다.",
        retrieved_chunks=["고려대학교 차세대포털 사업 예산은 500만원입니다."],
        question_type="단일문서_사실추출",
        retrieved_doc_ids=["D001"],
        use_embedding=False,
    )
    for k, v in gen_result.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("[3] evaluate_all() + 실험 메타정보 테스트")
    print("=" * 60)
    all_result = evaluate_all(
        golden_doc_id="D001",
        golden_answer="이 사업의 예산은 500만원이며 발주기관은 고려대학교입니다.",
        retrieved_doc_ids=["D002", "D001", "D003"],
        retrieved_chunks=["고려대학교 차세대포털 사업 예산은 500만원입니다."],
        question="이 사업의 예산은 얼마인가요?",
        answer="이 사업의 예산은 500만원입니다.",
        question_type="단일문서_사실추출",
        use_embedding=False,
        experiment_name="reranker_large_k20",
        embedding_model="bge-m3",
        chunk_strategy="D1_overlap100_merge",
        reranker="bge-reranker-large",
        llm="exaone3.5:7.8b",
    )
    for k, v in all_result.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("[4] save_results() 테스트")
    print("=" * 60)
    results = []
    for i in range(3):
        r = evaluate_all(
            golden_doc_id="D001",
            golden_answer="테스트 정답입니다.",
            retrieved_doc_ids=["D001", "D002"],
            retrieved_chunks=["테스트 청크입니다."],
            question="테스트 질문입니다.",
            answer="테스트 답변입니다.",
            question_type="단일문서_사실추출",
            use_embedding=False,
            experiment_name="test_run",
        )
        r["id"] = f"Q00{i+1}"
        results.append(r)

    save_results(results, "/tmp/test_eval_results_v2.csv")
    df = pd.read_csv("/tmp/test_eval_results_v2.csv")
    print(df.to_string(index=False))
