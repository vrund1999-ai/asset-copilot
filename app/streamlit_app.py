import os
import uuid

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="asset-copilot", page_icon="🏢", layout="wide")
st.title("asset-copilot")
st.caption("Ask questions about a synthetic CRE portfolio. Answers cite their sources.")


def error_detail(e: httpx.HTTPError) -> str:
    """Prefer the API's own error message over httpx's generic one."""
    if isinstance(e, httpx.HTTPStatusError):
        try:
            return f"{e.response.status_code}: {e.response.json()['detail']}"
        except (ValueError, KeyError, TypeError):
            return f"{e.response.status_code}: {e.response.text[:200]}"
    if isinstance(e, httpx.ConnectError):
        return f"Could not reach the API at {API_URL}. Is it running?"
    return f"Request failed: {e}"


def render(turn: dict) -> None:
    """Render one assistant turn by status: answered / cannot_determine / failed / error."""
    status = turn.get("status", "answered")
    if status == "error":
        st.error(turn["content"])
        return
    if status == "failed":
        st.error(turn["content"])
    elif status == "cannot_determine":
        st.info(turn["content"])
    else:
        st.markdown(turn["content"])
        if not turn.get("grounded", True):
            st.warning(
                "Some numbers in this answer could not be traced to a cited result. "
                "Check the sources before relying on it."
            )
    citations = turn.get("citations", [])
    if citations:
        with st.expander(f"Sources ({len(citations)})"):
            for c in citations:
                label = f"**{c['label']}**" if c.get("label") else ""
                if c["kind"] == "sql":
                    st.markdown(f"{label} SQL")
                    st.code(c["reference"], language="sql")
                else:
                    st.markdown(f"{label} {c['kind']}")
                    st.code(c["reference"])
    if turn.get("steps"):
        calls = "model call" if turn["steps"] == 1 else "model calls"
        st.caption(f"{turn['steps']} {calls} · session {turn.get('session_id', '')[:8]}")


if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.history = []

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        if turn["role"] == "user":
            st.markdown(turn["content"])
        else:
            render(turn)

if question := st.chat_input("e.g. Which assets have >20% lease rollover in the next 18 months?"):
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Querying the portfolio..."):
            try:
                r = httpx.post(
                    f"{API_URL}/ask",
                    json={"question": question, "session_id": st.session_state.session_id},
                    timeout=180,
                )
                r.raise_for_status()
                data = r.json()
                turn = {
                    "role": "assistant",
                    "content": data["answer"],
                    "status": data.get("status", "answered"),
                    "grounded": data.get("grounded", True),
                    "citations": data.get("citations", []),
                    "steps": data.get("steps", 0),
                    "session_id": data.get("session_id") or st.session_state.session_id,
                }
            except httpx.HTTPError as e:
                turn = {"role": "assistant", "content": error_detail(e), "status": "error"}
        render(turn)
    st.session_state.history.append(turn)
