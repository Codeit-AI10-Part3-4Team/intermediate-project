"""
eval/run_eval_full.py — 지우님 GVP Generation 결과(CSV)와 골든 데이터셋을 결합하여
Retrieval + Generation 전체 지표를 metrics.py로 측정한다.

입력:
    rag_golden_v5_hybrid_amountcheck_final.csv — 지우님 GVP 재실행 결과 (123행)
        qid, question_type, question, retrieved_doc_ids, retrieved_files,
        answer, answer_postprocessed, elapsed_sec, error 등
    golden_dataset_v2.csv — 골든 데이터셋 (doc_id, answer 등 정답)

GS_TO_DOCID 매핑으로 골든 데이터셋의 doc_id(예: "고려대학교_차세대포털")를
ChromaDB doc_id(예: "D008")로 변환하여 비교한다.

CSV에는 retrieved_doc_ids(문서 ID)만 있고 청크 텍스트가 없으므로,
semantic_faithfulness/context_recall/context_precision 계산을 위해
Retriever로 동일 질문을 재검색하여 청크 텍스트를 확보한다.
(주의: GVP 실행 시점과 재검색 시점의 DB 상태가 같다는 전제. 재검색 결과는
CSV의 retrieved_doc_ids와 완전히 동일하지 않을 수 있음 — BM25/벡터 검색은
결정적이지만 DB가 그 사이 변경되지 않았어야 함)

사용법:
    cd ~/intermediate-project
    python3 eval/run_eval_full.py
"""

import ast
import sys
import time
from pathlib import Path

import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag_core.retrieval.retriever import Retriever
from metrics import (
    retrieval_accuracy,
    context_recall,
    context_precision,
    mrr,
    semantic_faithfulness,
    answer_relevance,
    is_empty,
    has_foreign_lang,
    has_money_risk,
    is_too_short,
    save_results,
)


GVP_RESULT_PATH = THIS_DIR / "rag_golden_v5_hybrid_amountcheck_final.csv"
GOLDEN_PATH = THIS_DIR / "golden_dataset" / "golden_dataset_v2.csv"
SAVE_PATH = THIS_DIR / "eval_results_full_v2.csv"
CHROMA_DIR = "/data/vector_db/vector_db_v4"
TOP_K = 10

GS_TO_DOCID = {
    "GKL_그룹웨어": "D093", "KUSF_체육": "D011", "강릉어선안전": "D024",
    "경기_사회서비스": "D087", "고려대학교_차세대포털": "D008", "광주과기원_RCMS": "D073",
    "광주과학기술원_학사시스템": "D039", "구미_육상": "D018", "국립중앙의료원_응급": "D069",
    "국민연금공단_이러닝": "D049", "국민연금_멀티턴1": "D050", "국민연금_멀티턴2": "D050",
    "국민연금_멀티턴3": "D050", "국방_대용량": "D010", "기초과학연구원_극저온": "D051",
    "나노종합_팹": "D099", "대검찰청_홈페이지": "D053", "민속박물관_아카이브": "D090",
    "벤처협회_시스템": "D086", "보험개발원_실손": "D083", "봉화군_재난": "D005",
    "부산관광_ERP": "D037", "서민금융_채팅": "D056", "서영대_교육": "D045",
    "서울_디지털성범죄": "D068", "서울_지도플랫폼": "D040", "서울교육청_ISP": "D084",
    "세종_인사": "D088", "우즈벡_관개": "D072", "울산_버스": "D034",
    "인천_도시계획": "D004", "인천_일자리": "D030", "인천공항_ERP": "D079",
    "적십자_재해복구": "D095", "철도_ISP": "D070", "통합정보시스템_충돌": "D016",
    "평택_버스": "D060", "해양박물관_자료": "D066",
    "고려대_vs_광주과기원": ["D008", "D039"], "버스_다중비교": ["D034", "D060"],
    "재난안전_종합": ["D005", "D007"], "철도_vs_인천_ISP": ["D070", "D030"],
    "TEST": None, "unknown": None, "ISP_다중비교": None,
    "교육관련_다중문서": None, "문화_다중비교": None,
    "의료_다중문서": None, "재공고_종합": None,
    "신규_vs_고도화": None, "예산_최소_최대": None,
    "멀티턴_심화1": None, "멀티턴_심화2": None,
    "모른다_테스트1": None, "모른다_테스트2": None,
    "모른다_테스트3": None, "모른다_테스트4": None,
    "모른다_테스트5": None, "모른다_테스트6": None,
    "존재하지않는사업": None, "입찰마감_확인": None,
}


def parse_doc_ids(raw) -> list[str]:
    if pd.isna(raw):
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = ast.literal_eval(raw)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, SyntaxError):
        return []


