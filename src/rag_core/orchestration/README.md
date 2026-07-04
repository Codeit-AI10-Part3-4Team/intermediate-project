# src/rag_core/orchestration/

## 역할
파이프라인 단계(retrieval → prompts → llm)를 **LangGraph**로 조합하는 Orchestrator입니다.
질문 유형 분류(라우팅) → 검색 → 생성 → 후처리를 그래프로 구성하고, 멀티턴 세션을 지원합니다.

## 담당
PM

## 구성
- `orchestrator.py` — `LangGraphOrchestrator`: `rag_core.interfaces.Orchestrator` 계약 어댑터.
  `run(query, top_k, session_id=None, company_info=None) -> RagResponse`.
  `session_id`가 없으면 요청마다 새 thread(stateless), 있으면 멀티턴 유지.
- `langgraph_router.py` — StateGraph 정의: 키워드 기반 질문 분류, 하이브리드 검색 호출,
  Ollama 호출(실패 시 RuntimeError → api 계층에서 502/504 응답), 후처리.

## 배선
- `use_mock=False`일 때 `api/lifespan.py`가 `LangGraphOrchestrator(chroma_dir=Settings.chroma_dir)`로 주입.
- 의존성: `pip install -e ".[retrieval,orchestration]"` (langgraph는 `[orchestration]` extra).

## 알려진 제약
- `MemorySaver`(인메모리 체크포인터)는 thread별 상태를 프로세스 메모리에 계속 누적합니다 —
  세션 미지정 요청이 많으면 메모리가 자랍니다 (TTL/외부 저장소 검토 항목).
- LLM 호출 경계 외의 노드 오류는 아직 일부가 삼켜져 안내문으로 대체됩니다 —
  도메인 예외(`rag_core/exceptions.py`) 전파로 정리 중.

## 코딩 에이전트 참고
- 이 패키지는 **조합만** 담당합니다. 검색·프롬프트·LLM 로직 자체는 각 단계 패키지에 두세요.
- 노드에서 오류를 삼키지 말고 도메인 예외로 던지세요 — `api`가 502/504/500으로 번역합니다.
