"""Agent loop tests with a scripted fake Anthropic client. No network, no database."""

import json
from datetime import date

import pytest

from asset_copilot import agent
from asset_copilot.config import settings
from asset_copilot.db import QueryExecutionError
from fakes import FakeClient, response, text, tool_use


def submit(id_="s1", status="answered", answer="x", query_ids=("Q1",), calc_ids=()):
    return tool_use(id_, "submit_answer", status=status, answer=answer,
                    query_ids=list(query_ids), calc_ids=list(calc_ids))


def sql(id_, query):
    return tool_use(id_, "run_sql", sql=query, purpose="test")


def run(client, question="How many properties?", sid="sess-1"):
    return agent.run_agent(question, sid, client=client)


def actions(audit_log):
    return [e["action"] for e in audit_log]


def tool_results(client, call_index):
    """The tool_result blocks the agent sent to the model on call number `call_index`."""
    last = client.calls[call_index]["messages"][-1]
    assert last["role"] == "user" and isinstance(last["content"], list)
    return last["content"]


def test_happy_path_with_calculate_and_citations(fake_db, audit_log):
    fake_db.rows = [{"actual": "1100000", "budget": "1000000"}]
    client = FakeClient(
        response(sql("t1", "SELECT 1100000 AS actual, 1000000 AS budget FROM properties")),
        response(tool_use("t2", "calculate", expression="(1100000 - 1000000) / 1000000 * 100",
                          label="variance pct")),
        response(submit(answer="Actual was 1100000 vs budget 1000000, a 10% variance [Q1][C1].",
                        calc_ids=["C1"])),
    )
    out = run(client)

    assert out.status == "answered" and out.grounded and out.steps == 3
    assert [(c.kind, c.label) for c in out.citations] == [("sql", "Q1"), ("calculation", "C1")]
    assert out.citations[0].reference.endswith("LIMIT 500")  # executed SQL, not the draft
    assert out.citations[1].reference == "C1: (1100000 - 1000000) / 1000000 * 100 = 10"
    assert out.usage["input_tokens"] == 300 and out.usage["output_tokens"] == 60
    assert out.session_id == "sess-1"
    assert actions(audit_log) == [
        "ask_received", "model_call", "tool_call",
        "model_call", "tool_call",
        "model_call", "grounding_check", "tool_call", "answer_final",
    ]
    assert {e["session_id"] for e in audit_log} == {"sess-1"}


def test_request_shape(fake_db, audit_log):
    client = FakeClient(response(sql("t1", "SELECT 1 FROM properties")),
                        response(submit(answer="One row [Q1].")))
    run(client)
    call = client.calls[0]
    assert call["model"] == settings.anthropic_model
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert settings.as_of_date.isoformat() in call["system"][0]["text"]
    assert {t["name"] for t in call["tools"]} == {"run_sql", "calculate", "submit_answer"}
    # claude-sonnet-5-5 rejects non-default sampling params and forced tool_choice.
    assert "temperature" not in call and "tool_choice" not in call


