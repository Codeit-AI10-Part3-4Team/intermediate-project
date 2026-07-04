# frontend/app.py
# Streamlit entrypoint. Run from this directory: streamlit run app.py
# Single-page chat UI (design spec v2): "home" greeting screen <-> "chat" screen,
# routed via session_state. No st.navigation/sidebar by design.

import streamlit as st

from styles import BASE_CSS
from views import chat, home

st.set_page_config(
    page_title="ㅇㅇㅍ — RFP의 모든 것",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DEFAULT_TOP_K = 5


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("screen", "home")  # "home" | "chat"
    ss.setdefault("messages", [])  # {"role", "content", "sources", "usage", "is_error"}
    ss.setdefault("pending_query", None)  # query awaiting a /rag response
    ss.setdefault("pending_dispatched", False)  # chat screen painted before the call
    ss.setdefault("top_k", DEFAULT_TOP_K)
    ss.setdefault("checked_file_key", None)  # "<name>:<size>" of the checked upload
    ss.setdefault("suitability", None)  # SuitabilityResult dict or {"error": str}


_init_state()
st.html(BASE_CSS)
if st.session_state.screen == "home":
    home.render()
else:
    chat.render()
