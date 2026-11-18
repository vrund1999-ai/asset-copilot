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


VIEWS = ("Asset manager", "Analyst", "Reviewer")
VIEW_HELP = {
    "Asset manager": "Plain-language answers first; sources one click away.",
    "Analyst": "Sources open by default, for checking the SQL and documents.",
    "Reviewer": "Adds how answers are checked and where the results are documented.",
}


def current_view() -> str:
    """The selected view. It changes presentation only, never the answer.

    Kept under a plain session key (not the radio's widget key): st.switch_page drops widget
    state, which silently reset the view when a sample question moved the user to Ask.
    """
    view = st.session_state.get("_view")
    return view if view in VIEWS else VIEWS[0]


def view_toggle() -> None:
    """Sidebar radio; mirrored into the URL (?view=analyst) so a link keeps the choice."""
    if "_view" not in st.session_state:
        wanted = str(st.query_params.get("view", "")).lower()
        st.session_state["_view"] = next(
            (v for v in VIEWS if v.split()[0].lower() == wanted), VIEWS[0])
    st.session_state["_view"] = st.sidebar.radio(
        "View", VIEWS, index=VIEWS.index(current_view()),
        help="Changes how results are shown, not the answers themselves.")
    st.sidebar.caption(VIEW_HELP[current_view()])
    st.query_params["view"] = current_view().split()[0].lower()


@st.cache_data(ttl=15, show_spinner=False)
def api_status() -> tuple[bool, str]:
    """(reachable, detail) from GET /health, cached briefly so every rerun does not hit the API."""
    try:
        httpx.get(f"{API_URL}/health", timeout=3).raise_for_status()
        return True, "API reachable"
    except httpx.HTTPError as e:
        return False, error_detail(e)


@st.cache_data(ttl=60, show_spinner=False)
def portfolio_summary() -> dict:
    r = httpx.get(f"{API_URL}/portfolio/summary", timeout=30)
    r.raise_for_status()
    return r.json()


CSS = """
<style>
  [data-testid="stMetricValue"], [data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
  .ac-card { border: 1px solid rgba(128,128,128,.25); border-radius: .6rem; padding: .9rem 1rem;
             height: 100%; }
  .ac-card h4 { margin: 0 0 .3rem 0; font-size: 1rem; }
  .ac-muted { opacity: .7; font-size: .9rem; }
  .block-container { padding-top: 2rem; max-width: 1200px; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
