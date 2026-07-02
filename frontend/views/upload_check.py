# frontend/views/upload_check.py
# Upload suitability page: hwp/pdf -> POST /upload -> SuitabilityResult.
# Uploaded files are transient on the server (checked, then discarded).

from typing import Any

import streamlit as st

from api_client import ApiClientError, RagApiClient

MAX_UPLOAD_MB = 20  # keep in sync with api/routers/upload.py MAX_UPLOAD_BYTES

st.title("📤 업로드 적합성 검사")
st.caption(
    "업로드한 문서가 RFP로서 적합한지 참조 코퍼스와 비교해 판정합니다. "
    "문서는 검사 후 폐기되며 서버에 저장되지 않습니다."
)

uploaded = st.file_uploader(f"RFP 문서 (hwp/pdf, 최대 {MAX_UPLOAD_MB}MB)", type=["pdf", "hwp"])

if uploaded is not None:
    size_mb = uploaded.size / (1024 * 1024)
    if uploaded.size == 0:
        st.error("빈 파일입니다. 내용을 확인 후 다시 업로드하세요.")
        st.stop()
    if size_mb > MAX_UPLOAD_MB:
        st.error(f"파일이 너무 큽니다 ({size_mb:.1f}MB / 최대 {MAX_UPLOAD_MB}MB).")
        st.stop()

    st.caption(f"선택됨: {uploaded.name} ({size_mb:.2f}MB)")

    if st.button("적합성 검사 실행", type="primary"):
        client = RagApiClient()
        try:
            with st.spinner("적합성 검사 중..."):
                result = client.check_upload(
                    filename=uploaded.name,
                    content=uploaded.getvalue(),
                    content_type=uploaded.type or "application/octet-stream",
                )
        except ApiClientError as e:
            st.error(e.message)
            st.stop()

        is_suitable = bool(result.get("is_suitable"))
        score = result.get("score")
        score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "-"

        if is_suitable:
            st.success(f"✅ RFP로 적합합니다 (score {score_text})")
        else:
            st.error(f"❌ RFP로 부적합합니다 (score {score_text})")

        reasons: list[str] = result.get("reasons") or []
        if reasons:
            st.subheader("판정 근거")
            for reason in reasons:
                st.markdown(f"- {reason}")

        sources: list[dict[str, Any]] = result.get("sources") or []
        if sources:
            st.subheader(f"참조 코퍼스 비교 근거 ({len(sources)}건)")
            for i, source in enumerate(sources, start=1):
                chunk = source.get("chunk") or {}
                with st.expander(f"[{i}] {chunk.get('chunk_id', '(id 없음)')}"):
                    st.write(chunk.get("text") or "_(본문 없음)_")

        usage = result.get("usage") or {}
        if usage:
            st.caption(f"usage: {usage}")
