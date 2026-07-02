"""
eval/run_eval.py — 골든 데이터셋 v2 전체를 Retriever(Hybrid RRF)로 검색 후 metrics.py로 평가

희원님의 retrieval_model_test.ipynb에서 사용한 GS_TO_DOCID 매핑을 그대로 사용하여
골든 데이터셋의 doc_id(예: "고려대학교_차세대포털")를 ChromaDB의 doc_id(예: "D008")로 변환한다.

Retriever는 Hybrid RRF(벡터+BM25+kiwipiepy) 방식이며, 기존 Chroma DB를 재사용하려면
반드시 load()를 호출해야 한다.

사용법 (프로젝트 루트에서 실행):
    cd ~/intermediate-project
    source .venv/bin/activate
    python3 eval/run_eval.py
"""

import sys
import time
from pathlib import Path

import pandas as pd

# eval/run_eval.py 기준 상대경로로 src, eval 모듈 경로 추가
THIS_DIR = Path(__file__).resolve().parent          # .../intermediate-project/eval
PROJECT_ROOT = THIS_DIR.parent                       # .../intermediate-project
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(THIS_DIR))

from rag_core.retrieval.retriever import Retriever
from metrics import evaluate_retrieval, save_results


GOLDEN_PATH = THIS_DIR / "golden_dataset" / "golden_dataset_v2.csv"
SAVE_PATH = THIS_DIR / "eval_results_retrieval_hybrid_v1.csv"
CHROMA_DIR = "/data/vector_db/vector_db_v4"
TOP_K = 10

# 희원님 retrieval_model_test.ipynb 에서 가져온 매핑 (golden doc_id → 실제 ChromaDB doc_id)
GS_TO_DOCID = {
    "GKL_그룹웨어": "D093",
    "KUSF_체육": "D011",
    "강릉어선안전": "D024",
    "경기_사회서비스": "D087",
    "고려대학교_차세대포털": "D008",
    "광주과기원_RCMS": "D073",
    "광주과학기술원_학사시스템": "D039",
    "구미_육상": "D018",
    "국립중앙의료원_응급": "D069",
    "국민연금공단_이러닝": "D049",
    "국민연금_멀티턴1": "D050",
    "국민연금_멀티턴2": "D050",
    "국민연금_멀티턴3": "D050",
    "국방_대용량": "D010",
    "기초과학연구원_극저온": "D051",
    "나노종합_팹": "D099",
    "대검찰청_홈페이지": "D053",
    "민속박물관_아카이브": "D090",
    "벤처협회_시스템": "D086",
    "보험개발원_실손": "D083",
    "봉화군_재난": "D005",
    "부산관광_ERP": "D037",
    "서민금융_채팅": "D056",
    "서영대_교육": "D045",
    "서울_디지털성범죄": "D068",
    "서울_지도플랫폼": "D040",
    "서울교육청_ISP": "D084",
    "세종_인사": "D088",
    "우즈벡_관개": "D072",
    "울산_버스": "D034",
    "인천_도시계획": "D004",
    "인천_일자리": "D030",
    "인천공항_ERP": "D079",
    "적십자_재해복구": "D095",
    "철도_ISP": "D070",
    "통합정보시스템_충돌": "D016",
    "평택_버스": "D060",
    "해양박물관_자료": "D066",
    # 다중 문서
    "고려대_vs_광주과기원": ["D008", "D039"],
    "버스_다중비교": ["D034", "D060"],
    "재난안전_종합": ["D005", "D007"],
    "철도_vs_인천_ISP": ["D070", "D030"],
    # 평가 제외
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


def main():
    print("[run_eval] 골든 데이터셋 로드 중...")
    df = pd.read_csv(GOLDEN_PATH)
    print(f"[run_eval] 총 {len(df)}개 문항 로드 완료")

    print("[run_eval] Retriever 초기화 중 (bge-m3 로드)...")
    retriever = Retriever(chroma_dir=CHROMA_DIR)
    print("[run_eval] Chroma 로드 + BM25 인덱스 빌드 중 (load())...")
    retriever.load()
    print("[run_eval] Retriever 초기화 완료")

    results = []
    question_ids = []
    skipped = 0

    for idx, row in df.iterrows():
        gs_key = str(row["doc_id"])
        target = GS_TO_DOCID.get(gs_key)

        if target is None:
            skipped += 1
            continue

        target_ids = target if isinstance(target, list) else [target]
        golden_doc_id = target_ids[0]

        golden_answer = str(row["answer"])
        question = str(row["question"])

        start = time.perf_counter()
        retrieved = retriever.retrieve(question, top_k=TOP_K)
        end = time.perf_counter()

        retrieved_doc_ids = [r.chunk.doc_id for r in retrieved]
        retrieved_doc_ids = [
            golden_doc_id if d in target_ids else d for d in retrieved_doc_ids
        ]
        retrieved_chunks = [r.chunk.text for r in retrieved]

        metrics = evaluate_retrieval(
            golden_doc_id=golden_doc_id,
            golden_answer=golden_answer,
            retrieved_doc_ids=retrieved_doc_ids,
            retrieved_chunks=retrieved_chunks,
        )
        metrics["response_time_sec"] = end - start

        results.append(metrics)
        question_ids.append(row["id"])

        if (idx + 1) % 10 == 0:
            print(f"[run_eval] {idx + 1}/{len(df)} 진행 중")

    print(f"[run_eval] 평가 제외: {skipped}개 (target=None)")
    save_results(results, save_path=str(SAVE_PATH), question_ids=question_ids)

    result_df = pd.DataFrame(results)
    print("\n" + "=" * 50)
    print("[run_eval] 전체 평균 결과 (Hybrid RRF, rrf_k=60)")
    print("=" * 50)
    print(f"  평가 문항 수       : {len(result_df)}")
    print(f"  retrieval_accuracy : {result_df['retrieval_accuracy'].mean():.4f}")
    print(f"  context_recall     : {result_df['context_recall'].mean():.4f}")
    print(f"  context_precision  : {result_df['context_precision'].mean():.4f}")
    print(f"  mrr                : {result_df['mrr'].mean():.4f}")
    print(f"  avg_response_time  : {result_df['response_time_sec'].mean():.4f} sec")


if __name__ == "__main__":
    main()
