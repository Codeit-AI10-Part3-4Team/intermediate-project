# frontend/views/chat.py
# Second screen (spec v2): message history + bottom-pinned input. While a query
# is pending, the input renders disabled and a centered spinner shows; the
# blocking API call runs after both are on screen (progressive rendering),
# then a rerun appends the answer. Each /rag call is independent — the visible
# history is display-only (the backend has no conversation memory yet).
#
# ⚠️ The pending flow is DELIBERATELY synchronous (blocking call at the end of
# the main run). Two previous designs crashed Streamlit 1.58 on the VM with a
# SIGSEGV core dump on every question: @st.fragment(run_every=...) polling
# (with or without a worker thread) and the components.v1 scroll iframe.
# Do not reintroduce fragments/threads here without soak-testing on the
# deploy target. Stale leftovers of the previous screen during the blocking
# run are hidden by PENDING_CSS instead.

import re
from typing import Any

import streamlit as st

from api_client import ApiClientError, RagApiClient
from styles import CHAT_CSS, PENDING_CSS
from ui import render_header, render_sources


def render() -> None:
    st.html(CHAT_CSS)
    pending = st.session_state.pending_query
    if pending:
        # This run will block on the LLM below; without this, the previous
        # run's widgets (home screen) stay on screen dimmed the whole wait.
        st.html(PENDING_CSS)
    render_header(show_back=True)

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

    # Top-level call keeps the input pinned to the bottom of the page.
    prompt = st.chat_input(
        "궁금한 것을 물어보세요", key="chat_screen_input", disabled=pending is not None
    )
    if prompt and prompt.strip() and pending is None:
        _submit_query(prompt.strip())

    if pending:
        # Last statement of the run: the whole chat screen (spinner, disabled
        # input) is already painted before this blocks.
        _answer_pending_query(pending)


def _answer_pending_query(pending: str) -> None:
    """Blocking POST /rag; appends the assistant message (or error) and reruns."""
    try:
        result = RagApiClient().query_rag(query=pending, top_k=st.session_state.top_k)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result.get("answer") or "_(빈 답변)_",
                "sources": result.get("sources") or [],
                "usage": result.get("usage") or {},
            }
        )
    except ApiClientError as e:
        st.session_state.messages.append(
            {"role": "assistant", "content": e.message, "is_error": True}
        )
    st.session_state.pending_query = None
    st.rerun()


def _submit_query(query: str) -> None:
    """Append the user message and rerun into the pending (blocking) flow."""
    st.session_state.messages.append({"role": "user", "content": query})
    st.session_state.pending_query = query
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


# NOTE: spec 2-⑥'s "scroll the user bubble to the top" iframe hack
# (st.components.v1.html) was removed — the agreed fallback. On the VM
# (Streamlit 1.58 + service PYTHONPATH mixing another venv's protobuf) the
# custom-component serialization crashed the whole process on every question,
# resetting all sessions to the home screen. Do not reintroduce
# streamlit.components.v1 here without verifying it on the deploy target.
