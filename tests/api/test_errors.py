# tests/api/test_errors.py
"""도메인 예외 → HTTP 상태 코드 번역 테스트.

실제 앱 대신 동일한 미들웨어·핸들러를 배선한 테스트 앱을 쓴다
(api.main의 라우터를 건드리지 않고 예외 경로만 검증하기 위해).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import register_exception_handlers
from api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from rag_core.exceptions import LLMConnectionError, LLMTimeoutError, RetrievalError


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/boom/connection")
    async def boom_connection():
        raise LLMConnectionError("ollama refused")

    @app.get("/boom/timeout")
    async def boom_timeout():
        raise LLMTimeoutError("ollama slow")

    @app.get("/boom/retrieval")
    async def boom_retrieval():
        raise RetrievalError("index broken")

    @app.get("/boom/unexpected")
    async def boom_unexpected():
        raise ValueError("bug")

    return app


@pytest.fixture
def client():
    # 500 경로 검증을 위해 서버 예외를 다시 던지지 않게 한다.
    with TestClient(_build_app(), raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/boom/connection", 502),
        ("/boom/timeout", 504),
        ("/boom/retrieval", 500),
        ("/boom/unexpected", 500),
    ],
)
def test_exception_maps_to_status(client, path, expected_status):
    resp = client.get(path, headers={REQUEST_ID_HEADER: "trace-me"})

    assert resp.status_code == expected_status
    body = resp.json()
    assert "detail" in body
    # 오류 응답 본문의 request_id로 로그와 대조할 수 있어야 한다.
    assert body["request_id"] == "trace-me"


def test_validation_error_still_422():
    # FastAPI 기본 검증(요청 문제)은 그대로 422로 남는다 — 실제 앱으로 확인.
    from api.main import app as real_app

    with TestClient(real_app) as c:
        resp = c.post("/rag", json={"top_k": "not-an-int"})
    assert resp.status_code == 422
