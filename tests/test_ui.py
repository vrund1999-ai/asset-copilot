"""UI logic tests with Streamlit's AppTest (no browser, no API, no database)."""

import sys
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parent.parent / "app"
sys.path.insert(0, str(APP))  # the app imports `ui_common` as a top-level module

import ui_common
from answer_view import source_card, tables_in, turn_state
from variance_view import driver_rows, flag_rows, totals_rows, trend_rows

SUMMARY = {
    "month": "2026-06-01", "n_properties": 60, "n_active_leases": 459, "n_expiring_12m": 211,
    "n_documents": 55, "n_flags": 14, "flag_pct": "10", "flag_min_usd": "25000",
    "totals": [
        {"line": "revenue", "actual": "51185829.67", "budget": "52256268.02",
         "variance": "-1070438.35", "variance_pct": "-2.05", "favorable": False, "flagged": False},
        {"line": "opex", "actual": "22440236.47", "budget": "21891723.47",
         "variance": "548513.00", "variance_pct": "2.51", "favorable": False, "flagged": False},
        {"line": "noi", "actual": "28745593.20", "budget": "30364544.55",
         "variance": "-1618951.35", "variance_pct": "-5.33", "favorable": False, "flagged": False},
    ],
}


@pytest.fixture(autouse=True)
def clear_caches():
    ui_common.api_status.clear()
    ui_common.portfolio_summary.clear()
    yield
    ui_common.api_status.clear()
    ui_common.portfolio_summary.clear()


def fake_get(health_ok=True, summary=SUMMARY):
    def get(url, **_):
        req = httpx.Request("GET", url)
        if not health_ok:
            raise httpx.ConnectError("refused", request=req)
        if url.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"}, request=req)
        if url.endswith("/portfolio/summary"):
            return httpx.Response(200, json=summary, request=req)
        return httpx.Response(404, json={"detail": "not found"}, request=req)

    return get


def home(monkeypatch, **kw):
    monkeypatch.setattr(httpx, "get", fake_get(**kw))
    return AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=20).run()


def test_home_shows_snapshot_numbers(monkeypatch):
    at = home(monkeypatch)
    assert not at.exception
    metrics = {m.label: (m.value, m.delta) for m in at.metric}
    assert metrics["Properties"][0] == "60"
    assert metrics["Active leases"][0] == "459"
    assert metrics["Items flagged for review"][0] == "14"
    assert metrics["Revenue vs budget"] == ("$51,185,830", "-2.05%")
    assert metrics["Operating expenses vs budget"][1] == "+2.51%"
    assert metrics["NOI vs budget"] == ("$28,745,593", "-5.33%")


def test_home_hides_snapshot_when_api_is_down(monkeypatch):
    at = home(monkeypatch, health_ok=False)
    assert not at.exception
    assert not at.metric  # no numbers, cached or otherwise
    assert any("snapshot is unavailable" in w.value for w in at.warning)


def test_home_sample_questions_are_buttons(monkeypatch):
    at = home(monkeypatch)
    labels = [b.label for b in at.button]
    assert "Which 5 cities have the most properties?" in labels and len(labels) == 4


def test_reviewer_view_adds_how_answers_are_checked(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get())
    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=20)
    at.session_state["_view"] = "Reviewer"
    at.run()
    assert any(s.value == "How answers are checked" for s in at.subheader)
    at2 = home(monkeypatch)  # default view
    assert not any(s.value == "How answers are checked" for s in at2.subheader)


def toggle_app():
    import streamlit as st
    from ui_common import current_view, view_toggle

    view_toggle()
    st.write(f"view={current_view()}")


def test_view_defaults_to_asset_manager():
    at = AppTest.from_function(toggle_app, default_timeout=20).run()
    assert at.radio[0].value == "Asset manager" and at.markdown[-1].value == "view=Asset manager"


def test_view_read_from_query_string_and_written_back():
    at = AppTest.from_function(toggle_app, default_timeout=20)
    at.query_params["view"] = "analyst"
    at.run()
    assert at.radio[0].value == "Analyst"
    assert at.query_params["view"] == ["analyst"] or at.query_params["view"] == "analyst"


