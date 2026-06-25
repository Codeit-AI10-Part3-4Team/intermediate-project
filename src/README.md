# src/

## 역할
프로덕션 코드(검증이 끝나 재사용 가능한 형태로 정리된 코드)를 보관합니다.
`notebooks/`에서 검증된 로직만 이곳으로 이전됩니다.

## 하위 패키지 및 의존성 방향
```
src/api  ──depends on──>  src/rag_core
```
- `api/` — FastAPI 서버, 업로드 API (담당: 호정님)
- `rag_core/` — 파싱·청킹·임베딩·Retrieval·프롬프트·LLM 호출을 포함한 RAG 파이프라인 코어 로직

**의존성 규칙(중요)**: `rag_core`는 `api`를 import하지 않습니다. `rag_core`는 FastAPI 없이도 단독으로 실행·테스트 가능해야 합니다. 이 방향이 깨지면 RAG 로직 단위 테스트가 서버 기동에 종속되어 버립니다.

## 코딩 에이전트 참고
- 새 코드를 작성할 위치를 정할 때: HTTP 요청/응답, 라우팅, 인증 등 웹 서버 관심사라면 `api/`, 문서 처리·검색·LLM 호출 등 도메인 로직이라면 `rag_core/`.
- `rag_core` 하위 모듈에서 `from api import ...` 형태의 import가 보이면 설계 위반입니다.

> import 규칙: `pip install -e .`(src 레이아웃)로 설치하므로 `src.` 접두어 없이 `import rag_core` / `from api import ...`로 씁니다.
