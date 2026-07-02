# tests/frontend/test_api_client.py
# frontend/api_client.py 단위 테스트 — httpx.MockTransport로 네트워크 없이
# 성공 경로와 에러 → 사용자 메시지 매핑을 검증한다.
# (import 경로는 pyproject [tool.pytest.ini_options] pythonpath=["frontend"] 기준)

import json
from collections.abc import Callable

import httpx
import pytest

from api_client import ApiClientError, RagApiClient


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> RagApiClient:
    return RagApiClient(
        base_url="http://testserver",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )


def test_query_rag_success() -> None:
    payload = {"answer": "테스트 답변", "sources": [], "usage": {"total_tokens": 10}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rag"
        body = json.loads(request.content)
        assert body == {"query": "질문", "top_k": 3}
        return httpx.Response(200, json=payload)

    result = _make_client(handler).query_rag(query="질문", top_k=3)
    assert result == payload


def test_check_upload_sends_multipart() -> None:
    payload = {"is_suitable": True, "score": 0.9, "reasons": [], "sources": [], "usage": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/upload"
        assert request.headers["content-type"].startswith("multipart/form-data")
        assert b"sample.pdf" in request.content
        return httpx.Response(200, json=payload)

    result = _make_client(handler).check_upload(
        filename="sample.pdf", content=b"%PDF-1.4", content_type="application/pdf"
    )
    assert result["is_suitable"] is True


def test_connect_error_maps_to_user_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ApiClientError) as exc_info:
        _make_client(handler).query_rag(query="q", top_k=1)
    assert "연결할 수 없습니다" in exc_info.value.message
    assert exc_info.value.status_code is None


def test_timeout_maps_to_user_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(ApiClientError) as exc_info:
        _make_client(handler).query_rag(query="q", top_k=1)
    assert "초과" in exc_info.value.message


def test_http_error_with_string_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(415, json={"detail": "지원하지 않는 형식: .txt (지원: hwp, pdf)"})

    with pytest.raises(ApiClientError) as exc_info:
        _make_client(handler).check_upload(
            filename="a.txt", content=b"x", content_type="text/plain"
        )
    assert exc_info.value.status_code == 415
    assert "지원하지 않는 형식" in exc_info.value.message


def test_http_422_validation_detail_list() -> None:
    detail = [{"loc": ["body", "top_k"], "msg": "Input should be less than or equal to 50"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": detail})

    with pytest.raises(ApiClientError) as exc_info:
        _make_client(handler).query_rag(query="q", top_k=99)
    assert exc_info.value.status_code == 422
    assert "top_k" in exc_info.value.message


def test_server_error_with_non_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    with pytest.raises(ApiClientError) as exc_info:
        _make_client(handler).query_rag(query="q", top_k=1)
    assert exc_info.value.status_code == 500
    assert "서버 내부 오류" in exc_info.value.message


def test_success_with_non_dict_json_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "dict"])

    with pytest.raises(ApiClientError):
        _make_client(handler).query_rag(query="q", top_k=1)