def test_view_choice_is_stored_outside_the_widget():
    """st.switch_page drops widget state, so the choice must live under its own session key."""
    at = AppTest.from_function(toggle_app, default_timeout=20).run()
    at.radio[0].set_value("Reviewer").run()
    assert at.session_state["_view"] == "Reviewer"
    assert at.markdown[-1].value == "view=Reviewer"
    assert at.radio[0].key is None  # not bound to the stored value


def test_unknown_view_falls_back_to_default():
    def app():
        import streamlit as st
        from ui_common import current_view

        st.session_state["_view"] = "Nonsense"
        st.write(current_view())

    at = AppTest.from_function(app, default_timeout=20).run()
    assert at.markdown[0].value == "Asset manager"


# ---- Ask page: states, source cards, one-click feedback --------------------------------------

def turn_app():
    import streamlit as st
    from answer_view import render_turn

    st.session_state.setdefault("_view", st.session_state.get("want_view", "Asset manager"))
    render_turn(st.session_state["turn"], 0)


def render(turn, view="Asset manager", posts=None, monkeypatch=None):
    if monkeypatch is not None:
        def post(url, **kw):
            posts.append(kw["json"])
            return httpx.Response(200, json={"status": "saved"}, request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx, "post", post)
    at = AppTest.from_function(turn_app, default_timeout=20)
    at.session_state["turn"] = turn
    at.session_state["_view"] = view
    return at.run()


SQL = "SELECT city, count(*) FROM properties p JOIN leases l ON l.property_id = p.id GROUP BY city"
ANSWERED = {"content": "Austin has 9 properties.", "status": "answered", "grounded": True,
            "question": "q", "steps": 3, "session_id": "abcdef123456",
            "citations": [{"kind": "sql", "label": "Q1", "reference": SQL},
                          {"kind": "document", "label": "D1", "reference": "Lease 12 p.2"},
                          {"kind": "calculation", "label": "C1", "reference": "C1: 2 + 2 = 4"}]}


def test_turn_state_covers_every_status():
    assert turn_state(ANSWERED) == "answered"
    assert turn_state({**ANSWERED, "grounded": False}) == "ungrounded"
    assert turn_state({"status": "cannot_determine"}) == "cannot_determine"
    assert turn_state({"status": "failed"}) == "failed"
    assert turn_state({"status": "error"}) == "error"


def test_tables_in_and_source_cards():
    assert tables_in(SQL) == ["properties", "leases"]
    assert tables_in("select 1") == []
    sql, doc, calc = (source_card(c) for c in ANSWERED["citations"])
    assert sql["title"] == "Database query Q1" and sql["detail"] == "Read from: properties, leases"
    assert sql["language"] == "sql" and sql["code"] == SQL
    assert doc["title"] == "Lease 12 p.2" and doc["code"] is None
    assert calc["title"] == "Calculation C1" and calc["code"] == "C1: 2 + 2 = 4"


def test_answered_turn_leads_with_the_answer_and_collapses_sources():
    at = render(ANSWERED)
    assert not at.exception
    assert at.markdown[0].value == "Austin has 9 properties."
    assert any("Every number traced" in c.value for c in at.caption)
    assert not at.warning and not at.error
    assert at.expander[0].label == "Sources (3)" and not at.expander[0].proto.expanded


def test_analyst_view_opens_sources_and_adds_run_details():
    at = render(ANSWERED, view="Analyst")
    assert at.expander[0].proto.expanded
    assert any("3 model calls · session abcdef12" in c.value for c in at.caption)
    assert not any("Checks applied" in c.value for c in at.caption)


def test_reviewer_view_explains_the_checks():
    at = render(ANSWERED, view="Reviewer")
    assert any("Checks applied" in c.value and "abcdef12" in c.value for c in at.caption)


def test_ungrounded_turn_warns_before_the_text():
    at = render({**ANSWERED, "grounded": False})
    assert at.warning and "Not fully verified" in at.warning[0].value
    assert not any("Every number traced" in c.value for c in at.caption)


