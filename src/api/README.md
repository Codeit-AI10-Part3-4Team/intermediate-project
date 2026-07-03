# src/api/

## 역할
FastAPI 기반 서버 코드, 라우팅, 업로드 API를 보관합니다.

## 담당
호정님

## 현재 상태
- FastAPI 서버 구축 ✅ — `POST /rag`(질의, `session_id`로 멀티턴·`company_info`로 입찰분석 지원),
  `POST /upload`(적합성 검사 — 라우터·검증·transient 처리 구현, **판정은 아직 Mock**)
- 실제 파이프라인 배선 ✅ — `APP_USE_MOCK=false` 시 lifespan이 `LangGraphOrchestrator`를
  주입 (Chroma 경로는 `Settings.chroma_dir`). 절차는 `deploy/README.md`(러너북) 참고.
- 관측성 ✅ — 요청마다 `X-Request-ID`, 도메인 예외 → 502/504/500 매핑, 파일 로그 옵션
  (아래 "로깅 / 오류 추적" 섹션)
- 남은 것: 실제 `SuitabilityChecker` 구현·배선

## 구조 가이드
```
api/
├── main.py            # FastAPI 앱 엔트리포인트 (lifespan + 미들웨어·핸들러·라우터 등록)
├── lifespan.py         # 시작 시 Settings 읽어 로깅 설정 + 구현체를 app.state에 배선 (use_mock 전환)
├── config.py           # Settings (pydantic-settings, env_prefix=APP_)
├── middleware.py        # 요청마다 X-Request-ID 부여 + 액세스 로그 (api.access)
├── errors.py            # rag_core 도메인 예외 → HTTP 상태 코드 번역 (502/504/500)
├── logging_config.py    # 로깅 설정 (request_id 필터, APP_LOG_FILE 파일 핸들러)
├── mock.py             # Mock 구현 (MockOrchestrator / MockSuitabilityChecker 등)
├── routers/
│   ├── rag.py          # POST /rag  (질의 → Orchestrator.run)
│   └── upload.py        # POST /upload (RFP 적합성 검사 · transient)
├── schemas.py           # HTTP 입출력 전용 DTO (RagRequest) + rag_core 응답 re-export
└── dependencies.py      # app.state 구현체를 Depends로 주입 (타입은 rag_core Protocol)
```

## 로깅 / 오류 추적

**어디서 깨졌는지는 상태 코드가 먼저 말해줍니다** (`errors.py`):

| 상태 | 의미 | 원인 위치 |
| --- | --- | --- |
| 422 | 요청 형식 오류 (FastAPI 기본 검증) | 클라이언트 요청 |
| 502 | LLM 서버 연결 실패 (`LLMConnectionError`) | Ollama 미기동·연결 거부 |
| 504 | LLM 응답 시간 초과 (`LLMTimeoutError`) | Ollama 과부하·모델 지연 |
| 500 | 파이프라인·서버 내부 오류 (`RagCoreError` 등) | 서버 코드 |

**요청 ID로 로그를 꿰어 추적합니다**:

- 모든 응답에 `X-Request-ID` 헤더가 붙고, 오류 응답 본문에도 `request_id`가 들어갑니다.
- 그 요청을 처리하는 동안 찍힌 모든 로그 라인에 같은 ID가 붙습니다:
  `2026-07-03 12:00:00 ERROR [a1b2c3d4e5f6] api.errors: LLM connection failed: ...`
- 클라이언트가 `X-Request-ID`를 보내면 그 값을 그대로 사용합니다(프론트↔백엔드 대조).

**로그 위치**: 기본은 stdout(→ VM에선 journald). `APP_LOG_FILE`을 설정하면 회전 파일로도
남습니다 — VM 서비스는 `/var/log/rfp/api.log` (팀원이 sudo 없이 열람 가능,
`deploy/systemd/rfp-api.service` 참고). 레벨은 `APP_LOG_LEVEL`(기본 INFO).

**규칙**: `rag_core`는 모듈 로거(`logging.getLogger(__name__)`)로 찍기만 하고
핸들러/포맷을 설정하지 않습니다(설정은 `logging_config.py`에서 1회).
파이프라인 구현은 외부 예외를 그대로 흘리지 말고 `rag_core/exceptions.py`의
도메인 예외로 변환해 던지세요 — 예: Ollama 호출부에서 `requests.ConnectionError`
→ `LLMConnectionError`, `requests.Timeout` → `LLMTimeoutError`.
프롬프트/문서 전문은 로그에 남기지 말고 길이·청크 ID만 기록합니다.

