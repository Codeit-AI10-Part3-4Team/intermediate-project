# tests/

## 역할
`src/` 코드에 대한 단위/통합 테스트를 보관합니다.

## 명명 규칙
- 테스트 파일은 `test_<대상모듈>.py` 형식으로 작성하고, `src/`의 디렉토리 구조를 그대로 따라갑니다.
  - 예: `src/rag_core/parsing/pdf_parser.py` → `tests/rag_core/parsing/test_pdf_parser.py`

## 현재 우선순위
- `rag_core`의 각 단계(parsing, chunking, embedding, retrieval, prompts, llm)는 **API 서버 없이 단독으로 테스트 가능**해야 합니다. `src/README.md`의 의존성 규칙(`rag_core`가 `api`를 import하지 않음)이 지켜지는지 테스트 작성 시 함께 확인하세요.
- `test_api.py`는 FastAPI의 `TestClient`를 사용해 업로드 API의 요청/응답 형식을 검증합니다.

## 코딩 에이전트 참고
- 외부 LLM API 호출이 포함된 테스트는 실제 호출 대신 mock을 사용하세요. 비용 발생 및 비결정적 응답을 피하기 위함입니다.
- 골든 데이터셋(`eval/golden_dataset/`)을 이용한 평가는 이 폴더의 단위 테스트와는 별개로 `eval/metrics.py`에서 수행합니다. 혼용하지 마세요.
