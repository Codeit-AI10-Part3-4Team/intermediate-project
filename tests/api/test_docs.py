# tests/api/test_docs.py
"""Swagger UI(/docs)·OpenAPI 스펙 노출 테스트.

목적:
- 커스텀 /docs가 상대 경로("openapi.json")로 스펙을 참조하는지 검증.
  절대 경로("/openapi.json")면 JupyterHub 프록시(/user/<id>/proxy/8090) 뒤에서 깨진다.
- /openapi.json에 라우터 경로들이 실제로 실려 있는지 검증.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_docs_page_returns_200_html(client):
    resp = client.get("/docs")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_docs_page_references_relative_openapi_url(client):
    html = client.get("/docs").text

    # 프록시 프리픽스 아래에서도 스펙을 찾도록 상대 경로여야 한다.
    assert "'openapi.json'" in html
    assert "'/openapi.json'" not in html


def test_docs_page_sends_xsrf_header_for_jupyterhub_proxy(client):
    html = client.get("/docs").text

    # JupyterHub 5는 프록시 경유 POST에 XSRF 토큰을 요구한다 —
    # Swagger 요청 인터셉터가 _xsrf 쿠키를 X-XSRFToken 헤더로 실어야 한다.
    assert "X-XSRFToken" in html
    assert "requestInterceptor" in html


def test_openapi_spec_contains_router_paths(client):
    resp = client.get("/openapi.json")

    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/rag" in paths
    assert "/upload" in paths
    # 커스텀 docs 라우트는 스펙에 노출하지 않는다.
    assert "/docs" not in paths


def test_openapi_declares_relative_server(client):
    spec = client.get("/openapi.json").json()

    # servers가 없으면 Swagger UI가 기본 서버 "/"를 오리진 루트로 해석해
    # Try it out이 프록시 프리픽스를 벗어난다 (호스트 루트로 POST → Hub 403).
    # 상대 서버 "./"는 스펙을 받아온 위치 기준으로 해석된다.
    assert spec.get("servers") == [{"url": "./"}]
