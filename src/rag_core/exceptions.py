# src/rag_core/exceptions.py
"""rag_core 도메인 예외 계층.

파이프라인 구현은 외부 라이브러리 예외(requests.ConnectionError 등)를 밖으로
흘리지 말고 이 타입들로 변환해 던집니다. api 계층은 이 타입만 보고
HTTP 상태 코드로 번역합니다 (api/errors.py) — "요청 문제 vs 연결 문제"를
호출자가 구분할 수 있게 하는 단일 통로입니다.
"""


class RagCoreError(Exception):
    """rag_core 파이프라인에서 발생한 오류의 공통 베이스."""


class RetrievalError(RagCoreError):
    """검색 단계 실패 (벡터 DB 접근 불가, 인덱스 손상 등)."""


class LLMError(RagCoreError):
    """LLM 호출 단계 실패의 공통 베이스."""


class LLMConnectionError(LLMError):
    """LLM 서버(Ollama 등)에 연결하지 못함 — 서버 미기동·연결 거부."""


class LLMTimeoutError(LLMError):
    """LLM 서버가 제한 시간 안에 응답하지 않음."""
