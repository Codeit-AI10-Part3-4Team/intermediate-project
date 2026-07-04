# tests/frontend/test_app.py
# frontend/app.py 스모크 테스트 — AppTest로 화면 전환·질의 흐름을 네트워크 없이
# 검증한다 (RagApiClient는 views 모듈 네임스페이스에서 monkeypatch).
# (import 경로는 pyproject [tool.pytest.ini_options] pythonpath=["frontend"] 기준)

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import views.chat

APP_PATH = str(Path(__file__).parents[2] / "frontend" / "app.py")


class _FakeRagApiClient:
    """query_rag만 흉내 내는 대역 — 성공 응답 고정."""

    base_url = "http://testserver"

    def query_rag(self, query: str, top_k: int) -> dict[str, Any]:
        assert query
        assert 1 <= top_k <= 50
        return {
            "answer": "테스트 답변",
            "sources": [{"chunk": {"chunk_id": "c1", "text": "본문"}, "score": 0.9}],
            "usage": {"total_tokens": 10},
        }


def _boot() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.run()
    assert not at.exception
    return at


def test_home_screen_boots() -> None:
    at = _boot()
    assert at.session_state["screen"] == "home"
    assert len(at.chat_input) == 1  # home input only
    assert at.session_state["messages"] == []


def test_query_switches_to_chat_and_appends_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views.chat, "RagApiClient", _FakeRagApiClient)

    at = _boot()
    at.chat_input[0].set_value("수행 기간은?").run()

    assert not at.exception
    assert at.session_state["screen"] == "chat"
    assert at.session_state["pending_query"] is None  # answered within the run
    messages = at.session_state["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "테스트 답변"
    assert messages[1]["sources"][0]["chunk"]["chunk_id"] == "c1"


def test_api_error_becomes_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from api_client import ApiClientError

    class _FailingClient(_FakeRagApiClient):
        def query_rag(self, query: str, top_k: int) -> dict[str, Any]:
            raise ApiClientError("연결 실패")

    monkeypatch.setattr(views.chat, "RagApiClient", _FailingClient)

    at = _boot()
    at.chat_input[0].set_value("질문").run()

    assert not at.exception
    messages = at.session_state["messages"]
    assert messages[1]["is_error"] is True
    assert messages[1]["content"] == "연결 실패"