## API 문서 (Swagger UI)

- **로컬**: `uvicorn api.main:app --reload` → http://127.0.0.1:8000/docs
- **VM(상시 서비스)**: API는 의도적으로 loopback(127.0.0.1:8090) 전용이라 포트 직접 접근이 안 됩니다.
  JupyterHub 로그인 후 아래 주소로 접근하세요 (`jupyter-server-proxy` 경유, 팀원 계정만 가능):

  ```
  http://136.119.102.164:8000/user/<본인ID>/proxy/8090/docs
  ```

  `<본인ID>`는 JupyterHub 로그인 계정입니다. Try it out으로 `/rag`·`/upload`를 실제 호출해
  Mock 응답을 확인할 수 있습니다.
- 구현 메모: 기본 `/docs`는 절대 경로 `/openapi.json`을 하드코딩해 프록시 프리픽스
  (`/user/<id>/proxy/8090`) 아래에서 스펙 로드가 깨집니다. 그래서 `main.py`가 기본 docs를 끄고
  **상대 경로로 스펙을 참조하는 커스텀 `/docs`**를 제공합니다 (`/redoc`은 비활성).

## 서버 호출 구조 통일 (계약 = contracts)
협업 시 각자 만든 모듈이 서로 맞물리도록, **데이터 모델과 인터페이스(계약)를 한 곳에서 정의**합니다.

- **도메인 모델 / 계약의 단일 원천은 `src/rag_core`** 입니다 (`api`가 아님).
  - `src/rag_core/schemas.py` — `Document`, `Chunk`, `RetrievedChunk`, `RagResponse` (파이프라인이 주고받는 도메인 모델)
  - `src/rag_core/interfaces.py` — `Parser`, `Chunker`, `Embedder`, `Retriever`, `LLMClient`, `Orchestrator`, `SuitabilityChecker` (`typing.Protocol`)
- **`api/schemas.py`에는 HTTP 입출력 전용 DTO만** 둡니다. 현재는 `RagRequest`(질의 입력)뿐이며,
  응답 모델(`RagResponse`, `SuitabilityResult`)은 `rag_core`에서 import해 그대로 재사용합니다 (`from rag_core.schemas import RagResponse`).

> **왜 `rag_core`에 두는가**: `rag_core`는 `api`를 import하지 않는다는 의존 규칙([../README.md](../README.md)) 때문입니다.
> 계약을 `api`에 두면, `Document`를 반환해야 하는 `rag_core` 구현이 `api`를 import하게 되어 방향이 역전됩니다.
> 계약을 도메인 코어(`rag_core`)가 소유하고 어댑터(`api`)가 의존하면 양쪽 모두 허용된 방향만 사용합니다.

### 계약 사용 규칙
- 인터페이스는 `Protocol`(구조적 타이핑)이라 **구현체가 상속할 필요가 없습니다.** 시그니처만 맞추면 됩니다.
  ```python
  # rag_core 안의 PDF 파서 — Parser를 상속하지 않아도 Parser로 인정됨
  class PdfParser:
      def parse(self, file_path: str) -> Document: ...
  ```
- 라우터는 의존성으로 **인터페이스 타입**(`Orchestrator` 등)을 주입받고 구체 구현에 직접 의존하지 마세요.
- 모델 필드를 바꿔야 하면 `api`에서 복제하지 말고 **`rag_core`의 원본을 수정**합니다(단일 원천 유지).

## 산출물 연계
- `rag_core/` 패키지의 함수를 호출해 실제 파싱/Retrieval/LLM 응답을 생성합니다.
- **업로드 문서는 transient입니다**: 적합성 검사용으로 임시 파일로만 받고 응답 시점에 폐기하며, `data/`·DB·코퍼스에 **영속 저장하지 않습니다**(docs/architecture.md §4). 참조 코퍼스는 read-only.

## 코딩 에이전트 참고
- 비즈니스 로직(파싱, 청킹, Retrieval, 프롬프트 구성, LLM 호출)을 라우터 함수 안에 직접 작성하지 마세요. 반드시 `rag_core`의 함수를 호출하는 방식으로 작성합니다.
- 라우터는 가능한 한 thin하게: 요청 검증 → `rag_core` 함수 호출 → 응답 변환의 흐름만 가집니다.
- 코딩 스타일은 MS '일반적인 C# 코드 규칙'이 아닌 PEP8 + 실무 관행을 따릅니다(이 프로젝트는 Python).
