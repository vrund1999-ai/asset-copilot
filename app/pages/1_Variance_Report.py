from datetime import date
from decimal import Decimal

import httpx
import streamlit as st
from ui_common import API_URL, error_detail, feedback_form, session_id

st.set_page_config(page_title="Variance report", page_icon="📊", layout="wide")
st.title("Variance report")
st.caption(
    "Budget vs actual for one month. All numbers are computed in code; the commentary is "
    "drafted by a model and checked against those numbers."
)

LABEL = {"revenue": "Revenue", "opex": "Operating expenses", "noi": "NOI"}


def usd(x: str) -> str:
    d = Decimal(x)
    return f"-${abs(d):,.2f}" if d < 0 else f"${d:,.2f}"


def sgn(x: str) -> str:
    """Signed dollar amount for variances: +$1,000.00 / -$1,000.00."""
    d = Decimal(x)
    return f"+${d:,.2f}" if d > 0 else usd(x)


def pct(x: str | None) -> str:
    return "n/a" if x is None else f"{Decimal(x):+.2f}%"


def month_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%B %Y}"


@st.cache_data(ttl=60, show_spinner=False)
def load_options() -> dict:
    r = httpx.get(f"{API_URL}/variance/options", timeout=30)
    r.raise_for_status()
    return r.json()


try:
    options = load_options()
except httpx.HTTPError as e:
    st.error(error_detail(e))
    st.stop()

props = {p["name"]: p["property_id"] for p in options["properties"]}
c1, c2, c3 = st.columns([2, 1, 1])
scope = c1.selectbox("Scope", ["Entire portfolio", *props])
month = c2.selectbox("Month", options["months"], format_func=month_label)
want_commentary = c3.checkbox("Draft commentary", value=True,
                              help="Uses the model. Off = numbers only.")

if st.button("Generate report", type="primary"):
    with st.spinner("Computing variances..."):
        try:
            r = httpx.post(f"{API_URL}/variance", timeout=180, json={
                "month": month[:7], "property_id": props.get(scope),
                "commentary": want_commentary, "session_id": session_id()})
            r.raise_for_status()
            st.session_state.variance = {"report": r.json(), "scope": scope, "month": month}
        except httpx.HTTPError as e:
            st.session_state.variance = {"error": error_detail(e)}

state = st.session_state.get("variance")
if not state:
    st.info("Choose a scope and month, then press Generate report.")
    st.stop()
if "error" in state:
    st.error(state["error"])
    st.stop()

rep = state["report"]
st.subheader(f"{state['scope']} · {month_label(state['month'])}")

cols = st.columns(3)
for col, ln in zip(cols, rep["totals"], strict=True):
    col.metric(LABEL[ln["line"]], usd(ln["actual"]),
               delta=f"{sgn(ln['variance'])} ({pct(ln['variance_pct'])}) vs budget",
               delta_color="inverse" if ln["line"] == "opex" else "normal")

st.markdown("**Totals**")
st.dataframe([{"Line": LABEL[ln["line"]], "Actual": usd(ln["actual"]),
               "Budget": usd(ln["budget"]), "Variance": sgn(ln["variance"]),
               "Variance %": pct(ln["variance_pct"]),
               "Favorable": {True: "yes", False: "no", None: "-"}[ln["favorable"]]}
              for ln in rep["totals"]], width="stretch", hide_index=True)

if rep["scope"] == "portfolio":
    st.markdown("**Largest drivers (by NOI variance)**")
    st.dataframe([{"Property": d["name"], "Type": d["asset_type"],
                   "NOI variance": sgn(d["lines"][2]["variance"]),
                   "NOI variance %": pct(d["lines"][2]["variance_pct"]),
                   "Share of portfolio NOI variance": pct(d["noi_contribution_pct"])}
                  for d in rep["drivers"]], width="stretch", hide_index=True)

st.markdown("**Flagged for human review**")
st.caption(f"Items with |variance| ≥ {rep['flag_pct']}% and ≥ {usd(rep['flag_min_usd'])}.")
if rep["flags"]:
    st.dataframe([{"Item": f["name"], "Line": LABEL[f["line"]], "Variance": sgn(f["variance"]),
                   "Variance %": pct(f["variance_pct"])} for f in rep["flags"]],
                 width="stretch", hide_index=True)
else:
    st.success("No items exceed the review thresholds.")

st.markdown("**Commentary**")
if rep.get("commentary"):
    st.write(rep["commentary"])
    if rep["commentary_source"] == "template":
        st.caption("Template summary built directly from the tables. "
                   + (rep.get("commentary_note") or ""))
    else:
        st.caption("Drafted by the model; every number was checked against the tables above.")
    feedback_form(f"variance_{state['scope']}_{state['month']}",
                  f"[variance] {state['scope']} {state['month'][:7]}", rep["commentary"])
else:
    st.caption("Commentary was not requested.")
