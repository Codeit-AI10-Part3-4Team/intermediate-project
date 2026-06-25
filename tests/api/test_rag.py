# tests/api/test_rag.py
"""POST /rag 엔드포인트 단위 테스트 (목업 Orchestrator 기준).

목적:
- 라우터 ↔ 스키마(RagRequest/RagResponse) ↔ 의존성 주입 배선이 동작하는지 검증.
- 실제 LLM/검색은 호출하지 않는다 (use_mock=True 경로의 MockOrchestrator 사용).
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    # with 블록이어야 lifespan이 실행되어 app.state.orchestrator가 채워진다.
    with TestClient(app) as c:
        yield c


def test_rag_returns_200_and_response_shape(client):
    resp = client.post("/rag", json={"query": "RFP 핵심 요구사항은?", "top_k": 2})

    assert resp.status_code == 200
    body = resp.json()
    # RagResponse 스키마 키 검증
    assert set(body.keys()) == {"answer", "sources", "usage"}
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["sources"], list)


def test_rag_source_shape_and_score(client):
    resp = client.post("/rag", json={"query": "q", "top_k": 1})

    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert len(sources) == 1
    src = sources[0]
    assert set(src.keys()) == {"chunk", "score"}
    assert 0.0 <= src["score"] <= 1.0
    # 중첩된 Chunk 스키마 검증
    assert set(src["chunk"].keys()) == {"chunk_id", "doc_id", "text", "metadata"}


def test_rag_top_k_is_respected(client):
    # MockOrchestrator는 sources를 top_k로 슬라이싱한다.
    resp = client.post("/rag", json={"query": "q", "top_k": 0 + 1})
    assert len(resp.json()["sources"]) <= 1


def test_rag_top_k_defaults_when_omitted(client):
    # top_k 미지정 시 스키마 기본값(5)이 적용되어 검증 오류 없이 통과해야 한다.
    resp = client.post("/rag", json={"query": "기본값 테스트"})
    assert resp.status_code == 200


@pytest.mark.parametrize("bad_top_k", [0, 51, 999, -3])
def test_rag_rejects_out_of_range_top_k(client, bad_top_k):
    # schemas.RagRequest: top_k 는 1..50 (ge=1, le=50)
    resp = client.post("/rag", json={"query": "q", "top_k": bad_top_k})
    assert resp.status_code == 422


def test_rag_requires_query(client):
    # query 필수 누락 → 422
    resp = client.post("/rag", json={"top_k": 3})
    assert resp.status_code == 422


def test_openapi_exposes_rag_path():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    assert "/rag" in schema["paths"]
    assert "post" in schema["paths"]["/rag"]
