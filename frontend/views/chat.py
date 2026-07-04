# frontend/views/chat.py
# Second screen (spec v2): message history + bottom-pinned input. While a query
# is pending, the input renders disabled and a centered spinner shows; the
# blocking API call runs after both are on screen (progressive rendering),
# then a rerun appends the answer. Each /rag call is independent — the visible
# history is display-only (the backend has no conversation memory yet).

import re
import threading
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from api_client import ApiClientError, RagApiClient
from styles import CHAT_CSS
from ui import render_header, render_sources


def render() -> None:
    st.html(CHAT_CSS)
    render_header(show_back=True)

    pending = st.session_state.pending_query
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        for index, message in enumerate(st.session_state.messages):
            with st.chat_message(message["role"]):
                if message.get("is_error"):
                    st.error(message["content"])
                elif message["role"] == "assistant":
                    st.markdown(_format_answer(message["content"]))
                else:
                    st.markdown(message["content"])
                render_sources(message.get("sources") or [])
                _render_related_questions(
                    message.get("usage") or {}, index, disabled=pending is not None
                )
        if pending:
            st.html(
                '<div class="oop-genwrap"><span class="oop-spinner"></span>'
                '<span class="oop-cap">답변 생성 중…</span></div>'
            )
            _scroll_last_user_message_to_top()
            _pending_worker()

    # Top-level call keeps the input pinned to the bottom of the page.
    prompt = st.chat_input(
        "궁금한 것을 물어보세요", key="chat_screen_input", disabled=pending is not None
    )
    if prompt and prompt.strip() and pending is None:
        _submit_query(prompt.strip())


@st.fragment(run_every="0.3s")
def _pending_worker() -> None:
    """Poll the background /rag call and publish the answer when it lands.

    Every tick returns immediately — no script or fragment run ever blocks on
    the LLM. (A blocking call inside a run_every tick collides with the next
    ticks: runs get preempted/aborted for the whole LLM wait, which crashed
    the deployed app and reset sessions back to the home screen.)
    """
    ss = st.session_state
    call = ss.pending_call
    if not ss.pending_query or call is None or not call.get("done"):
        return
    if "error" in call:
        ss.messages.append({"role": "assistant", "content": call["error"], "is_error": True})
    else:
        result = call["result"]
        ss.messages.append(
            {
                "role": "assistant",
                "content": result.get("answer") or "_(빈 답변)_",
                "sources": result.get("sources") or [],
                "usage": result.get("usage") or {},
            }
        )
    ss.pending_query = None
    ss.pending_call = None
    _rerun_app()


def _rerun_app() -> None:
    """Full-app rerun that also works on Streamlit versions without the
    scope kwarg (RerunException is control flow and passes through)."""
    try:
        st.rerun(scope="app")
    except TypeError:
        st.rerun()


def start_pending(query: str) -> None:
    """Append the user message and fire /rag on a daemon thread.

    The thread writes into a plain dict held in session_state ("done" last,
    so the polling side never sees a half-filled result) and must not touch
    any st.* API. Called from the home-submit routing and _submit_query.
    """
    st.session_state.messages.append({"role": "user", "content": query})
    st.session_state.pending_query = query
    call: dict[str, Any] = {}
    st.session_state.pending_call = call
    top_k = st.session_state.top_k

    def work() -> None:
        try:
            call["result"] = RagApiClient().query_rag(query=query, top_k=top_k)
        except ApiClientError as e:
            call["error"] = e.message
        except Exception:  # a worker thread must never die silently
            call["error"] = "답변 생성 중 예기치 못한 오류가 발생했습니다. 다시 시도해 주세요."
        call["done"] = True

    threading.Thread(target=work, daemon=True).start()


def _submit_query(query: str) -> None:
    start_pending(query)
    st.rerun()


def _format_answer(text: str) -> str:
    """Keep LLM line breaks readable in markdown.

    Markdown collapses single newlines, and backend strings sometimes carry
    literal backslash-n sequences — normalize both to hard breaks.
    """
    text = text.replace("\\n", "\n")
    return text.replace("\n", "  \n")


def _render_related_questions(usage: dict[str, Any], message_index: int, disabled: bool) -> None:
    """Follow-up suggestions from the backend as click-to-ask buttons.

    The rest of `usage` (thread_id, question_type, style_prompt, ...) is
    internal metadata the UI cannot act on, so it is not displayed.
    """
    related = usage.get("related_questions")
    if not isinstance(related, str) or not related.strip():
        return
    questions = _parse_related_questions(related)
    if not questions:
        return
    with st.expander("관련 질문 제안"):
        for i, question in enumerate(questions):
            if (
                st.button(question, key=f"related_q_{message_index}_{i}", disabled=disabled)
                and not disabled
            ):
                _submit_query(question)


def _parse_related_questions(raw: str) -> list[str]:
    """'1. 질문?\\n2. 질문?' (literal \\n 포함) -> numbering 제거한 질문 리스트."""
    questions = []
    for line in raw.replace("\\n", "\n").splitlines():
        line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
        if line:
            questions.append(line)
    return questions


def _scroll_last_user_message_to_top() -> None:
    # Spec 2-⑥: scroll the just-sent user bubble to the top. Streamlit has no
    # scroll API; this same-origin iframe hack is the agreed fallback risk —
    # if a Streamlit upgrade breaks it, delete this call (keep-bottom behavior).
    components.html(
        """
        <script>
        const msgs = window.parent.document.querySelectorAll(
            '[data-testid="stChatMessage"]');
        const users = Array.from(msgs).filter((m) =>
            m.querySelector('[data-testid="stChatMessageAvatarUser"]'));
        const last = users[users.length - 1];
        if (last) last.scrollIntoView({behavior: "smooth", block: "start"});
        </script>
        """,
        height=0,
    )
