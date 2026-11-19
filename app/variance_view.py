"""Row builders for the variance report tables.

Values are floats only for display and sorting (the numbers were computed in code, as Decimals,
by the API). Keeping them numeric makes the Streamlit column headers sort by value, not by text.
"""

LABEL = {"revenue": "Revenue", "opex": "Operating expenses", "noi": "NOI"}
FAVORABLE = {True: "Favorable", False: "Unfavorable", None: "n/a"}


def _f(x: str | None) -> float | None:
    return None if x is None else float(x)


def flag_rows(rep: dict) -> list[dict]:
    """Flagged items, biggest absolute dollar variance first."""
    rows = [{"Item": f["name"], "Line": LABEL[f["line"]], "Variance ($)": _f(f["variance"]),
             "Variance (%)": _f(f["variance_pct"]), "property_id": f["property_id"]}
            for f in rep["flags"]]
    return sorted(rows, key=lambda r: -abs(r["Variance ($)"]))


def totals_rows(rep: dict) -> list[dict]:
    return [{"Line": LABEL[t["line"]], "Actual ($)": _f(t["actual"]), "Budget ($)": _f(t["budget"]),
             "Variance ($)": _f(t["variance"]), "Variance (%)": _f(t["variance_pct"]),
             "Result": FAVORABLE[t["favorable"]]} for t in rep["totals"]]


def driver_rows(rep: dict) -> list[dict]:
    """Largest NOI drivers; the table is sortable in the UI, this order is the API's."""
    out = []
    for d in rep["drivers"]:
        noi = next(line for line in d["lines"] if line["line"] == "noi")
        out.append({"Property": d["name"], "Type": d["asset_type"],
                    "NOI variance ($)": _f(noi["variance"]), "NOI variance (%)": _f(noi["variance_pct"]),
                    "Share of portfolio NOI variance (%)": _f(d["noi_contribution_pct"]),
                    "property_id": d["property_id"]})
    return out


def trend_rows(reports: list[tuple[str, dict]]) -> list[dict]:
    """One row per month for a single property: (month, report) pairs, newest first."""
    rows = []
    for month, rep in reports:
        t = {x["line"]: x for x in rep["totals"]}
        rows.append({"Month": month, "Revenue ($)": _f(t["revenue"]["actual"]),
                     "Opex ($)": _f(t["opex"]["actual"]), "NOI ($)": _f(t["noi"]["actual"]),
                     "NOI vs budget ($)": _f(t["noi"]["variance"]),
                     "NOI vs budget (%)": _f(t["noi"]["variance_pct"])})
    return rows


COLUMNS = {
    "Actual ($)": "dollar", "Budget ($)": "dollar", "Variance ($)": "dollar",
    "NOI variance ($)": "dollar", "Revenue ($)": "dollar", "Opex ($)": "dollar", "NOI ($)": "dollar",
    "NOI vs budget ($)": "dollar",
}
PCT_COLUMNS = ("Variance (%)", "NOI variance (%)", "Share of portfolio NOI variance (%)",
               "NOI vs budget (%)")


def column_config(st) -> dict:
    """Streamlit column formats: dollars with separators, signed percentages."""
    cfg = {c: st.column_config.NumberColumn(format=fmt) for c, fmt in COLUMNS.items()}
    cfg.update({c: st.column_config.NumberColumn(format="%+.2f%%") for c in PCT_COLUMNS})
    cfg["property_id"] = None  # hidden helper column used for drill-down
    return cfg
