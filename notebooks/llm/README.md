# notebooks/llm/

## 역할
LLM 후보 조사, 요약/QA 프롬프트 설계 및 실험 노트북을 보관합니다.

## 담당
지우님

## 현재 작업
- LLM 후보 조사
- 요약/QA 프롬프트 초안 작성

## 산출물 연계
- 입력: `notebooks/retrieval/`(희원님)의 Retrieval Pipeline 초안 결과(context)
- 출력: Prompt Template v1 → 검증 후 `src/rag_core/prompts/templates/`, `src/rag_core/llm/`로 이전
- 프롬프트 평가 결과는 `notebooks/eval/`(PM)의 평가 기준 수립에 입력값이 됩니다.

## 코딩 에이전트 참고
- 프롬프트 템플릿 문자열은 코드에 하드코딩하지 말고 별도 `.txt`/`.jinja` 파일로 분리해 실험합니다. 프로덕션 이전 시 `src/rag_core/prompts/templates/`로 그대로 옮길 수 있도록 설계하세요.
- LLM 클라이언트 호출 코드(API 키, 엔드포인트)는 노트북에 평문으로 남기지 말고 환경 변수를 사용하세요.
- Retrieval/임베딩 로직을 여기에 작성하지 마세요 (`notebooks/retrieval/` 담당 영역).
