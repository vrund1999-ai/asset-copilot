import os
import uuid

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="asset-copilot", page_icon="🏢", layout="wide")
st.title("asset-copilot")
st.caption("Ask questions about a synthetic CRE portfolio. Answers cite their sources.")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.history = []

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])

if question := st.chat_input("e.g. Which assets have >20% lease rollover in the next 18 months?"):
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            r = httpx.post(
                f"{API_URL}/ask",
                json={"question": question, "session_id": st.session_state.session_id},
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            answer = data["answer"]
            st.markdown(answer)
            for c in data.get("citations", []):
                st.caption(f"Source ({c['kind']}): {c['reference']}")
        except httpx.HTTPError as e:
            answer = f"Request failed: {e}"
            st.error(answer)
    st.session_state.history.append({"role": "assistant", "content": answer})
