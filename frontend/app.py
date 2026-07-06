# frontend/app.py
# Streamlit entrypoint. Run from this directory: streamlit run app.py
# Single-page chat UI (design spec v2): "home" greeting screen <-> "chat" screen,
# routed via session_state. No st.navigation/sidebar by design.

import streamlit as st

from styles import BASE_CSS
from ui import render_status_banner
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
    ss.setdefault("top_k", DEFAULT_TOP_K)
    ss.setdefault("checked_file_key", None)  # "<name>:<size>" of the checked upload
    ss.setdefault("suitability", None)  # SuitabilityResult dict or {"error": str}


def _route_home_submit() -> None:
    """Home chat_input submit -> switch to the chat screen within the same run.

    The submitted value is readable from session state before any widget
    renders. Routing here (instead of st.rerun() at the end of the home
    render) lets the run complete normally, so Streamlit clears the home
    widgets instead of leaving them dimmed on screen for the answer wait.
    """
    query = st.session_state.get("home_input")
    if st.session_state.screen != "home" or not query or not query.strip():
        return
    st.session_state.messages.append({"role": "user", "content": query.strip()})
    st.session_state.pending_query = query.strip()
    st.session_state.screen = "chat"


_init_state()
_route_home_submit()
st.html(BASE_CSS)
render_status_banner()  # 배포 롤백/점검 상황을 사용자에게 전파 (평시엔 아무것도 안 그림)
if st.session_state.screen == "home":
    home.render()
else:
    chat.render()