def test_refused_failed_and_error_turns_are_distinct():
    refused = render({"content": "I can't determine that.", "status": "cannot_determine"})
    assert refused.info and not refused.error and not refused.warning
    assert not refused.expander  # no sources, nothing to rate-limit the reader
    failed = render({"content": "Gave up after 8 steps.", "status": "failed"})
    assert failed.error and "could not finish" in failed.error[0].value
    assert not [b for b in failed.button]  # nothing to rate
    err = render({"content": "Could not reach the API", "status": "error", "question": "q"})
    assert err.error and "did not respond" in err.error[0].value
    assert [b.label for b in err.button] == ["Try again"]


def test_thumbs_down_saves_on_one_click_then_takes_an_optional_note(monkeypatch):
    posts: list[dict] = []
    at = render(ANSWERED, posts=posts, monkeypatch=monkeypatch)
    assert [b.label for b in at.button] == ["👍 Helpful", "👎 Not helpful"]
    at.button[1].click().run()
    assert len(posts) == 1 and posts[0]["rating"] == -1 and posts[0]["correction"] is None
    assert [c.value for c in at.caption if "rating was saved" in c.value]
    at.text_input[0].set_value("Austin has 10").run()
    at.button[0].click().run()
    assert len(posts) == 2 and posts[1]["correction"] == "Austin has 10" and posts[1]["rating"] == -1
    assert any("feedback was saved" in c.value for c in at.caption)
    assert not at.button  # done: nothing left to click


def test_thumbs_up_is_a_single_click(monkeypatch):
    posts: list[dict] = []
    at = render(ANSWERED, posts=posts, monkeypatch=monkeypatch)
    at.button[0].click().run()
    assert [p["rating"] for p in posts] == [1]
    assert not any("What was wrong" in c.value for c in at.caption)


def test_feedback_failure_is_reported_and_can_be_retried(monkeypatch):
    def boom(url, **_):
        raise httpx.ConnectError("refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", boom)
    at = render(ANSWERED)
    at.button[0].click().run()
    assert at.error and "Could not reach the API" in at.error[0].value
    assert [b.label for b in at.button] == ["👍 Helpful", "👎 Not helpful"]


# ---- Variance report: flagged first, numeric sortable rows, drill-down -----------------------

def _line(line, actual, budget, variance, pct, flagged=False):
    return {"line": line, "actual": actual, "budget": budget, "variance": variance,
            "variance_pct": pct, "favorable": variance.startswith("-") is False, "flagged": flagged}


def _totals(scale=1):
    return [_line("revenue", "1000.00", "900.00", "100.00", "11.11", True),
            _line("opex", "400.00", "450.00", "-50.00", "-11.11"),
            _line("noi", "600.00", "450.00", "150.00", "33.33", True)]


REPORT = {
    "scope": "portfolio", "property_id": None, "property_name": None, "month": "2026-06-01",
    "n_properties": 2, "totals": _totals(), "flag_pct": "10", "flag_min_usd": "25000",
    "drivers": [{"property_id": 7, "name": "Harbor Plaza", "asset_type": "office",
                 "noi_contribution_pct": "60.00", "lines": _totals()}],
    "flags": [{"property_id": 8, "name": "Elm Court", "line": "opex", "variance": "-30000",
               "variance_pct": "-12.5"},
              {"property_id": 7, "name": "Harbor Plaza", "line": "revenue", "variance": "90000.50",
               "variance_pct": "15"},
              {"property_id": None, "name": "Portfolio", "line": "noi", "variance": "5000",
               "variance_pct": "11"}],
    "commentary": "NOI is ahead of budget.", "commentary_source": "llm", "commentary_note": None,
}


def test_variance_rows_are_numeric_and_flags_sorted_by_size():
    flags = flag_rows(REPORT)
    assert [f["Item"] for f in flags] == ["Harbor Plaza", "Elm Court", "Portfolio"]
    assert flags[0]["Variance ($)"] == 90000.5 and isinstance(flags[0]["Variance (%)"], float)
    t = totals_rows(REPORT)
    assert [r["Result"] for r in t] == ["Favorable", "Unfavorable", "Favorable"]
    assert driver_rows(REPORT)[0]["NOI variance ($)"] == 150.0
    tr = trend_rows([("2026-06", REPORT)])
    assert tr[0]["NOI ($)"] == 600.0 and tr[0]["NOI vs budget (%)"] == 33.33


