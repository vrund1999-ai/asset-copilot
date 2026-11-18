"""UI logic tests with Streamlit's AppTest (no browser, no API, no database)."""

import sys
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parent.parent / "app"
sys.path.insert(0, str(APP))  # the app imports `ui_common` as a top-level module

import ui_common

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
