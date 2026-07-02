# frontend/views/rag_query.py
# RAG query page: query + top_k -> POST /rag -> answer + source chunks.

from typing import Any

import streamlit as st

from api_client import ApiClientError, RagApiClient

st.title("💬 RFP 질의")
st.caption("정부 제안요청서(RFP) 참조 코퍼스를 근거로 질문에 답합니다.")

with st.form("rag_query_form"):
    query = st.text_area(
        "질문",
        placeholder="예) 이 사업의 수행 기간과 예산 규모는 어떻게 되나요?",
        height=120,
    )
    top_k = st.slider("근거 청크 수 (top_k)", min_value=1, max_value=50, value=5)
    submitted = st.form_submit_button("질의하기", type="primary")

if submitted:
    if not query.strip():
        st.warning("질문을 입력하세요.")
        st.stop()

    client = RagApiClient()
    try:
        with st.spinner("답변 생성 중..."):
            result = client.query_rag(query=query.strip(), top_k=top_k)
    except ApiClientError as e:
        st.error(e.message)
        st.stop()

    st.subheader("답변")
    st.markdown(result.get("answer") or "_(빈 답변)_")

    sources: list[dict[str, Any]] = result.get("sources") or []
    if sources:
        st.subheader(f"근거 ({len(sources)}건)")
        for i, source in enumerate(sources, start=1):
            chunk = source.get("chunk") or {}
            score = source.get("score")
            score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "-"
            label = f"[{i}] {chunk.get('chunk_id', '(id 없음)')} · score {score_text}"
            with st.expander(label):
                st.write(chunk.get("text") or "_(본문 없음)_")
                metadata = chunk.get("metadata") or {}
                if metadata:
                    st.json(metadata, expanded=False)

    usage = result.get("usage") or {}
    if usage:
        st.caption(f"usage: {usage}")
