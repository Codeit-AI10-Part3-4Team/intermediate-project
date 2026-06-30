# 평가 기준 (Evaluation Criteria)

RFP RAG 파이프라인의 품질을 측정하기 위한 평가 지표와 기준을 정의합니다.
평가는 `golden_dataset/golden_dataset_v2.csv`(123개 QA)를 기준으로 진행하며,
`metrics.py`의 순수 함수들로 점수를 계산합니다.

---

## 1. Retrieval 평가

검색 결과가 정답 문서를 얼마나 잘 찾아내는지 측정합니다.

| 지표 | 정의 | 계산 방식 |
|---|---|---|
| `retrieval_accuracy` | 정답 doc_id가 retrieved 리스트에 포함되는지 여부 | 포함 시 1.0, 아니면 0.0 |
| `context_recall` | 정답 텍스트의 핵심 키워드가 retrieved context에 얼마나 포함되는지 | 매칭된 키워드 수 / 전체 키워드 수 |
| `context_precision` | retrieved chunks 중 정답과 관련된 청크의 비율 | 키워드 2개 이상 또는 30% 이상 포함 시 relevant로 판정 |
| `mrr` | 정답 문서가 검색 결과 몇 번째 순위에 있는지 (Mean Reciprocal Rank) | 1 / rank (정답이 없으면 0.0) |

### doc_id 매핑 기준

골든 데이터셋의 `doc_id`(예: `고려대학교_차세대포털`)는 ChromaDB의 `doc_id`(예: `D008`)와 형식이 다릅니다.
`run_eval.py`의 `GS_TO_DOCID` 딕셔너리로 매핑하여 비교합니다. 다음 항목은 평가에서 제외합니다.

- `TEST`, `unknown` 등 테스트용 더미 데이터
- `모른다_테스트1~6` 등 가드레일 검증용 질문 (정답 문서가 없는 것이 의도된 케이스)
- `존재하지않는사업`, `입찰마감_확인` 등 범위 밖 질문

다중 문서 비교 질문(`고려대_vs_광주과기원` 등)은 정답 doc_id가 여러 개이며,
`metrics.py`는 단일 `golden_doc_id` 기준으로 동작하므로 target 리스트 중 하나로 정규화하여 평가합니다.

---

## 2. Generation 평가

### 2-1. 임베딩 유사도 기반 지표

| 지표 | 정의 | 비고 |
|---|---|---|
| `semantic_faithfulness` | 답변(answer)과 retrieved context의 임베딩 유사도 (bge-m3, 코사인 유사도) | 논문의 Faithfulness(답변이 context에 없는 내용을 말했는가)와는 다른 개념입니다. 향후 LLM Judge 방식으로 교체 예정입니다. |
| `answer_relevance` | 질문(question)과 답변(answer)의 임베딩 유사도 (bge-m3, 코사인 유사도) | 향후 LLM Judge 방식으로 교체 예정입니다. |

### 2-2. Rule-based 품질 점검 (지우님 Generation v5 파이프라인 기준)

LLM-as-judge는 비용과 시간 제약으로 본 프로젝트에서는 사용하지 않고,
다음 rule-based 지표로 Generation 품질을 점검합니다.

| 지표 | 정의 | 목표값 |
|---|---|---|
| `is_empty` | 빈 답변 여부 | 0건 |
| `has_foreign_lang` | 일본어/중국어 등 외국어 혼입 여부 (영어 약어는 허용) | 0건 |
| `has_money_risk` | "약 X억" 등 추정 금액 표현 포함 여부 | 0건 |
| `is_too_short` | 답변이 10자 미만으로 너무 짧은지 여부 | false positive 가능 (예산 질문의 정상적으로 짧은 답변) |
| `single_doc_many_docs` | 단일문서 질문인데 여러 문서가 검색된 경우 | 0건 |

### 2-3. 응답 시간

| 지표 | 정의 |
|---|---|
| `response_time_ms` / `response_time_sec` | Retrieval+Generation 전체 응답 시간 |

---

## 3. 실험 메타정보

`evaluate_all()` 호출 시 다음 메타정보를 함께 기록하여, 하나의 CSV로 여러 실험을 비교할 수 있도록 합니다.

| 필드 | 설명 |
|---|---|
| `experiment_name` | 실험 식별자 (예: `baseline`, `hybrid_rrf_morpheme`) |
| `embedding_model` | 사용한 임베딩 모델 (기본값: `bge-m3`) |
| `chunk_strategy` | 청킹 전략 (기본값: `D1_overlap100_merge`) |
| `reranker` | 사용한 Reranker (Hybrid 단독 채택 이후 기본값: `none`) |
| `llm` | 사용한 LLM (기본값: `exaone3.5:7.8b`) |
| `timestamp` | 평가 실행 시각 |

---

## 4. 현재 확정 베이스라인

| 항목 | 확정값 |
|---|---|
| 임베딩 모델 | bge-m3 |
| 청크 사이즈 | 500 |
| Prefix 전략 | A_short (사업명 + 발주기관) |
| 청킹 전략 | overlap=100 + 표/텍스트 병합 (needs_subsplit 포함) |
| Retrieval 전략 | Hybrid RRF (벡터 + BM25, kiwipiepy 형태소 분석, rrf_k=60) |
| Reranker | 미사용 (Hybrid 단독 채택, Reranker 조합 시 성능 하락 확인) |
| Vector DB | ChromaDB (vector_db_v4) |
| Generation 모델 | exaone3.5:7.8b (Ollama, 실패 시 OpenAI fallback) |

### 알려진 제약 사항

- 현재 `vector_db_v4`는 `chunker.py`의 `needs_subsplit` 로직 반영 이전(11,435개 청크)으로 구축되어 있습니다.
  새 로직 기준 청크 수는 16,190개로 확인되었으며(희원님 실험 환경), 재생성 시 Recall/MRR이 다소 상승할 것으로 예상됩니다(MRR 0.1943 → 0.2426 수준).
- `context_recall`/`context_precision`은 공백 기준 키워드 매칭을 사용합니다. 형태소 분석기(kiwipiepy) 기반으로 개선 예정입니다(Sprint 3).
- `semantic_faithfulness`, `answer_relevance`는 임베딩 유사도 방식이며, LLM Judge 방식으로 교체 예정입니다(Sprint 3).

---

## 5. 평가 실행 방법

```bash
cd intermediate-project
source .venv/bin/activate
python3 eval/run_eval.py
```

결과는 `eval/eval_results_retrieval_*.csv`에 저장되며, `id`, 실험 메타정보, Retrieval/Generation 지표 컬럼을 포함합니다.
