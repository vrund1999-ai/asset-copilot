"""Variance math, commentary checking and the /variance endpoints. No network, DB or model."""

from datetime import date
from decimal import Decimal

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from asset_copilot import api, variance, variance_commentary
from asset_copilot.agent import AgentConfigError
from asset_copilot.variance import ReportError, compute_report, line_variance
from asset_copilot.variance_commentary import (
    attach_commentary,
    tables_record,
    template_commentary,
    ungrounded_numbers,
)
from fakes import FakeClient, response, text

D = Decimal
MONTH = date(2026, 6, 1)


def row(pid, a_rev, a_opex, b_rev, b_opex, name=None, asset_type="office"):
    return {"property_id": pid, "name": name or f"Prop {pid}", "asset_type": asset_type,
            "a_rev": D(a_rev), "a_opex": D(a_opex), "a_noi": D(a_rev) - D(a_opex),
            "b_rev": D(b_rev), "b_opex": D(b_opex)}


ROWS = [
    row(1, "1000000.00", "400000.00", "1100000.00", "400000.00"),   # NOI -100,000 (-14.29%)
    row(2, "500000.00", "300000.00", "480000.00", "290000.00"),     # NOI +10,000
    row(3, "800000.00", "500000.00", "800000.00", "500000.00"),     # on budget
    row(4, "600000.00", "330000.00", "600000.00", "300000.00"),     # opex +30,000 (10%)
]


# ---- line math -------------------------------------------------------------------------------

def test_variance_is_actual_minus_budget_in_exact_decimal():
    ln = line_variance("revenue", D("100.10"), D("100.00"), D(10), D(25000))
    assert ln.variance == D("0.10") and ln.variance_pct == D("0.10")
    assert isinstance(ln.variance, Decimal)


@pytest.mark.parametrize("line,actual,budget,favorable", [
    ("revenue", 110, 100, True), ("revenue", 90, 100, False),
    ("opex", 110, 100, False), ("opex", 90, 100, True),
    ("noi", 110, 100, True), ("noi", 90, 100, False),
    ("revenue", 100, 100, None), ("opex", 100, 100, None),
])
def test_favorable_direction(line, actual, budget, favorable):
    assert line_variance(line, D(actual), D(budget), D(10), D(0)).favorable is favorable


def test_percentage_rounds_half_away_from_zero():
    # 2.345% exactly -> 2.35 (and -2.35), matching SQL ROUND on numeric.
    assert line_variance("revenue", D("102.345"), D("100"), D(10), D(0)).variance_pct == D("2.35")
    assert line_variance("revenue", D("97.655"), D("100"), D(10), D(0)).variance_pct == D("-2.35")


def test_zero_budget_has_no_percentage():
    ln = line_variance("noi", D("5000"), D("0"), D(10), D(1000))
    assert ln.variance_pct is None and ln.flagged  # dollar threshold alone applies
    assert not line_variance("noi", D("500"), D("0"), D(10), D(1000)).flagged


def test_flag_thresholds_are_inclusive():
    # exactly 10% and exactly $10,000 meets both thresholds
    assert line_variance("revenue", D("110000"), D("100000"), D(10), D(10000)).flagged


def test_flag_uses_the_rounded_percentage_shown_in_the_report():
    # 9.999% displays as 10.00%, so it is flagged: what the reader sees is what triggers review
    ln = line_variance("revenue", D("109999"), D("100000"), D(10), D(9000))
    assert ln.variance_pct == D("10.00") and ln.flagged
    below = line_variance("revenue", D("109900"), D("100000"), D(10), D(9000))
    assert below.variance_pct == D("9.90") and not below.flagged


def test_big_percent_but_small_dollars_is_not_flagged():
    assert not line_variance("revenue", D("1500"), D("1000"), D(10), D(25000)).flagged


def test_big_dollars_but_small_percent_is_not_flagged():
    assert not line_variance("revenue", D("10100000"), D("10000000"), D(10), D(25000)).flagged


# ---- report ----------------------------------------------------------------------------------

def test_portfolio_totals_are_sums_and_noi_is_revenue_minus_opex():
    r = compute_report(ROWS, MONTH, flag_pct=D(10), flag_min_usd=D(25000))
    rev, opex, noi = r.totals
    assert rev.actual == D("2900000.00") and rev.budget == D("2980000.00")
    assert opex.actual == D("1530000.00") and opex.budget == D("1490000.00")
    assert noi.actual == D("1370000.00") and noi.budget == D("1490000.00")
    assert noi.variance == D("-120000.00") and noi.variance_pct == D("-8.05")
    assert r.scope == "portfolio" and r.n_properties == 4 and r.property_id is None


