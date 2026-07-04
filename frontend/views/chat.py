# frontend/views/chat.py
# Second screen (spec v2): message history + bottom-pinned input. While a query
# is pending, the input renders disabled and a centered spinner shows; the
# blocking API call runs after both are on screen (progressive rendering),
# then a rerun appends the answer. Each /rag call is independent — the visible
# history is display-only (the backend has no conversation memory yet).

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
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                if message.get("is_error"):
                    st.error(message["content"])
                elif message["role"] == "assistant":
                    st.markdown(_format_answer(message["content"]))
                else:
                    st.markdown(message["content"])
                render_sources(message.get("sources") or [])
                _render_related_questions(message.get("usage") or {})
        if pending:
            st.html(
                '<div class="oop-genwrap"><span class="oop-spinner"></span>'
                '<span class="oop-cap">답변 생성 중…</span></div>'
            )
            _scroll_last_user_message_to_top()

    # Top-level call keeps the input pinned to the bottom of the page.
    prompt = st.chat_input(
        "궁금한 것을 물어보세요", key="chat_screen_input", disabled=pending is not None
    )
    if prompt and prompt.strip() and pending is None:
        st.session_state.messages.append({"role": "user", "content": prompt.strip()})
        st.session_state.pending_query = prompt.strip()
        st.session_state.pending_dispatched = False
        st.rerun()

    if pending:
        if st.session_state.pending_dispatched:
            _answer_pending_query(pending)
        else:
            # Paint the chat screen first and make the blocking call on the
            # next run. A blocking call in the same run as a screen switch
            # keeps the previous screen's widgets on screen as dimmed stale
            # elements for the whole LLM latency.
            st.session_state.pending_dispatched = True
            st.rerun()


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
    st.session_state.pending_dispatched = False
    st.rerun()


def _format_answer(text: str) -> str:
    """Keep LLM line breaks readable in markdown.

    Markdown collapses single newlines, and backend strings sometimes carry
    literal backslash-n sequences — normalize both to hard breaks.
    """
    text = text.replace("\\n", "\n")
    return text.replace("\n", "  \n")


def _render_related_questions(usage: dict[str, Any]) -> None:
    """Show follow-up question suggestions from the backend, if any.

    The rest of `usage` (thread_id, question_type, style_prompt, ...) is
    internal metadata the UI cannot act on, so it is not displayed.
    """
    related = usage.get("related_questions")
    if not isinstance(related, str) or not related.strip():
        return
    with st.expander("관련 질문 제안"):
        st.markdown(_format_answer(related))


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
