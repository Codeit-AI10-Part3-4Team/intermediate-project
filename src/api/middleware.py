# src/api/middleware.py
"""요청 ID 부여 + 액세스 로그 미들웨어.

모든 요청에 X-Request-ID를 부여(클라이언트가 보내면 그 값을 존중)하고,
contextvar에 실어 이 요청을 처리하는 동안 찍히는 모든 로그 라인에
같은 ID가 붙게 합니다 (api/logging_config.py의 RequestIdFilter가 주입).
응답 헤더에도 같은 ID를 실어, 사용자가 겪은 오류를 로그에서 역추적할 수 있습니다.
"""

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# 요청 스코프 밖(서버 기동 로그 등)에서는 "-"로 표기된다.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_access_logger = logging.getLogger("api.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        # catch-all 예외 핸들러(ServerErrorMiddleware)는 이 미들웨어 바깥에서 돌아
        # contextvar가 리셋된 뒤라서, request.state로도 ID를 전달한다 (api/errors.py 참고).
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            _access_logger.info(
                "%s %s -> 500 (%.1fms)", request.method, request.url.path, elapsed_ms
            )
            raise
        else:
            elapsed_ms = (time.perf_counter() - start) * 1000
            _access_logger.info(
                "%s %s -> %d (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_var.reset(token)
