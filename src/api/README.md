# src/api/

## 역할
FastAPI 기반 서버 코드, 라우팅, 업로드 API를 보관합니다.

## 담당
호정님

## 현재 작업
- GitHub 레포/브랜치 전략 수립 (인프라 측면)
- FastAPI 서버 구축
- 업로드 API 구현

## 구조 가이드
```
api/
├── main.py            # FastAPI 앱 엔트리포인트
├── routers/
│   └── upload.py       # 업로드 엔드포인트
├── schemas.py           # HTTP 입출력 전용 DTO (예: RagRequest)
└── dependencies.py      # 공통 의존성 (인증, DB 세션 등)
```

## 서버 호출 구조 통일 (계약 = contracts)
협업 시 각자 만든 모듈이 서로 맞물리도록, **데이터 모델과 인터페이스(계약)를 한 곳에서 정의**합니다.

- **도메인 모델 / 계약의 단일 원천은 `src/rag_core`** 입니다 (`api`가 아님).
  - `src/rag_core/schemas.py` — `Document`, `Chunk`, `RetrievedChunk`, `RagResponse` (파이프라인이 주고받는 도메인 모델)
  - `src/rag_core/interfaces.py` — `Parser`, `Chunker`, `Embedder`, `Retriever`, `LLMClient`, `Orchestrator` (`typing.Protocol`)
- **`api/schemas.py`에는 HTTP 입출력 전용 DTO만** 둡니다. 현재는 `RagRequest`(질의 입력)뿐이며,
  응답 모델 `RagResponse`는 `rag_core`에서 import해 그대로 재사용합니다 (`from rag_core.schemas import RagResponse`).

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
- 업로드된 문서는 `data/`에 저장하거나 GCP 저장소 경로로 전달합니다(파일 직접 커밋 금지).

## 코딩 에이전트 참고
- 비즈니스 로직(파싱, 청킹, Retrieval, 프롬프트 구성, LLM 호출)을 라우터 함수 안에 직접 작성하지 마세요. 반드시 `rag_core`의 함수를 호출하는 방식으로 작성합니다.
- 라우터는 가능한 한 thin하게: 요청 검증 → `rag_core` 함수 호출 → 응답 변환의 흐름만 가집니다.
- 코딩 스타일은 MS '일반적인 C# 코드 규칙'이 아닌 PEP8 + 실무 관행을 따릅니다(이 프로젝트는 Python).