def test_drivers_ranked_by_absolute_noi_variance_with_id_tiebreak():
    rows = ROWS + [row(5, "100", "0", "100", "10")]  # NOI +10 ... small
    r = compute_report(rows, MONTH, top_n=3)
    assert [d.property_id for d in r.drivers] == [1, 4, 2]  # -100k, -30k, +10k
    tie = compute_report([row(9, "10", "0", "20", "0"), row(3, "10", "0", "20", "0")], MONTH)
    assert [d.property_id for d in tie.drivers] == [3, 9]


def test_noi_contributions_sum_to_100_over_all_properties():
    r = compute_report(ROWS, MONTH, top_n=10)
    assert sum(d.noi_contribution_pct for d in r.drivers) == D("100.00")
    assert r.drivers[0].noi_contribution_pct == D("83.33")  # -100k of -120k


def test_contribution_is_none_when_total_variance_is_zero():
    rows = [row(1, "110", "0", "100", "0"), row(2, "90", "0", "100", "0")]
    r = compute_report(rows, MONTH)
    assert r.totals[2].variance == 0
    assert all(d.noi_contribution_pct is None for d in r.drivers)


def test_flags_portfolio_total_first_then_properties_by_size():
    r = compute_report(ROWS, MONTH, flag_pct=D(10), flag_min_usd=D(25000))
    got = [(f.name, f.line) for f in r.flags]
    # Prop 1: revenue -9.09% (not flagged), noi -14.29% and $100k. Prop 4: opex +10% / $30k, and
    # the same $30k lands on NOI (-10%). Properties are ordered by size of NOI variance.
    assert got == [("Prop 1", "noi"), ("Prop 4", "opex"), ("Prop 4", "noi")]
    assert all(f.property_id in (1, 4) for f in r.flags) and r.totals[2].flagged is False


def test_property_scope_reports_only_that_property():
    r = compute_report([ROWS[0]], MONTH, property_id=1, flag_pct=D(10), flag_min_usd=D(25000))
    assert r.scope == "property" and r.property_name == "Prop 1" and r.n_properties == 1
    assert len(r.drivers) == 1 and r.drivers[0].noi_contribution_pct == D("100.00")
    assert [(f.property_id, f.line) for f in r.flags] == [(1, "noi")]


def test_no_rows_is_a_report_error():
    with pytest.raises(ReportError):
        compute_report([], MONTH)


def test_thresholds_default_from_settings_and_are_echoed():
    r = compute_report(ROWS, MONTH)
    assert r.flag_pct == D(10) and r.flag_min_usd == D(25000)


# ---- template and commentary checking --------------------------------------------------------

def report(rows=ROWS, pid=None):
    return compute_report(rows, MONTH, pid, flag_pct=D(10), flag_min_usd=D(25000))


@pytest.mark.parametrize("rep", [
    report(), report([ROWS[0]], 1), report([ROWS[2]], 3),
    report([row(1, "0", "0", "0", "0")]),
])
def test_template_is_always_grounded(rep):
    t = template_commentary(rep)
    assert ungrounded_numbers(t, rep) == []
    assert "June 2026" in t and "not available in the data" in t


def test_template_names_flagged_items_and_directions():
    t = template_commentary(report())
    assert "need human review" in t and "Prop 1" in t and "Prop 4" in t
    assert "unfavorable" in t and "below budget" in t and "above budget" in t


def test_pool_accepts_rounded_and_reformatted_numbers_but_not_invented_ones():
    pool = tables_record(report())
    rep = report()
    ok = "NOI was $1.37M, about $120K or 8.05% below the $1.49M budget; 3 items are flagged."
    assert ungrounded_numbers(ok, rep) == []
    assert ungrounded_numbers("NOI missed by $150,000.", rep) == ["150,000"]
    assert ungrounded_numbers("Growth was 12.7%.", rep) == ["12.7%"]
    assert pool.rows  # the pool is built from the report tables


class Capture(FakeClient):
    pass


def client_with(*texts, stop_reason="end_turn"):
    return Capture(*[response(text(t), stop_reason=stop_reason) for t in texts])


GOOD = "NOI was $1.37M against a $1.49M budget, 8.05% below, with 3 items flagged for review."
BAD = "NOI was $1.37M, which is $2.5M worse than last year."


