# tests/frontend/test_app.py
# frontend/app.py 스모크 테스트 — AppTest로 화면 전환·질의 흐름을 네트워크 없이
# 검증한다 (RagApiClient는 views 모듈 네임스페이스에서 monkeypatch).
# (import 경로는 pyproject [tool.pytest.ini_options] pythonpath=["frontend"] 기준)
#
# CI는 [frontend] extra(streamlit)를 설치하지 않으므로(경량 CI 관례),
# streamlit이 없으면 모듈 전체를 skip한다 — 데이터 의존 테스트의 skipif와 동일 취지.

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit", reason="frontend extra 미설치 (pip install -e '.[frontend]')")

from streamlit.testing.v1 import AppTest  # noqa: E402

import views.chat  # noqa: E402

APP_PATH = str(Path(__file__).parents[2] / "frontend" / "app.py")


class _FakeRagApiClient:
    """query_rag만 흉내 내는 대역 — 성공 응답 고정."""

    base_url = "http://testserver"

    def query_rag(self, query: str, top_k: int) -> dict[str, Any]:
        assert query
        assert 1 <= top_k <= 50
        return {
            "answer": "테스트 답변\n- 첫 항목\n- 둘째 항목",
            "sources": [{"chunk": {"chunk_id": "c1", "text": "본문"}, "score": 0.9}],
            # 실 백엔드처럼 usage에 내부 메타데이터가 섞여 오는 경우
            "usage": {
                "thread_id": "",
                "question_type": "single_doc_fact",
                "related_questions": "1. 후속 질문?\\n2. 다른 질문?",
                "style_prompt": "(UI 미지원 — 표시되면 안 됨)",
            },
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
    assert at.session_state["pending_query"] is None  # answered across reruns
    assert at.session_state["pending_dispatched"] is False  # two-phase flow settled
    messages = at.session_state["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"].startswith("테스트 답변")
    assert messages[1]["sources"][0]["chunk"]["chunk_id"] == "c1"
    # 내부 메타데이터(usage 원본)가 그대로 화면에 덤프되지 않아야 한다
    rendered = " ".join(m.value for m in at.markdown)
    assert "style_prompt" not in rendered
    assert "thread_id" not in rendered


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


def test_format_answer_preserves_line_breaks() -> None:
    from views.chat import _format_answer

    # 실제 개행은 마크다운 하드 브레이크로
    assert _format_answer("가\n나") == "가  \n나"
    # 백엔드가 literal "\n"(백슬래시+n)을 보내는 경우도 동일 처리
    assert _format_answer("가\\n나") == "가  \n나"


def test_parse_related_questions_strips_numbering() -> None:
    from views.chat import _parse_related_questions

    assert _parse_related_questions("1. 첫 질문?\\n2) 둘째 질문?\n\n셋째") == [
        "첫 질문?",
        "둘째 질문?",
        "셋째",
    ]
    assert _parse_related_questions("   ") == []


def test_related_question_button_submits_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views.chat, "RagApiClient", _FakeRagApiClient)

    at = _boot()
    at.chat_input[0].set_value("첫 질문").run()

    # 답변(usage.related_questions)에서 만들어진 제안 버튼 클릭 → 재질의
    button = at.button(key="related_q_1_0")
    assert button.label == "후속 질문?"
    button.click().run()

    assert not at.exception
    messages = at.session_state["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[2]["content"] == "후속 질문?"  # numbering 제거된 본문으로 질의
    assert at.session_state["pending_query"] is None
