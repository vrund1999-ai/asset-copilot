"""Landing page: what this is, a portfolio snapshot, and sample questions."""

from decimal import Decimal

import httpx
import streamlit as st
from ui_common import api_status, current_view, error_detail, portfolio_summary

SAMPLE_QUESTIONS = [
    "Which 5 cities have the most properties?",
    "Which lender has the largest total principal outstanding, and what is that total?",
    "Which 5 active leases have the highest base rent per sq ft, with property and suite?",
    "For how many properties does the loan mature before that property's latest lease expires?",
]

st.title("asset-copilot")
st.markdown(
    "Ask questions about a commercial real estate portfolio and get answers that show their "
    "sources: the query that was run, or the document and page. Review monthly budget-vs-actual "
    "with the largest drivers and items flagged for a person to look at."
)
st.caption("Everything here is synthetic data. Nothing is changed by asking questions.")


def usd(x: str) -> str:
    d = Decimal(x)
    return f"-${abs(d):,.0f}" if d < 0 else f"${d:,.0f}"


st.header("Portfolio snapshot")
api_ok, api_detail = api_status()
snap, snap_error = None, None
if not api_ok:  # never show a cached snapshot as if it were live
    snap_error = api_detail
else:
    try:
        snap = portfolio_summary()
    except httpx.HTTPError as e:
        snap_error = error_detail(e)
if snap is None:
    st.warning(f"The snapshot is unavailable. {snap_error}")
else:
    month = snap["month"][:7]
    st.caption(f"Latest month with actuals and budget: {month}. Counts as of the data's reporting date.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Properties", f"{snap['n_properties']:,}")
    c2.metric("Active leases", f"{snap['n_active_leases']:,}",
              help=f"{snap['n_expiring_12m']:,} of them expire within 12 months.")
    c3.metric("Documents loaded", f"{snap['n_documents']:,}")
    c4.metric("Items flagged for review", f"{snap['n_flags']:,}",
              help=f"Variance of at least {snap['flag_pct']}% and {usd(snap['flag_min_usd'])}.")
    cols = st.columns(3)
    names = {"revenue": "Revenue", "opex": "Operating expenses", "noi": "NOI"}
    for col, ln in zip(cols, snap["totals"], strict=True):
        pct = "n/a" if ln["variance_pct"] is None else f"{Decimal(ln['variance_pct']):+.2f}%"
        col.metric(names[ln["line"]] + " vs budget", usd(ln["actual"]), delta=pct,
                   delta_color="inverse" if ln["line"] == "opex" else "normal")
    st.caption(f"{snap['n_expiring_12m']:,} active leases expire within 12 months.")

st.header("Try a question")
cols = st.columns(2)
for i, q in enumerate(SAMPLE_QUESTIONS):
    if cols[i % 2].button(q, key=f"sample_{i}", width="stretch"):
        st.session_state.pending_question = q
        st.switch_page("screens/ask.py")

left, right = st.columns(2)
with left:
    st.page_link("screens/ask.py", label="Ask a question", icon="💬")
with right:
    st.page_link("screens/variance_report.py", label="Open the variance report", icon="📊")

if current_view() == "Reviewer":
    st.header("How answers are checked")
    CHECKS = [
        ("**Read-only by construction.** One SELECT at a time, on an approved list of tables, "
         "through a database role that cannot write."),
        ("**Numbers are traced.** Figures in an answer must appear in a cited result; otherwise "
         "the answer is marked as not grounded."),
        "**No arithmetic by the model.** Totals come from queries or a calculator tool.",
        "**Everything is logged** in an audit table with a session id.",
        ("**Measured, with limits.** See the README for the evaluation results and what they do "
         "and do not show."),
    ]
    st.markdown("\n".join(f"- {c}" for c in CHECKS))

with st.expander("What this cannot do"):
    st.markdown(
        "It only knows the database tables and the lease and loan documents loaded here. It "
        "cannot change data, look things up elsewhere, or forecast. When the data does not "
        "support an answer it says so."
    )
