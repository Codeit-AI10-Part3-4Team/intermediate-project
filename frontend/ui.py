# frontend/ui.py
# Render helpers shared by both screens (header, source chunks).

import functools
import subprocess
from pathlib import Path
from typing import Any

import streamlit as st

# st.html sanitizes inline <svg> away, so the logo goes through st.image.
_LOGO_PATH = str(Path(__file__).parent / "design" / "logo" / "oop-logo.svg")

GREETING_HTML = (
    '<div class="oop-greeting">ㅇㅇㅍ, RFP의 모든 것.'
    '<span class="oop-greeting-sub">궁금한 것을 물어보세요</span></div>'
)
CHECKING_HTML = (
    '<div class="oop-greeting oop-checking"><span class="oop-spinner"></span>'
    "문서를 검사 중입니다</div>"
)


@functools.cache
def build_rev() -> str:
    """Short git SHA of the running code — lets anyone verify a deploy took
    effect from the UI (⚙ popover) instead of guessing."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=Path(__file__).parent,
            check=False,
        )
        return result.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def render_header(show_back: bool) -> None:
    """Top-left logo; chat screen adds the back arrow next to it (spec 2-⑧)."""
    logo_col, back_col, _ = st.columns([2, 1, 17], vertical_alignment="center")
    with logo_col:
        st.image(_LOGO_PATH, width=76)
    if show_back:
        with back_col:
            if st.button(":material/arrow_back:", help="첫 화면으로", key="back_btn"):
                st.session_state.screen = "home"
                st.session_state.messages = []
                st.session_state.pending_query = None
                st.rerun()


def render_sources(sources: list[dict[str, Any]]) -> None:
    """RetrievedChunk list -> expander cards (answer first, sources after)."""
    if not sources:
        return
    st.markdown(f"**근거 ({len(sources)}건)**")
    for i, source in enumerate(sources, start=1):
        chunk = source.get("chunk") or {}
        score = source.get("score")
        score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "-"
        with st.expander(f"[{i}] {chunk.get('chunk_id') or '(id 없음)'} · score {score_text}"):
            st.write(chunk.get("text") or "_(본문 없음)_")
            metadata = chunk.get("metadata") or {}
            if metadata:
                st.json(metadata, expanded=False)
