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


def test_openapi_spec_contains_router_paths(client):
    resp = client.get("/openapi.json")

    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/rag" in paths
    assert "/upload" in paths
    # 커스텀 docs 라우트는 스펙에 노출하지 않는다.
    assert "/docs" not in paths
