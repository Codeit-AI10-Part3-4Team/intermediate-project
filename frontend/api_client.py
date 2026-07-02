# frontend/api_client.py
# HTTP client for the FastAPI backend. The frontend talks to the API over HTTP
# only and never imports api/rag_core packages, so backend mock/real swaps
# (use_mock) require no frontend change.

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 60.0


class ApiClientError(Exception):
    """API call failure with a display-ready message for the UI."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RagApiClient:
    """Thin wrapper over POST /rag and POST /upload.

    Config via env vars (no hardcoded endpoints):
    - RAG_API_BASE_URL (default: http://127.0.0.1:8000)
    - RAG_API_TIMEOUT_SECONDS (default: 60)
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,  # test seam (httpx.MockTransport)
    ) -> None:
        resolved = base_url or os.environ.get("RAG_API_BASE_URL", DEFAULT_BASE_URL)
        self.base_url = resolved.rstrip("/")
        if timeout_seconds is None:
            timeout_seconds = float(
                os.environ.get("RAG_API_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
            )
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def query_rag(self, query: str, top_k: int) -> dict[str, Any]:
        """POST /rag -> RagResponse dict (answer, sources, usage)."""
        return self._post("/rag", json={"query": query, "top_k": top_k})

    def check_upload(self, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        """POST /upload (multipart) -> SuitabilityResult dict."""
        return self._post("/upload", files={"file": (filename, content, content_type)})

    def _post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(path, json=json, files=files)
        except httpx.ConnectError as e:
            raise ApiClientError(
                f"API 서버({self.base_url})에 연결할 수 없습니다. 서버 실행 여부를 확인하세요."
            ) from e
        except httpx.TimeoutException as e:
            raise ApiClientError(
                f"응답 대기 시간({self.timeout_seconds:.0f}초)을 초과했습니다. 잠시 후 다시 시도하세요."
            ) from e
        except httpx.HTTPError as e:
            raise ApiClientError(f"요청 처리 중 오류가 발생했습니다: {e}") from e

        if not response.is_success:
            raise ApiClientError(_error_message(response), status_code=response.status_code)

        try:
            data = response.json()
        except ValueError as e:
            raise ApiClientError("API 응답을 해석할 수 없습니다 (JSON 아님).") from e
        if not isinstance(data, dict):
            raise ApiClientError("API 응답 형식이 올바르지 않습니다 (객체가 아님).")
        return data


def _error_message(response: httpx.Response) -> str:
    """Map FastAPI error bodies ({"detail": str | list}) to a user-facing message."""
    status = response.status_code
    detail: Any = None
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("detail")
    except ValueError:
        pass

    if isinstance(detail, str) and detail:
        return f"요청이 거부되었습니다 (HTTP {status}): {detail}"

    if isinstance(detail, list) and detail:
        # 422 validation errors: [{"loc": [...], "msg": "...", ...}, ...]
        messages: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(part) for part in item.get("loc", []) if part != "body")
                msg = str(item.get("msg", ""))
                messages.append(f"{loc}: {msg}" if loc else msg)
        if messages:
            return f"입력값 검증에 실패했습니다 (HTTP {status}): " + "; ".join(messages)

    if status >= 500:
        return f"서버 내부 오류가 발생했습니다 (HTTP {status}). 관리자에게 문의하세요."
    return f"요청이 실패했습니다 (HTTP {status})."
