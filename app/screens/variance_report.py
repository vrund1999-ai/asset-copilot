from datetime import date
from decimal import Decimal

import httpx
import streamlit as st
from ui_common import API_URL, current_view, error_detail, quick_feedback, session_id
from variance_view import (
    LABEL,
    column_config,
    driver_rows,
    flag_rows,
    totals_rows,
    trend_rows,
)

st.title("Variance report")
st.caption(
    "Budget vs actual for one month. All numbers are computed in code; the commentary is "
    "drafted by a model and checked against those numbers."
)


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


@st.cache_data(ttl=60, show_spinner=False)
def property_report(month: str, property_id: int) -> dict:
    """A property's numbers only (no model call), used by the drill-down."""
    r = httpx.post(f"{API_URL}/variance", timeout=60, json={
        "month": month[:7], "property_id": property_id, "commentary": False})
    r.raise_for_status()
    return r.json()


try:
    options = load_options()
except httpx.HTTPError as e:
    st.error(error_detail(e))
    st.stop()

props = {p["name"]: p["property_id"] for p in options["properties"]}
names = {v: k for k, v in props.items()}


def open_property(name: str, month: str) -> None:
    """Button callback: point the pickers at a property and regenerate on the next run."""
    st.session_state.scope_sel = name
    st.session_state.month_sel = month
    st.session_state.auto_generate = True


c1, c2, c3 = st.columns([2, 1, 1])
scope = c1.selectbox("Scope", ["Entire portfolio", *props], key="scope_sel")
month = c2.selectbox("Month", options["months"], format_func=month_label, key="month_sel")
want_commentary = c3.checkbox("Draft commentary", value=True,
                              help="Uses the model. Off = numbers only.")

if st.button("Generate report", type="primary") | bool(st.session_state.pop("auto_generate", False)):
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
view = current_view()
cfg = column_config(st)
st.subheader(f"{state['scope']} · {month_label(state['month'])}")

cols = st.columns(3)
for col, ln in zip(cols, rep["totals"], strict=True):
    col.metric(LABEL[ln["line"]], usd(ln["actual"]),
               delta=f"{sgn(ln['variance'])} ({pct(ln['variance_pct'])}) vs budget",
               delta_color="inverse" if ln["line"] == "opex" else "normal")

# 1. Flagged items first, with drill-down.
flags = flag_rows(rep)
st.subheader(f"Flagged for review ({len(flags)})")
st.caption(f"Variance of at least {rep['flag_pct']}% and {usd(rep['flag_min_usd'])}, largest first. "
           "Select a row to see that property.")
if flags:
    event = st.dataframe(flags, width="stretch", hide_index=True, column_config=cfg,
                         on_select="rerun", selection_mode="single-row", key=f"flag_table_{state['scope']}_{state['month']}")
    picked = event.selection.rows
    if picked:
        f = flags[picked[0]]
        if f["property_id"] is None:
            st.info("This flag is the portfolio total. Select a property row to drill in.")
        else:
            st.markdown(f"**{f['Item']}** · {f['Line']} · {month_label(state['month'])}")
            try:
                months = options["months"]
                i = months.index(state["month"])
                history = [state["month"], *months[i + 1:i + 4]]
                reports = [(m[:7], property_report(m, f["property_id"])) for m in history]
                st.dataframe(trend_rows(reports), width="stretch", hide_index=True,
                             column_config=cfg)
                st.caption("This month and up to three earlier months, same property.")
            except (httpx.HTTPError, ValueError) as e:
                st.error(error_detail(e) if isinstance(e, httpx.HTTPError) else str(e))
            st.button("Open the full report for this property", key="open_prop",
                      on_click=open_property, args=(names[f["property_id"]], state["month"]))
else:
    st.success("No items exceed the review thresholds.")

# 2. Commentary.
st.subheader("Commentary")
if rep.get("commentary"):
    st.write(rep["commentary"])
    if rep["commentary_source"] == "template":
        st.caption("⚠️ Template summary built directly from the tables. "
                   + (rep.get("commentary_note") or ""))
    else:
        st.caption("✅ Drafted by the model; every number was checked against the tables.")
    if view == "Reviewer":
        st.caption("Check applied: any number in the commentary that is not in the computed "
                   "tables causes a fallback to the template summary. "
                   f"Source for this report: {rep['commentary_source']}.")
    quick_feedback(f"variance_{state['scope']}_{state['month']}",
                   f"[variance] {state['scope']} {state['month'][:7]}", rep["commentary"])
else:
    st.caption("Commentary was not requested.")

# 3. Full tables: open by default for the Analyst view.
with st.expander("Full tables", expanded=view == "Analyst"):
    st.markdown("**Totals**")
    st.dataframe(totals_rows(rep), width="stretch", hide_index=True, column_config=cfg)
    if rep["scope"] == "portfolio":
        st.markdown("**Largest drivers (by NOI variance)**")
        st.dataframe(driver_rows(rep), width="stretch", hide_index=True, column_config=cfg)
    st.caption("Click a column heading to sort.")
