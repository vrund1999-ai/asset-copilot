"""Variance report numbers vs an independent gold SQL calculation, on the real synthetic database.

The gold side computes sums, variances AND percentages in Postgres (admin connection); the report
side runs the production path (read-only role, Decimal arithmetic in Python). They must agree
exactly. Skipped automatically when no database is available (CI).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from asset_copilot import variance

pytestmark = pytest.mark.integration

GOLD = """
SELECT SUM(o.revenue) AS a_rev, SUM(b.revenue) AS b_rev,
       SUM(o.opex) AS a_opex, SUM(b.opex) AS b_opex,
       SUM(o.noi) AS a_noi, SUM(b.revenue - b.opex) AS b_noi,
       COUNT(*) AS n
FROM operating_statements o JOIN budgets b USING (property_id, month)
WHERE o.month = :m {scope}
"""


def gold(engine, month, property_id=None):
    scope = "AND o.property_id = :p" if property_id is not None else ""
    with engine.connect() as conn:
        r = conn.execute(text(GOLD.format(scope=scope)),
                         {"m": month, "p": property_id}).one()._mapping
        out = {"n": r["n"]}
        for line, a, b in (("revenue", "a_rev", "b_rev"), ("opex", "a_opex", "b_opex"),
                           ("noi", "a_noi", "b_noi")):
            row = conn.execute(
                text("SELECT :a - :b AS v, ROUND((:a - :b) / NULLIF(:b, 0) * 100, 2) AS p"),
                {"a": r[a], "b": r[b]}).one()
            out[line] = (r[a], r[b], row.v, row.p)
    return out


def check(report, expected):
    assert report.n_properties == expected["n"]
    for ln in report.totals:
        a, b, v, p = expected[ln.line]
        assert (ln.actual, ln.budget, ln.variance, ln.variance_pct) == (a, b, v, p), ln.line


def all_months(engine):
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text(
            "SELECT DISTINCT month FROM operating_statements ORDER BY 1"))]


def test_portfolio_totals_match_gold_sql_for_every_month(live_db):
    months = all_months(live_db)
    assert len(months) == 24
    for m in months:
        check(variance.build_report(m, commentary=False), gold(live_db, m))


def test_property_reports_match_gold_sql(live_db):
    months = all_months(live_db)
    with live_db.connect() as conn:
        pids = [r[0] for r in conn.execute(text(
            "SELECT property_id FROM properties ORDER BY property_id"))]
    for pid in pids[::7]:  # a spread of properties across asset types
        for m in (months[0], months[11], months[-1]):
            rep = variance.build_report(m, pid, commentary=False)
            check(rep, gold(live_db, m, pid))
            assert rep.scope == "property" and rep.property_id == pid


def test_drivers_and_contributions_match_gold_sql(live_db):
    m = date(2026, 6, 1)
    with live_db.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(
            "SELECT o.property_id, o.noi - (b.revenue - b.opex) AS v, "
            "ROUND((o.noi - (b.revenue - b.opex)) / (SELECT SUM(o2.noi - (b2.revenue - b2.opex)) "
            "FROM operating_statements o2 JOIN budgets b2 USING (property_id, month) "
            "WHERE o2.month = :m) * 100, 2) AS contrib "
            "FROM operating_statements o JOIN budgets b USING (property_id, month) "
            "WHERE o.month = :m ORDER BY abs(o.noi - (b.revenue - b.opex)) DESC, o.property_id "
            "LIMIT 5"), {"m": m})]
    rep = variance.build_report(m, commentary=False)
    assert [(d.property_id, d.lines[2].variance, d.noi_contribution_pct) for d in rep.drivers] == [
        (r["property_id"], r["v"], r["contrib"]) for r in rows]


def test_flagged_items_follow_the_documented_thresholds(live_db):
    rep = variance.build_report(date(2026, 6, 1), commentary=False)
    assert rep.flags, "expected some flagged items in the latest month"
    for f in rep.flags:
        assert abs(f.variance) >= rep.flag_min_usd
        assert f.variance_pct is None or abs(f.variance_pct) >= rep.flag_pct
    assert all(isinstance(f.variance, Decimal) for f in rep.flags)


def test_report_writes_audit_row_with_session(live_db):
    with live_db.connect() as conn:
        before = conn.execute(text(
            "SELECT count(*) FROM audit_log WHERE session_id = 'itest-variance'")).scalar()
    variance.build_report(date(2026, 6, 1), commentary=False, session_id="itest-variance")
    with live_db.begin() as conn:
        after = conn.execute(text(
            "SELECT count(*) FROM audit_log WHERE session_id = 'itest-variance'")).scalar()
        conn.execute(text("DELETE FROM audit_log WHERE session_id = 'itest-variance'"))
    assert after == before + 1


def test_portfolio_summary_matches_gold_sql(live_db):
    s = variance.portfolio_summary()
    with live_db.connect() as conn:
        latest = conn.execute(text(
            "SELECT MAX(o.month) FROM operating_statements o JOIN budgets b "
            "USING (property_id, month)")).scalar()
        props = conn.execute(text("SELECT COUNT(*) FROM properties")).scalar()
        active = conn.execute(text(
            "SELECT COUNT(*) FROM leases WHERE start_date <= :a AND end_date >= :a"),
            {"a": date(2026, 6, 30)}).scalar()
        expiring = conn.execute(text(
            "SELECT COUNT(*) FROM leases WHERE start_date <= :a AND end_date >= :a "
            "AND end_date <= :a + 365"), {"a": date(2026, 6, 30)}).scalar()
        docs = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar()
    g = gold(live_db, latest)
    assert s.month == latest and s.n_properties == props
    assert (s.n_active_leases, s.n_expiring_12m, s.n_documents) == (active, expiring, docs)
    by = {ln.line: ln for ln in s.totals}
    for line in ("revenue", "opex", "noi"):
        a, b, v, p = g[line]
        assert (by[line].actual, by[line].budget, by[line].variance) == (a, b, v)
        assert by[line].variance_pct == p
    assert s.n_flags == len(variance.compute_report(variance.fetch_rows(latest), latest).flags)
