# frontend/app.py
# Streamlit entrypoint. Run from this directory: streamlit run app.py
# Pages live in views/ and are registered here via st.navigation.

import streamlit as st

from api_client import RagApiClient

st.set_page_config(page_title="RFP RAG", page_icon="📄", layout="wide")

pages = st.navigation(
    [
        st.Page("views/rag_query.py", title="RFP 질의", icon="💬", default=True),
        st.Page("views/upload_check.py", title="업로드 적합성 검사", icon="📤"),
    ]
)

st.sidebar.caption(f"API: {RagApiClient().base_url}")

pages.run()
