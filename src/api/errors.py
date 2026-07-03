# src/api/errors.py
"""rag_core 도메인 예외 → HTTP 상태 코드 번역.

실패 지점을 상태 코드만으로 구분할 수 있게 한다:
- 422: 요청 자체가 잘못됨 (FastAPI 기본 검증 — 여기서 다루지 않음)
- 502: 업스트림(LLM 서버) 연결 실패
- 504: 업스트림 응답 시간 초과
- 500: 그 외 파이프라인/서버 내부 오류

모든 오류 응답 본문에 request_id를 실어 로그와 대조할 수 있게 한다.
"""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from api.middleware import REQUEST_ID_HEADER, request_id_var
from rag_core.exceptions import LLMConnectionError, LLMTimeoutError, RagCoreError

logger = logging.getLogger("api.errors")


def _request_id(request: Request) -> str:
    # catch-all 핸들러는 미들웨어 바깥에서 돌아 contextvar가 이미 리셋됨 → state 우선.
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else request_id_var.get()


def _error_response(request: Request, status_code: int, detail: str) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "request_id": request_id},
        headers={REQUEST_ID_HEADER: request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LLMConnectionError)
    async def handle_llm_connection(request: Request, exc: LLMConnectionError) -> JSONResponse:
        logger.error("LLM connection failed: %s", exc, exc_info=exc)
        return _error_response(
            request, 502, "LLM 서버에 연결할 수 없습니다. 서버 상태를 확인해 주세요."
        )

    @app.exception_handler(LLMTimeoutError)
    async def handle_llm_timeout(request: Request, exc: LLMTimeoutError) -> JSONResponse:
        logger.error("LLM request timed out: %s", exc, exc_info=exc)
        return _error_response(request, 504, "LLM 서버 응답이 제한 시간을 초과했습니다.")

    @app.exception_handler(RagCoreError)
    async def handle_rag_core(request: Request, exc: RagCoreError) -> JSONResponse:
        logger.error("Pipeline error: %s", exc, exc_info=exc)
        return _error_response(request, 500, "요청 처리 중 내부 오류가 발생했습니다.")

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception (request_id=%s): %s", _request_id(request), exc, exc_info=exc
        )
        return _error_response(request, 500, "서버 내부 오류가 발생했습니다.")
