# tests/api/test_middleware.py
"""요청 ID 미들웨어 테스트.

- 모든 응답에 X-Request-ID 헤더가 붙는다.
- 클라이언트가 보낸 X-Request-ID는 그대로 유지된다 (프론트엔드 ↔ 로그 대조용).
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.middleware import REQUEST_ID_HEADER


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_response_has_request_id_header(client):
    resp = client.post("/rag", json={"query": "q", "top_k": 1})

    assert resp.status_code == 200
    assert resp.headers.get(REQUEST_ID_HEADER)


def test_incoming_request_id_is_preserved(client):
    resp = client.post(
        "/rag",
        json={"query": "q", "top_k": 1},
        headers={REQUEST_ID_HEADER: "test-id-123"},
    )

    assert resp.headers[REQUEST_ID_HEADER] == "test-id-123"


def test_each_request_gets_distinct_id(client):
    id_a = client.get("/openapi.json").headers[REQUEST_ID_HEADER]
    id_b = client.get("/openapi.json").headers[REQUEST_ID_HEADER]

    assert id_a != id_b
