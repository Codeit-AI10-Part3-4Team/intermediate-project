# src/rag_core/llm/

## 역할
`prompts/`에서 구성된 프롬프트로 LLM을 호출하고 응답을 처리하는 모듈입니다.

## 담당
지우님

## 입력/출력
- 입력: `prompts/`가 생성한 최종 프롬프트
- 출력: LLM 응답 텍스트(요약 또는 QA 답변) + 메타데이터(토큰 사용량, 응답 시간 등 필요 시)

## 현재 구현
- `pipeline.py` — Ollama(`exaone3.5:7.8b`) 호출·후처리·가드레일 함수 모음.
  엔드포인트는 `OLLAMA_BASE_URL` 환경 변수(기본 `http://127.0.0.1:11434`).
- 호출 실패는 `rag_core/exceptions.py`의 도메인 예외(`LLMConnectionError`/`LLMTimeoutError`)로
  변환해 던지며, `api/errors.py`가 502/504로 번역합니다.
- Ollama 장애 시 OpenAI(gpt-4o-mini) fallback은 `orchestration/langgraph_router.py`의
  `call_llm_with_fallback`에 있습니다 (`OPENAI_API_KEY` 필요).

## 산출물 연계
- 이 모듈의 출력이 `src/api/routers/upload.py` 등 API 레이어를 통해 최종 사용자에게 반환됩니다.
- "Prompt Template v1"과 함께 이 모듈이 첫 end-to-end 응답 생성 경로를 완성합니다.

## 코딩 에이전트 참고
- LLM 클라이언트(API 키, 엔드포인트, 모델명)는 환경 변수로 주입하고 코드에 하드코딩하지 않습니다.
- LLM 호출 실패(타임아웃, rate limit, 빈 응답)에 대한 예외 처리 및 재시도 로직을 포함합니다.
- 추후 다른 LLM(클라우드 API ↔ on-device GGUF/llama.cpp)으로 교체 가능하도록 호출 인터페이스를 추상화하세요 (예: `LLMClient` 베이스 클래스 + 구현체별 클래스).
- 프롬프트 구성 로직을 여기에 작성하지 마세요 (`prompts/` 담당 영역).
