"""Helpers shared by the Streamlit pages: API URL, error messages, session id, feedback form."""

import os
import uuid

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")


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


def session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


def feedback_form(key: str, question: str, answer: str) -> None:
    """Thumbs up/down with an optional correction, stored via POST /feedback.

    `question` is stored as-is; variance reports use a "[variance] ..." prefix so the analysis
    script (evals/feedback_report.py) can tell them apart from Q&A turns.
    """
    sent_key = f"feedback_sent_{key}"
    if st.session_state.get(sent_key):
        st.caption("Thanks, your feedback was saved.")
        return
    with st.form(f"feedback_{key}"):
        correction = st.text_input("Correction or comment (optional)", key=f"fb_text_{key}")
        up_col, down_col = st.columns(2)
        up = up_col.form_submit_button("👍 Helpful")
        down = down_col.form_submit_button("👎 Not helpful")
    if up or down:
        try:
            r = httpx.post(f"{API_URL}/feedback", timeout=30, json={
                "session_id": session_id(), "question": question, "answer": answer,
                "rating": 1 if up else -1, "correction": correction.strip() or None})
            r.raise_for_status()
        except httpx.HTTPError as e:
            st.error(error_detail(e))
            return
        st.session_state[sent_key] = True
        st.rerun()