def test_unsafe_sql_blocked_error_fed_back_then_recovers(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(
        response(sql("t1", "DROP TABLE properties")),
        response(sql("t2", "SELECT COUNT(*) AS n FROM properties")),
        response(submit(answer="There are 60 properties [Q1].")),
    )
    out = run(client)
    first = tool_results(client, 1)[0]
    assert first["is_error"] is True and "blocked by policy" in first["content"]
    assert len(fake_db.executed) == 1 and "DROP" not in fake_db.executed[0]
    assert out.status == "answered" and out.citations[0].label == "Q1"  # blocked query got no id


def test_db_error_fed_back_and_retried(fake_db, audit_log):
    fake_db.fail_with = QueryExecutionError('column "nope" does not exist')
    client = FakeClient(
        response(sql("t1", "SELECT nope FROM properties")),
        response(submit(status="cannot_determine", query_ids=[], answer="no such column")),
    )
    out = run(client)
    assert 'column \\"nope\\" does not exist' in tool_results(client, 1)[0]["content"]
    assert out.status == "cannot_determine"


def test_iteration_cap_returns_clear_failure(fake_db, audit_log, monkeypatch):
    monkeypatch.setattr(settings, "max_iterations", 3)
    client = FakeClient(*[response(sql(f"t{i}", "SELECT 1 FROM properties")) for i in range(3)])
    out = run(client)
    assert out.status == "failed" and not out.grounded and out.steps == 3
    assert out.answer == "I couldn't complete this within 3 steps."
    assert actions(audit_log)[-1] == "answer_final"
    assert audit_log[-1]["detail"]["reason"] == "max_iterations"


def test_too_many_sql_errors_stops_early(fake_db, audit_log, monkeypatch):
    monkeypatch.setattr(settings, "max_sql_errors", 2)
    client = FakeClient(*[response(sql(f"t{i}", "DELETE FROM leases")) for i in range(5)])
    out = run(client)
    assert out.status == "failed" and out.steps == 2
    assert audit_log[-1]["detail"]["reason"] == "too_many_sql_errors"


def test_hallucinated_number_triggers_one_correction_then_succeeds(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(
        response(sql("t1", "SELECT COUNT(*) AS n FROM properties")),
        response(submit("s1", answer="There are 75 properties [Q1].")),
        response(submit("s2", answer="There are 60 properties [Q1].")),
    )
    out = run(client)
    err = tool_results(client, 2)[0]
    assert err["is_error"] and "75" in err["content"] and "do not appear" in err["content"]
    assert out.status == "answered" and out.grounded is True


def test_hallucinated_number_twice_returns_ungrounded(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(
        response(sql("t1", "SELECT COUNT(*) AS n FROM properties")),
        response(submit("s1", answer="There are 75 properties [Q1].")),
        response(submit("s2", answer="There are 75 properties [Q1].")),
    )
    out = run(client)
    assert out.status == "answered" and out.grounded is False and out.steps == 3
    checks = [e["detail"] for e in audit_log if e["action"] == "grounding_check"]
    assert [c["ungrounded"] for c in checks] == [["75"], ["75"]]
    assert audit_log[-1]["detail"]["grounded"] is False


def test_fabricated_query_id_rejected(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(
        response(sql("t1", "SELECT COUNT(*) AS n FROM properties")),
        response(submit("s1", answer="There are 60 [Q9].", query_ids=["Q9"])),
        response(submit("s2", answer="There are 60 [Q1].", query_ids=["Q1"])),
    )
    out = run(client)
    err = tool_results(client, 2)[0]
    assert err["is_error"] and "Unknown ids: ['Q9']" in err["content"] and "Q1" in err["content"]
    assert out.status == "answered" and [c.label for c in out.citations] == ["Q1"]


def test_answered_without_any_citation_rejected(fake_db, audit_log):
    client = FakeClient(
        response(submit("s1", answer="It is 60.", query_ids=[])),
        response(submit("s2", status="cannot_determine", answer="No data.", query_ids=[])),
    )
    out = run(client)
    assert "at least one query_id" in tool_results(client, 1)[0]["content"]
    assert out.status == "cannot_determine"


def test_cannot_determine_gets_standard_prefix_and_no_citations(audit_log):
    client = FakeClient(response(submit(status="cannot_determine", query_ids=[],
                                        answer="Forecasts are not in the database.")))
    out = run(client)
    assert out.status == "cannot_determine" and out.citations == [] and out.grounded
    assert out.answer == "I can't determine that from the data. Forecasts are not in the database."


def test_cannot_determine_prefix_not_duplicated(audit_log):
    client = FakeClient(response(submit(
        status="cannot_determine", query_ids=[],
        answer="I can't determine that from the data. No forecasts.")))
    assert run(client).answer.count("I can't determine") == 1


def test_multiple_tool_calls_in_one_turn_all_answered_in_one_message(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(
        response(sql("t1", "SELECT COUNT(*) AS n FROM properties"),
                 tool_use("t2", "calculate", expression="60 * 2", label="double")),
        response(submit(answer="60 properties, doubled is 120 [Q1][C1].", calc_ids=["C1"])),
    )
    out = run(client)
    results = tool_results(client, 1)
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert out.status == "answered" and out.grounded


def test_submit_alongside_other_tools_is_rejected(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(
        response(sql("t1", "SELECT COUNT(*) AS n FROM properties"),
                 submit("s1", answer="There are 60 [Q1].")),
        response(submit("s2", answer="There are 60 [Q1].")),
    )
    out = run(client)
    results = tool_results(client, 1)
    assert not results[0]["is_error"] and results[1]["is_error"]
    assert "on its own" in results[1]["content"]
    assert out.status == "answered" and out.steps == 2


def test_no_tool_call_is_nudged_once_then_recovers(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(
        response(sql("t1", "SELECT COUNT(*) AS n FROM properties")),
        response(text("There are 60 properties.")),
        response(submit(answer="There are 60 properties [Q1].")),
    )
    out = run(client)
    assert client.calls[2]["messages"][-1] == {"role": "user", "content": agent.SUBMIT_NUDGE}
    assert out.status == "answered"


def test_no_tool_call_twice_fails(audit_log):
    out = run(FakeClient(response(text("hi")), response(text("hi again"))))
    assert out.status == "failed" and audit_log[-1]["detail"]["reason"] == "no_submit"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refusal_and_truncation_fail_safely(audit_log, stop_reason):
    out = run(FakeClient(response(text("..."), stop_reason=stop_reason)))
    assert out.status == "failed" and out.citations == []
    assert audit_log[-1]["detail"]["reason"] == stop_reason


def test_unknown_tool_returns_error_result(audit_log):
    client = FakeClient(
        response(tool_use("t1", "drop_everything", x=1)),
        response(submit(status="cannot_determine", query_ids=[], answer="n/a")),
    )
    run(client)
    assert "Unknown tool" in tool_results(client, 1)[0]["content"]


def test_assistant_content_is_passed_back_unchanged(fake_db, audit_log):
    first = response(sql("t1", "SELECT 1 FROM properties"))
    client = FakeClient(first, response(submit(answer="One row [Q1].")))
    run(client)
    assistant = client.calls[1]["messages"][1]
    assert assistant["role"] == "assistant" and assistant["content"] is first.content


def test_sdk_error_is_audited_and_reraised(audit_log):
    class Boom:
        class messages:
            @staticmethod
            def create(**_):
                raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError):
        agent.run_agent("q", "sess-x", client=Boom())
    assert audit_log[-1]["action"] == "agent_error"
    assert audit_log[-1]["detail"]["error"] == "upstream down"


def test_session_id_generated_when_missing(audit_log):
    client = FakeClient(response(submit(status="cannot_determine", query_ids=[], answer="n/a")))
    out = agent.run_agent("q", None, client=client)
    assert out.session_id and {e["session_id"] for e in audit_log} == {out.session_id}


def test_missing_api_key_raises_config_error(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(agent.AgentConfigError):
        agent.build_client()


def test_tool_result_payloads_are_valid_json(fake_db, audit_log):
    fake_db.rows = [{"n": 60}]
    client = FakeClient(response(sql("t1", "SELECT COUNT(*) AS n FROM properties")),
                        response(submit(answer="There are 60 [Q1].")))
    run(client)
    payload = json.loads(tool_results(client, 1)[0]["content"])
    assert payload["query_id"] == "Q1" and payload["rows"] == [{"n": 60}]


def test_prompt_pins_as_of_date():
    from asset_copilot.prompts import build_system_prompt

    p = build_system_prompt(date(2026, 6, 30))
    assert "AS_OF date (treat this as today): 2026-06-30" in p
    assert "DATE '2026-06-30'" in p
