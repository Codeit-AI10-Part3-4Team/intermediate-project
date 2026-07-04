# frontend/views/home.py
# First screen (spec v2): centered greeting + chat input + upload button + settings.
# Upload runs the suitability check only — the document is checked, discarded on
# the server, and never feeds /rag queries.

import streamlit as st

from api_client import ApiClientError, RagApiClient
from styles import HOME_CSS
from ui import CHECKING_HTML, GREETING_HTML, render_header

MAX_UPLOAD_MB = 20  # keep in sync with api/routers/upload.py MAX_UPLOAD_BYTES


def render() -> None:
    st.html(HOME_CSS)
    render_header(show_back=False)

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.html('<div style="height:16vh"></div>')
        # Filled at the end of the run: greeting normally, "검사 중" during a check.
        greeting = st.empty()
        st.html('<div style="height:0.5rem"></div>')

        query = st.chat_input("궁금한 것을 물어보세요", key="home_input")

        upload_col, gear_col = st.columns([6, 1], vertical_alignment="center")
        with upload_col:
            uploaded = st.file_uploader(
                "RFP 문서 업로드",
                type=["pdf", "hwp"],
                label_visibility="collapsed",
                key="uploader",
            )
        with gear_col:
            with st.popover(":material/settings:", help="검색 설정"):
                # key binding keeps the value alive after leaving this screen —
                # a keyless slider lingers as a stale element during the screen
                # switch and breaks AppTest state serialization.
                st.slider("근거 청크 수 (top_k)", 1, 50, key="top_k")
                st.caption(f"API: {RagApiClient().base_url}")
        st.html(
            '<div class="oop-cap">업로드한 문서는 RFP 적합성 검사 후 즉시 폐기되며 '
            "서버에 저장되지 않습니다</div>"
        )

        checking = False
        file_key = None
        if uploaded is not None:
            size_mb = uploaded.size / (1024 * 1024)
            file_key = f"{uploaded.name}:{uploaded.size}"
            if uploaded.size == 0:
                st.error("빈 파일입니다. 내용을 확인 후 다시 업로드하세요.")
            elif size_mb > MAX_UPLOAD_MB:
                st.error(f"파일이 너무 큽니다 ({size_mb:.1f}MB / 최대 {MAX_UPLOAD_MB}MB).")
            elif file_key != st.session_state.checked_file_key:
                checking = True
            else:
                _render_suitability_result()
        else:
            # Chip removed via its native ✕ -> forget the previous check.
            st.session_state.checked_file_key = None
            st.session_state.suitability = None

        greeting.html(CHECKING_HTML if checking else GREETING_HTML)

        if checking:
            # Runs after the greeting swap is on screen; reruns when done.
            _run_suitability_check(uploaded, file_key)

    if query and query.strip():
        st.session_state.messages.append({"role": "user", "content": query.strip()})
        st.session_state.pending_query = query.strip()
        st.session_state.pending_dispatched = False
        st.session_state.screen = "chat"
        st.rerun()


def _run_suitability_check(uploaded, file_key: str | None) -> None:
    """Blocking POST /upload; stores the result (or error) and reruns."""
    try:
        result = RagApiClient().check_upload(
            filename=uploaded.name,
            content=uploaded.getvalue(),
            content_type=uploaded.type or "application/octet-stream",
        )
        st.session_state.suitability = result
    except ApiClientError as e:
        st.session_state.suitability = {"error": e.message}
    st.session_state.checked_file_key = file_key
    st.rerun()


def _render_suitability_result() -> None:
    result = st.session_state.suitability
    if not result:
        return
    if "error" in result:
        st.error(result["error"])
        return
    score = result.get("score")
    score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "-"
    verdict = "pass" if result.get("is_suitable") else "fail"
    label = "RFP로 적합" if verdict == "pass" else "RFP로 부적합"
    st.html(
        '<div style="text-align:center">'
        f'<span class="oop-badge {verdict}">{label} · score {score_text}</span></div>'
    )
    for reason in result.get("reasons") or []:
        st.markdown(f"- {reason}")
