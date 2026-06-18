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
├── schemas/             # Pydantic 요청/응답 모델
└── dependencies.py      # 공통 의존성 (인증, DB 세션 등)
```

## 산출물 연계
- `rag_core/` 패키지의 함수를 호출해 실제 파싱/Retrieval/LLM 응답을 생성합니다.
- 업로드된 문서는 `data/`에 저장하거나 GCP 저장소 경로로 전달합니다(파일 직접 커밋 금지).

## 코딩 에이전트 참고
- 비즈니스 로직(파싱, 청킹, Retrieval, 프롬프트 구성, LLM 호출)을 라우터 함수 안에 직접 작성하지 마세요. 반드시 `rag_core`의 함수를 호출하는 방식으로 작성합니다.
- 라우터는 가능한 한 thin하게: 요청 검증 → `rag_core` 함수 호출 → 응답 변환의 흐름만 가집니다.
- 코딩 스타일은 MS '일반적인 C# 코드 규칙'이 아닌 PEP8 + 실무 관행을 따릅니다(이 프로젝트는 Python).
