"""Variance report: actuals vs budget for one property or the whole portfolio, for one month.

Everything numeric is computed here, deterministically, in Decimal. The LLM only drafts commentary
on top of these tables (see variance_commentary.py) and may not introduce numbers of its own.

Conventions:
  - variance = actual - budget (dollars); variance_pct = variance / budget * 100, 2 decimals,
    None when the budget is 0. NOI = revenue - opex for both actual and budget.
  - favorable: revenue and NOI above budget, opex below budget. None when variance is 0.
  - an item is FLAGGED for human review when |variance_pct| >= flag_pct AND |variance| >= flag_min_usd
    (if the budget is 0 and the percentage is undefined, the dollar threshold alone applies).
  - drivers: the properties with the largest absolute NOI variance. noi_contribution_pct is that
    property's NOI variance as a share of the total NOI variance; it can exceed 100% or be negative
    when properties offset each other, and is None when the total variance is 0.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text

from . import db
from .config import settings
from .db import readonly_engine

CENT = Decimal("0.01")
LINES = ("revenue", "opex", "noi")


class ReportError(ValueError):
    """The report cannot be produced (unknown month or property). Safe to show to the user."""


class LineVariance(BaseModel):
    line: Literal["revenue", "opex", "noi"]
    actual: Decimal
    budget: Decimal
    variance: Decimal
    variance_pct: Decimal | None
    favorable: bool | None
    flagged: bool


class PropertyVariance(BaseModel):
    property_id: int
    name: str
    asset_type: str
    lines: list[LineVariance]
    noi_contribution_pct: Decimal | None = None


class Flag(BaseModel):
    property_id: int | None  # None = the portfolio-level total
    name: str
    line: str
    variance: Decimal
    variance_pct: Decimal | None


class VarianceReport(BaseModel):
    scope: Literal["portfolio", "property"]
    property_id: int | None
    property_name: str | None
    month: date
    n_properties: int
    totals: list[LineVariance]
    drivers: list[PropertyVariance]
    flags: list[Flag]
    flag_pct: Decimal
    flag_min_usd: Decimal
    commentary: str | None = None
    commentary_source: Literal["llm", "template"] | None = None
    commentary_note: str | None = None


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def line_variance(line: str, actual: Decimal, budget: Decimal, flag_pct: Decimal,
                  flag_min_usd: Decimal) -> LineVariance:
    actual, budget = Decimal(actual), Decimal(budget)
    variance = actual - budget
    pct = _q(variance / budget * 100) if budget != 0 else None
    if variance == 0:
        favorable = None
    else:
        favorable = variance < 0 if line == "opex" else variance > 0
    big_dollars = abs(variance) >= flag_min_usd
    flagged = big_dollars and (pct is None or abs(pct) >= flag_pct)
    return LineVariance(line=line, actual=_q(actual), budget=_q(budget), variance=_q(variance),
                        variance_pct=pct, favorable=favorable, flagged=flagged)


def _lines(rev_a, opex_a, rev_b, opex_b, flag_pct, flag_min_usd, noi_a=None) -> list[LineVariance]:
    rev_a, opex_a, rev_b, opex_b = (Decimal(v) for v in (rev_a, opex_a, rev_b, opex_b))
    noi_a = Decimal(noi_a) if noi_a is not None else rev_a - opex_a
    pairs = (("revenue", rev_a, rev_b), ("opex", opex_a, opex_b),
             ("noi", noi_a, rev_b - opex_b))
    return [line_variance(n, a, b, flag_pct, flag_min_usd) for n, a, b in pairs]


def compute_report(
    rows: list[dict], month: date, property_id: int | None = None, *,
    flag_pct: Decimal | None = None, flag_min_usd: Decimal | None = None,
    top_n: int | None = None,
) -> VarianceReport:
    """Pure function. `rows`: one dict per property with a_rev, a_opex, a_noi, b_rev, b_opex."""
    flag_pct = settings.variance_flag_pct if flag_pct is None else flag_pct
    flag_min_usd = settings.variance_flag_min_usd if flag_min_usd is None else flag_min_usd
    top_n = settings.variance_top_n if top_n is None else top_n
    if not rows:
        raise ReportError("No operating and budget data for that month and scope.")

    rows = sorted(rows, key=lambda r: r["property_id"])
    sums = {k: sum((Decimal(r[k]) for r in rows), Decimal(0))
            for k in ("a_rev", "a_opex", "a_noi", "b_rev", "b_opex")}
    totals = _lines(sums["a_rev"], sums["a_opex"], sums["b_rev"], sums["b_opex"],
                    flag_pct, flag_min_usd, sums["a_noi"])
    total_noi_var = totals[2].variance

    props = []
    for r in rows:
        lines = _lines(r["a_rev"], r["a_opex"], r["b_rev"], r["b_opex"], flag_pct, flag_min_usd,
                       r["a_noi"])
        contrib = (_q(lines[2].variance / total_noi_var * 100) if total_noi_var != 0 else None)
        props.append(PropertyVariance(
            property_id=r["property_id"], name=r["name"], asset_type=r["asset_type"],
            lines=lines, noi_contribution_pct=contrib))

    single = property_id is not None
    drivers = props if single else sorted(
        props, key=lambda p: (-abs(p.lines[2].variance), p.property_id))[:top_n]

    def flags_of(pid, name, lines):
        return [Flag(property_id=pid, name=name, line=ln.line, variance=ln.variance,
                     variance_pct=ln.variance_pct) for ln in lines if ln.flagged]

    if single:
        flags = flags_of(props[0].property_id, props[0].name, props[0].lines)
    else:  # portfolio total first, then properties by size of NOI variance
        flags = flags_of(None, "Portfolio total", totals)
        for p in sorted(props, key=lambda p: (-abs(p.lines[2].variance), p.property_id)):
            flags += flags_of(p.property_id, p.name, p.lines)

    return VarianceReport(
        scope="property" if single else "portfolio", property_id=property_id,
        property_name=rows[0]["name"] if single else None, month=month, n_properties=len(rows),
        totals=totals, drivers=drivers, flags=flags, flag_pct=flag_pct,
        flag_min_usd=flag_min_usd)


_ROWS_SQL = (
    "SELECT p.property_id, p.name, p.asset_type, o.revenue AS a_rev, o.opex AS a_opex, "
    "o.noi AS a_noi, b.revenue AS b_rev, b.opex AS b_opex "
    "FROM operating_statements o JOIN budgets b USING (property_id, month) "
    "JOIN properties p USING (property_id) WHERE o.month = :m "
)


def fetch_rows(month: date, property_id: int | None = None) -> list[dict]:
    """Fixed, parameterised query on the read-only role (the report never builds SQL from text)."""
    sql = _ROWS_SQL + ("AND p.property_id = :pid " if property_id is not None else "")
    params: dict = {"m": month}
    if property_id is not None:
        params["pid"] = property_id
    with readonly_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql + "ORDER BY p.property_id"),
                                                       params)]


def options() -> dict:
    """Months with both actuals and budget, newest first, and the property list."""
    with readonly_engine().connect() as conn:
        months = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT o.month FROM operating_statements o JOIN budgets b "
            "USING (property_id, month) ORDER BY 1 DESC"))]
        props = [dict(r._mapping) for r in conn.execute(text(
            "SELECT property_id, name FROM properties ORDER BY name"))]
    return {"months": months, "properties": props}


def build_report(month: date, property_id: int | None = None, *, commentary: bool = True,
                 session_id: str | None = None, client=None) -> VarianceReport:
    month = month.replace(day=1)
    rows = fetch_rows(month, property_id)
    if not rows:
        what = f"property {property_id}" if property_id is not None else "the portfolio"
        raise ReportError(f"No operating and budget data for {what} in {month:%Y-%m}.")
    report = compute_report(rows, month, property_id)
    db.audit("variance_report", {"scope": report.scope, "property_id": property_id,
                              "month": month.isoformat(), "n_properties": report.n_properties,
                              "flags": len(report.flags)}, session_id)
    if commentary:
        from .variance_commentary import attach_commentary

        attach_commentary(report, client=client, session_id=session_id)
    return report


class PortfolioSummary(BaseModel):
    """Landing-page snapshot: portfolio size and the latest month vs budget."""

    month: date
    n_properties: int
    n_active_leases: int
    n_expiring_12m: int  # active leases ending within 12 months of the as-of date
    n_documents: int
    totals: list[LineVariance]
    n_flags: int
    flag_pct: Decimal
    flag_min_usd: Decimal


def portfolio_summary(as_of: date | None = None) -> PortfolioSummary:
    """Counts plus the portfolio totals for the latest month that has actuals and budget.

    Same numbers as the variance report for that month (it reuses compute_report); no commentary,
    no model call, and no audit row because nothing here is an agent action.
    """
    as_of = as_of or settings.as_of_date
    horizon = as_of + timedelta(days=365)
    months = options()["months"]
    if not months:
        raise ReportError("No months with both actuals and budget are loaded.")
    month = months[0]
    report = compute_report(fetch_rows(month), month)
    with readonly_engine().connect() as conn:
        counts = conn.execute(text(
            "SELECT (SELECT COUNT(*) FROM properties) AS props, "
            "(SELECT COUNT(*) FROM leases WHERE start_date <= :a AND end_date >= :a) AS active, "
            "(SELECT COUNT(*) FROM leases WHERE start_date <= :a AND end_date >= :a "
            "   AND end_date <= :h) AS expiring, "
            "(SELECT COUNT(*) FROM documents) AS docs"), {"a": as_of, "h": horizon}).one()
    return PortfolioSummary(
        month=month, n_properties=counts.props, n_active_leases=counts.active,
        n_expiring_12m=counts.expiring, n_documents=counts.docs, totals=report.totals,
        n_flags=len(report.flags), flag_pct=report.flag_pct, flag_min_usd=report.flag_min_usd)
