# tests/

## 역할
`src/` 코드에 대한 단위/통합 테스트를 보관합니다.

## 명명 규칙
- 테스트 파일은 `test_<대상모듈>.py` 형식으로 작성하고, `src/`의 디렉토리 구조를 그대로 따라갑니다.
  - 예: `src/rag_core/parsing/pdf_parser.py` → `tests/rag_core/parsing/test_pdf_parser.py`

## 현재 구성
- `api/` — FastAPI `TestClient` 기반: 라우터(`test_rag`/`test_upload`/`test_docs`), 요청 ID 미들웨어(`test_middleware`), 예외→HTTP 매핑(`test_errors`), Settings(`test_config`)
- `frontend/` — `httpx.MockTransport` 기반 `api_client` 테스트 (실서버 불필요)
- 루트 — `test_parser`·`test_chunker`·`test_parity_check_parsing`(데이터 없으면 skip), `test_import_integrity`(src/ 내부 import가 실재 모듈인지 AST 정적 검증 — 무거운 의존성 불필요)
- **테스트 공백(알려짐)**: retrieval·embedding·llm·prompts·orchestration은 아직 단위 테스트가 없습니다. 추가 시 아래 원칙을 따르세요.

## 원칙
- `rag_core`의 각 단계는 **API 서버 없이 단독으로 테스트 가능**해야 합니다. `src/README.md`의 의존성 규칙(`rag_core`가 `api`를 import하지 않음)이 지켜지는지 테스트 작성 시 함께 확인하세요.

## 코딩 에이전트 참고
- 외부 LLM API 호출이 포함된 테스트는 실제 호출 대신 mock을 사용하세요. 비용 발생 및 비결정적 응답을 피하기 위함입니다.
- 골든 데이터셋(`eval/golden_dataset/`)을 이용한 평가는 이 폴더의 단위 테스트와는 별개로 `eval/metrics.py`에서 수행합니다. 혼용하지 마세요.