def variance_page(monkeypatch, report=REPORT, view="Asset manager"):
    def get(url, **_):
        req = httpx.Request("GET", url)
        return httpx.Response(200, request=req, json={
            "months": ["2026-06-01", "2026-05-01", "2026-04-01"],
            "properties": [{"property_id": 7, "name": "Harbor Plaza"},
                           {"property_id": 8, "name": "Elm Court"}]})

    def post(url, **kw):
        rep = dict(report)
        if kw["json"].get("property_id"):
            rep = {**rep, "scope": "property", "property_id": kw["json"]["property_id"]}
        return httpx.Response(200, json=rep, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    ui_common.api_status.clear()
    at = AppTest.from_file(str(APP / "screens" / "variance_report.py"), default_timeout=30)
    at.session_state["_view"] = view
    return at.run()


def test_variance_page_orders_flags_then_commentary_then_tables(monkeypatch):
    at = variance_page(monkeypatch)
    at.button[0].click().run()
    assert not at.exception
    heads = [h.value for h in at.subheader]
    assert heads[1:] == ["Flagged for review (3)", "Commentary"]
    assert [e.label for e in at.expander] == ["Full tables"] and not at.expander[0].proto.expanded


def test_variance_analyst_view_opens_full_tables(monkeypatch):
    at = variance_page(monkeypatch, view="Analyst")
    at.button[0].click().run()
    assert at.expander[0].proto.expanded


def test_variance_reviewer_sees_commentary_check(monkeypatch):
    at = variance_page(monkeypatch, view="Reviewer")
    at.button[0].click().run()
    assert any("Check applied" in c.value for c in at.caption)


def test_variance_no_flags_shows_clear_state(monkeypatch):
    at = variance_page(monkeypatch, report={**REPORT, "flags": []})
    at.button[0].click().run()
    assert at.success and "No items exceed" in at.success[0].value
    assert any(h.value == "Flagged for review (0)" for h in at.subheader)


def test_variance_open_property_callback_sets_pickers(monkeypatch):
    at = variance_page(monkeypatch)
    at.button[0].click().run()
    assert at.selectbox[0].value == "Entire portfolio"
    at.session_state["scope_sel"] = "Harbor Plaza"
    at.session_state["month_sel"] = "2026-05-01"
    at.session_state["auto_generate"] = True
    at.run()
    assert not at.exception
    assert at.session_state["variance"]["scope"] == "Harbor Plaza"
    assert at.session_state["variance"]["month"] == "2026-05-01"


# ---- Document citations show the supporting passage ------------------------------------------

DOC = {"kind": "document", "label": "D1", "reference": "Lease Abstract p.2",
       "excerpt": "## Renewal Options\n\n2 option(s) at 95% of *fair market* rent."}


def test_document_card_carries_excerpt():
    card = source_card(DOC)
    assert card["title"] == "Lease Abstract p.2" and card["excerpt"].startswith("## Renewal")
    assert source_card({**DOC, "excerpt": None})["excerpt"] is None


def test_quote_escapes_markdown_and_keeps_blank_lines():
    from answer_view import quote

    out = quote("## Heading\n\n*bold* <b>x</b> $5")
    assert out.splitlines() == ["> \\#\\# Heading", ">", "> \\*bold\\* \\<b\\>x\\</b\\> \\$5"]


def test_document_source_shows_passage_text_in_the_expander():
    turn = {**ANSWERED, "citations": [DOC]}
    at = render(turn, view="Analyst")
    assert not at.exception
    assert any("fair market" in m.value for m in at.markdown)
    assert any("passage that was cited" in c.value for c in at.caption)


def test_document_source_without_excerpt_says_so():
    at = render({**ANSWERED, "citations": [{**DOC, "excerpt": None}]}, view="Analyst")
    assert any("passage text was not returned" in c.value for c in at.caption)