def main():
    print("[run_eval_full] GVP 결과 + 골든 데이터셋 로드 중...")
    gvp_df = pd.read_csv(GVP_RESULT_PATH)
    golden_df = pd.read_csv(GOLDEN_PATH)
    print(f"[run_eval_full] GVP 결과 {len(gvp_df)}행, 골든 데이터셋 {len(golden_df)}행")

    print("[run_eval_full] Retriever 초기화 중 (재검색으로 청크 텍스트 확보용)...")
    retriever = Retriever(chroma_dir=CHROMA_DIR)
    retriever.load()
    print("[run_eval_full] Retriever 초기화 완료")

    golden_lookup = golden_df.set_index("id").to_dict("index")

    results = []
    question_ids = []
    skipped = 0
    start_time = time.perf_counter()

    for idx, row in gvp_df.iterrows():
        qid = row["qid"]
        golden_row = golden_lookup.get(qid)
        if golden_row is None:
            skipped += 1
            continue

        gs_key = str(golden_row["doc_id"])
        target = GS_TO_DOCID.get(gs_key)
        if target is None:
            skipped += 1
            continue

        target_ids = target if isinstance(target, list) else [target]
        golden_doc_id = target_ids[0]
        golden_answer = str(golden_row.get("answer", ""))

        question = str(row.get("question", ""))
        answer = str(row.get("answer_postprocessed", row.get("answer", "")))

        # CSV에 retrieved_doc_ids만 있고 청크 텍스트가 없으므로 동일 질문으로 재검색
        retrieved = retriever.retrieve(question, top_k=TOP_K)
        retrieved_doc_ids = [r.chunk.doc_id for r in retrieved]
        retrieved_doc_ids = [
            golden_doc_id if d in target_ids else d for d in retrieved_doc_ids
        ]
        retrieved_chunks = [r.chunk.text for r in retrieved]

        metrics = {
            "retrieval_accuracy": retrieval_accuracy(golden_doc_id, retrieved_doc_ids),
            "context_recall": context_recall(golden_answer, retrieved_chunks),
            "context_precision": context_precision(golden_answer, retrieved_chunks),
            "mrr": mrr(golden_doc_id, retrieved_doc_ids),
            "semantic_faithfulness": semantic_faithfulness(answer, retrieved_chunks),
            "answer_relevance": answer_relevance(question, answer),
            "is_empty": is_empty(answer),
            "has_foreign_lang": has_foreign_lang(answer),
            "has_money_risk": has_money_risk(answer),
            "is_too_short": is_too_short(answer),
            "elapsed_sec_generation": row.get("elapsed_sec"),
            "error": row.get("error"),
            "question_type": row.get("question_type"),
        }

        results.append(metrics)
        question_ids.append(qid)

        if (idx + 1) % 20 == 0:
            elapsed = time.perf_counter() - start_time
            print(f"[run_eval_full] {idx + 1}/{len(gvp_df)} 진행 중 ({elapsed:.1f}초 경과)")

    print(f"[run_eval_full] 평가 제외: {skipped}개")
    save_results(results, save_path=str(SAVE_PATH), question_ids=question_ids)

    total_elapsed = time.perf_counter() - start_time
    result_df = pd.DataFrame(results)
    print("\n" + "=" * 50)
    print(f"[run_eval_full] 전체 평균 결과 (총 소요 {total_elapsed:.1f}초)")
    print("=" * 50)
    print(f"  평가 문항 수            : {len(result_df)}")
    print(f"  retrieval_accuracy      : {result_df['retrieval_accuracy'].mean():.4f}")
    print(f"  context_recall          : {result_df['context_recall'].mean():.4f}")
    print(f"  context_precision       : {result_df['context_precision'].mean():.4f}")
    print(f"  mrr                     : {result_df['mrr'].mean():.4f}")
    print(f"  semantic_faithfulness   : {result_df['semantic_faithfulness'].mean():.4f}")
    print(f"  answer_relevance        : {result_df['answer_relevance'].mean():.4f}")
    print(f"  is_empty 건수           : {result_df['is_empty'].sum()}")
    print(f"  has_foreign_lang 건수   : {result_df['has_foreign_lang'].sum()}")
    print(f"  has_money_risk 건수     : {result_df['has_money_risk'].sum()}")
    print(f"  is_too_short 건수       : {result_df['is_too_short'].sum()}")
    print(f"  error 건수              : {result_df['error'].notna().sum()}")
    print(f"  avg_elapsed_sec(생성)   : {result_df['elapsed_sec_generation'].mean():.2f}")


if __name__ == "__main__":
    main()
