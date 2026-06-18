# notebooks/retrieval/

## 역할
청킹 전략, 임베딩 모델 후보, Baseline Retrieval 실험 노트북을 보관합니다.

## 담당
희원님

## 현재 작업
- 청킹 초안 구현
- 임베딩 모델 후보 조사
- Baseline Retrieval 구현

## 산출물 연계
- 입력: `notebooks/parsing/`(유빈님)의 문서 구조 분석 및 청킹 후보 조사 결과
- 출력: Retrieval Pipeline 초안 → 검증 후 `src/rag_core/chunking/`, `src/rag_core/embedding/`, `src/rag_core/retrieval/`로 분리 이전
- 임베딩 결과는 `notebooks/llm/`(지우님)의 QA 프롬프트 실험에서 context로 사용됩니다.

## 코딩 에이전트 참고
- 청킹·임베딩·Retrieval 세 단계를 한 노트북에서 실험하더라도, 프로덕션 코드로 옮길 때는 반드시 `src/rag_core/chunking/`, `src/rag_core/embedding/`, `src/rag_core/retrieval/` 세 모듈로 분리합니다.
- 임베딩 모델 비교 실험 결과(속도/정확도)는 노트북 마크다운 셀에 표로 기록해 의사결정 근거를 남기세요.
- LLM 호출 로직을 여기에 작성하지 마세요 (`notebooks/llm/` 담당 영역).