def test_grounded_draft_is_accepted(audit_log):
    rep = report()
    c = client_with(GOOD)
    attach_commentary(rep, client=c, session_id="s")
    assert rep.commentary == GOOD and rep.commentary_source == "llm" and rep.commentary_note is None
    call = c.calls[0]
    assert "tools" not in call and call["system"] and "Prop 1" in call["messages"][0]["content"]
    assert "commentary" not in call["messages"][0]["content"]  # the draft never sees old text
    ev = audit_log[-1]
    assert ev["action"] == "variance_commentary" and ev["session_id"] == "s"
    assert ev["detail"]["source"] == "llm" and ev["detail"]["attempts"] == 1


def test_ungrounded_draft_gets_one_retry_then_is_accepted(audit_log):
    rep = report()
    c = client_with(BAD, GOOD)
    attach_commentary(rep, client=c)
    assert rep.commentary == GOOD and rep.commentary_source == "llm"
    retry = c.calls[1]["messages"]
    assert retry[1]["role"] == "assistant" and "do not appear" in retry[2]["content"]
    assert "2.5M" in retry[2]["content"]
    d = audit_log[-1]["detail"]
    assert d["attempts"] == 2 and d["ungrounded_first_attempt"] == ["2.5M"]


def test_still_ungrounded_falls_back_to_template(audit_log):
    rep = report()
    attach_commentary(rep, client=client_with(BAD, BAD))
    assert rep.commentary_source == "template" and "$2.5M" not in rep.commentary
    assert "not in the report tables" in rep.commentary_note
    assert ungrounded_numbers(rep.commentary, rep) == []


def test_missing_key_falls_back_to_template(audit_log, monkeypatch):
    def no_key():
        raise AgentConfigError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(variance_commentary, "build_client", no_key)
    rep = report()
    attach_commentary(rep)
    assert rep.commentary_source == "template" and "AgentConfigError" in rep.commentary_note


def test_api_error_falls_back_to_template(audit_log):
    class Boom:
        class messages:
            @staticmethod
            def create(**kw):
                raise anthropic.APIConnectionError(
                    request=httpx.Request("POST", "https://api.anthropic.com"))

    rep = report()
    attach_commentary(rep, client=Boom())
    assert rep.commentary_source == "template" and "APIConnectionError" in rep.commentary_note


def test_truncated_draft_falls_back_to_template(audit_log):
    rep = report()
    attach_commentary(rep, client=client_with(GOOD, stop_reason="max_tokens"))
    assert rep.commentary_source == "template" and "max_tokens" in rep.commentary_note


# ---- build_report + endpoints ----------------------------------------------------------------

def test_build_report_unknown_month_or_property(monkeypatch, audit_log):
    monkeypatch.setattr(variance, "fetch_rows", lambda m, p=None: [])
    with pytest.raises(ReportError, match="property 99"):
        variance.build_report(MONTH, 99, commentary=False)


def test_build_report_normalises_month_audits_and_skips_commentary(monkeypatch, audit_log):
    seen = {}
    monkeypatch.setattr(variance, "fetch_rows", lambda m, p=None: seen.update(m=m) or ROWS)
    rep = variance.build_report(date(2026, 6, 17), commentary=False, session_id="s9")
    assert seen["m"] == MONTH and rep.commentary is None
    assert audit_log[-1]["action"] == "variance_report" and audit_log[-1]["session_id"] == "s9"


@pytest.fixture
def client():
    return TestClient(api.app)


def test_variance_endpoint_returns_decimals_as_exact_strings(client, monkeypatch, audit_log):
    monkeypatch.setattr(variance, "fetch_rows", lambda m, p=None: ROWS)
    r = client.post("/variance", json={"month": "2026-06", "commentary": False})
    assert r.status_code == 200
    body = r.json()
    assert body["totals"][2]["variance"] == "-120000.00" and body["totals"][2]["variance_pct"] == "-8.05"
    assert (body["flags"][0]["name"], body["flags"][0]["line"]) == ("Prop 1", "noi")
    assert body["commentary"] is None and body["month"] == "2026-06-01"


@pytest.mark.parametrize("month", ["", "june", "2026", "2026-13", "x-y"])
def test_variance_endpoint_rejects_bad_month(client, month):
    assert client.post("/variance", json={"month": month}).status_code == 422


def test_variance_endpoint_404_for_no_data(client, monkeypatch, audit_log):
    monkeypatch.setattr(variance, "fetch_rows", lambda m, p=None: [])
    r = client.post("/variance", json={"month": "2031-01", "commentary": False})
    assert r.status_code == 404 and "2031-01" in r.json()["detail"]


def test_variance_options_endpoint(client, monkeypatch):
    monkeypatch.setattr(variance, "options", lambda: {"months": [MONTH], "properties": []})
    assert client.get("/variance/options").json() == {"months": ["2026-06-01"], "properties": []}
