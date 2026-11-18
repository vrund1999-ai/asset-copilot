"""Entry point: page config, shared sidebar (view toggle, API status) and navigation."""

import streamlit as st
from ui_common import api_status, inject_css, view_toggle

st.set_page_config(page_title="asset-copilot", page_icon="🏢", layout="wide")
inject_css()

pages = [
    st.Page("screens/home.py", title="Home", icon="🏠", default=True),
    st.Page("screens/ask.py", title="Ask", icon="💬", url_path="ask"),
    st.Page("screens/variance_report.py", title="Variance report", icon="📊",
            url_path="variance"),
]
view_toggle()
ok, detail = api_status()
st.sidebar.divider()
st.sidebar.caption(("🟢 " if ok else "🔴 ") + detail)
if not ok:
    st.sidebar.button("Check again", on_click=api_status.clear)
st.sidebar.caption("Synthetic data only.")
st.navigation(pages).run()
