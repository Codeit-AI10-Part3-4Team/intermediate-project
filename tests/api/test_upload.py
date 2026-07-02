# tests/api/test_upload.py
"""POST /upload (RFP 적합성 검사) 단위 테스트 — 목업 SuitabilityChecker 기준.

목적:
- 라우터 검증(형식/크기/빈 파일) ↔ transient 처리 ↔ 의존성 주입 배선 검증.
- 실제 파싱/LLM은 호출하지 않는다 (use_mock=True 경로의 MockSuitabilityChecker).
"""

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_suitability_checker
from api.main import app
from rag_core.parsing import ParsingError, UnsupportedFormatError


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _pdf(content: bytes = b"%PDF-1.4 fake"):
    return {"file": ("doc.pdf", content, "application/pdf")}


def test_upload_returns_200_and_result_shape(client):
    resp = client.post("/upload", files=_pdf())

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"is_suitable", "score", "reasons", "sources", "usage"}
    assert isinstance(body["is_suitable"], bool)
    assert 0.0 <= body["score"] <= 1.0
    assert isinstance(body["reasons"], list)


def test_upload_rejects_unsupported_extension(client):
    resp = client.post("/upload", files={"file": ("note.txt", b"hello", "text/plain")})
    assert resp.status_code == 415


def test_upload_rejects_empty_file(client):
    resp = client.post("/upload", files=_pdf(content=b""))
    assert resp.status_code == 422


def test_upload_rejects_oversized_file(client, monkeypatch):
    # 임계치를 낮춰 대용량 업로드 없이 413 경로를 검증.
    from api.routers import upload as upload_router

    monkeypatch.setattr(upload_router, "MAX_UPLOAD_BYTES", 4)
    resp = client.post("/upload", files=_pdf(content=b"123456789"))
    assert resp.status_code == 413


@pytest.mark.parametrize(
    "exc, expected",
    [(UnsupportedFormatError("bad fmt"), 415), (ParsingError("corrupt"), 422)],
)
def test_upload_maps_parsing_errors_to_http(client, exc, expected):
    # checker가 도메인 파싱 예외를 던지면 라우터가 HTTP 에러로 변환해야 한다.
    class _RaisingChecker:
        def check(self, file_path: str):
            raise exc

    app.dependency_overrides[get_suitability_checker] = lambda: _RaisingChecker()
    try:
        resp = client.post("/upload", files=_pdf())
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == expected


def test_openapi_exposes_upload_path():
    with TestClient(app) as c:
        schema = c.get("/openapi.json").json()
    assert "/upload" in schema["paths"]
    assert "post" in schema["paths"]["/upload"]
