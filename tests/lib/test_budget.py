"""Ceilings, the efficiency table, and what a rate limit actually means."""

from __future__ import annotations

import json

import pytest
from agent_sdk_skills.budget import (
    STATUS_FAILED,
    STATUS_INFORMATIONAL,
    STATUS_NOT_EVALUATED,
    STATUS_PASSED,
    budget_findings,
    check_budget,
    cost_basis_is_list,
    cost_label,
    efficiency_rows,
    efficiency_table,
    model_thinking_tokens,
    model_usage_of,
    models_billed,
    rate_limit_summary,
    rate_limit_verdict,
    total_cost,
    total_tokens,
    usage_limit_from_result,
    usage_of,
)
from agent_sdk_skills.trace import load_trace, result_event


@pytest.fixture
def traces(fixtures):
    return fixtures / "traces"


@pytest.fixture
def results(fixtures):
    return fixtures / "results"


@pytest.fixture
def happy_result(traces):
    return result_event(load_trace(traces / "happy.trace.jsonl"))


def load_series(directory):
    return [json.loads(p.read_text()) for p in sorted(directory.glob("*.result.json"))]


# -- check_budget ----------------------------------------------------------

def test_a_run_inside_every_ceiling_passes(happy_result):
    verdict = check_budget(happy_result, {"max_turns": 6, "max_cost_usd": 0.25})
    assert verdict.status == STATUS_PASSED
    assert verdict.score == 1.0
    assert "within budget" in verdict.reason
    assert verdict.cost_basis == "subscription"


def test_a_run_over_a_ceiling_fails_and_names_the_numbers(happy_result):
    verdict = check_budget(happy_result, {"max_cost_usd": 0.001})
    assert verdict.status == STATUS_FAILED
    assert verdict.score == 0.0
    assert "max_cost_usd" in verdict.reason
    assert verdict.failures[0].observed == pytest.approx(0.0221836)


def test_the_score_is_the_fraction_of_ceilings_met(happy_result):
    verdict = check_budget(happy_result, {"max_turns": 6, "max_cost_usd": 0.001})
    assert verdict.score == 0.5


def test_no_result_event_means_not_evaluated_never_passed():
    """Imported session evidence carries no cost: a green tick would be a lie."""
    verdict = check_budget(None, {"max_cost_usd": 1.0})
    assert verdict.status == STATUS_NOT_EVALUATED
    assert "imported session" in verdict.reason


def test_a_grader_with_no_ceiling_has_nothing_to_compare(happy_result):
    assert check_budget(happy_result, {}).status == STATUS_NOT_EVALUATED


def test_an_informational_grader_records_without_failing(happy_result):
    verdict = check_budget(happy_result, {"max_cost_usd": 0.001}, informational=True)
    assert verdict.status == STATUS_INFORMATIONAL
    assert verdict.informational
    assert "informational" in verdict.reason


def test_informational_can_be_declared_in_the_grader(happy_result):
    verdict = check_budget(happy_result, {"max_cost_usd": 0.001, "informational": True})
    assert verdict.status == STATUS_INFORMATIONAL


def test_token_ceilings_read_the_measured_usage_keys(happy_result):
    verdict = check_budget(happy_result, {"max_input_tokens": 100,
                                          "max_output_tokens": 1000,
                                          "max_cache_read_tokens": 10000})
    assert verdict.status == STATUS_PASSED
    fields = {c.field for c in verdict.checks}
    assert fields == {"usage.input_tokens", "usage.output_tokens",
                      "usage.cache_read_input_tokens"}


def test_a_ceiling_with_no_value_in_the_result_is_reported_as_unmeasured():
    event = {"num_turns": 2, "usage": {}}
    verdict = check_budget(event, {"max_turns": 4, "max_input_tokens": 10})
    assert verdict.status == STATUS_PASSED
    assert "not measured: usage.input_tokens" in verdict.reason


def test_cache_creation_is_never_read_as_a_number():
    """It is a nested dict of ephemeral TTL buckets; comparing it would never fire."""
    event = {"usage": {"cache_creation": {"ephemeral_1h_input_tokens": 4620}}}
    verdict = check_budget(event, {"max_cache_creation_tokens": 10})
    assert verdict.status == STATUS_NOT_EVALUATED


def test_max_turns_is_the_graders_own_ceiling_not_a_check_on_the_option():
    """Measured: max_turns=1 produced num_turns=2 with subtype success."""
    event = {"num_turns": 2, "subtype": "success", "usage": {}}
    assert check_budget(event, {"max_turns": 1}).status == STATUS_FAILED
    assert check_budget(event, {"max_turns": 3}).status == STATUS_PASSED


def test_cost_is_the_case_total_not_a_sum_of_turns(traces):
    """`total_cost_usd` is a session running total, so summing double-counts."""
    event = result_event(load_trace(traces / "structured_output.trace.jsonl"))
    assert event.get("total_cost_usd") == pytest.approx(0.004991)
    assert check_budget(event, {"max_cost_usd": 0.004991}).status == STATUS_PASSED


def test_usage_of_defaults_missing_keys_to_zero():
    assert usage_of(None)["input_tokens"] == 0
    assert usage_of({"usage": {"input_tokens": 3}})["output_tokens"] == 0


def test_total_tokens_counts_cache_reads_too(happy_result):
    """Hiding cache reads makes a run loading 20k of ambient config look free."""
    assert total_tokens(happy_result) == 4 + 185 + 4418 + 4620


# -- rate limits and usage limits ------------------------------------------

@pytest.mark.parametrize("status,verdict", [
    ("allowed", "keep"),
    ("allowed_warning", "warn"),
    ("rejected", "stop"),
])
def test_only_a_rejected_status_stops_anything(status, verdict):
    assert rate_limit_verdict(status) == verdict


def test_an_unknown_status_warns_rather_than_guessing():
    assert rate_limit_verdict("something_new") == "warn"
    assert rate_limit_verdict(None) == "warn"


def test_a_warning_rate_limit_does_not_make_a_run_inconclusive(traces):
    """One fired on all three measured runs; treating it as a hit marks everything bad."""
    events = load_trace(traces / "happy.trace.jsonl")
    summary = rate_limit_summary(events)
    assert summary["status"] == "allowed_warning"
    assert summary["verdict"] == "warn"
    assert summary["windows"]["seven_day"]["utilization"] == 0.83
    assert summary["surpassed_threshold"] == 0.75


def test_a_rejected_rate_limit_stops_the_suite(traces):
    summary = rate_limit_summary(load_trace(traces / "rate_limited.trace.jsonl"))
    assert summary["status"] == "rejected"
    assert summary["verdict"] == "stop"


def test_no_rate_limit_events_returns_none():
    assert rate_limit_summary([]) is None


def test_a_429_is_recognised_as_a_usage_limit_with_certainty(traces):
    event = result_event(load_trace(traces / "rate_limited.trace.jsonl"))
    limit = usage_limit_from_result(event)
    assert limit is not None
    assert limit["confidence"] == "certain"
    assert limit["verdict"] == "stop"
    assert "NOT_EVALUATED" in limit["reason"]


def test_limit_wording_in_an_error_result_is_recognised_as_likely():
    """There is no SDK message type for this, so it has to be inferred."""
    event = {"is_error": True, "subtype": "error_during_execution",
             "result_text": "Claude usage limit reached. Your limit will reset at 6pm."}
    limit = usage_limit_from_result(event)
    assert limit["confidence"] == "likely"
    assert "inferred" in limit["reason"]


def test_an_ordinary_failure_is_not_a_usage_limit(happy_result):
    assert usage_limit_from_result(happy_result) is None
    assert usage_limit_from_result({"is_error": True, "result_text": "no such title"}) is None


def test_limit_wording_without_an_error_is_not_a_hit():
    """An agent that says the words has not hit anything."""
    assert usage_limit_from_result(
        {"is_error": False, "subtype": "success",
         "result_text": "your quota is fine"}) is None


# -- findings --------------------------------------------------------------

def test_a_turn_limit_produces_a_warning_that_reads_it_as_inconclusive(traces):
    findings = budget_findings(result_event(load_trace(traces / "max_turns.trace.jsonl")))
    assert [f.id for f in findings] == ["RES010"]
    assert findings[0].severity == "warn"
    assert "inconclusive" in findings[0].fix


def test_a_cost_ceiling_produces_its_own_finding(traces):
    findings = budget_findings(result_event(load_trace(traces / "budget_exceeded.trace.jsonl")))
    assert "RES020" in [f.id for f in findings]


def test_a_usage_limit_produces_a_finding(traces):
    findings = budget_findings(result_event(load_trace(traces / "rate_limited.trace.jsonl")))
    assert "RES011" in [f.id for f in findings]


def test_a_healthy_run_produces_no_finding(happy_result):
    assert budget_findings(happy_result) == []


# -- the efficiency table --------------------------------------------------

def test_the_efficiency_table_averages_each_cases_runs(results):
    rows = {row["case"]: row for row in efficiency_rows(load_series(results / "series_5run"))}
    assert rows["reserve-available"]["runs"] == 5
    assert rows["reserve-available"]["turns"] == 3
    assert rows["refuse-double-booking"]["turns"] == 4
    assert rows["reserve-available"]["cost_usd"] == pytest.approx(0.042)


def test_pass_rate_stays_a_separate_column_from_cost(results):
    """A failing run that ended early is the cheapest run there is."""
    rows = {row["case"]: row for row in efficiency_rows(load_series(results / "series_5run"))}
    assert rows["refuse-double-booking"]["pass_rate"] == 0.6
    assert rows["reserve-available"]["pass_rate"] == 1.0


def test_a_series_with_no_measured_runs_says_so(results):
    rows = efficiency_rows([{"case": "x", "runs": [{"run": 1, "status": "NOT_EVALUATED",
                                                    "graders": []}]}])
    assert rows[0]["note"].startswith("no measured runs")
    assert rows[0]["turns"] is None


def test_the_table_labels_a_subscription_estimate_honestly(results):
    table = efficiency_table(efficiency_rows(load_series(results / "series_5run")))
    assert "Lower is better" in table
    assert "nothing is billed" in table
    assert "| case | runs |" in table


def test_total_cost_reports_its_basis_and_what_is_missing(results):
    totals = total_cost(load_series(results / "series_5run"))
    assert totals["runs_counted"] == 15
    assert totals["runs_without_cost"] == 0
    assert totals["cost_basis"] == "subscription"
    assert "not billed" in totals["label"]


def test_a_cost_figure_without_its_basis_says_so():
    assert "basis unknown" in cost_label(0.1, None)
    assert "billed" in cost_label(0.1, "api_key")
    assert cost_label(None, "subscription") == "cost unknown"


# -- more than one model, and the cost basis -------------------------------

def test_a_measured_two_model_run_names_every_model_it_was_billed_for(fixtures):
    """CLI 2.1.294 billed Haiku 5.5 for its own background work, unasked (2026-10-11)."""
    result = result_event(load_trace(fixtures / "traces" / "two_models.trace.jsonl"))
    assert result is not None
    assert models_billed(result) == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    usage = model_usage_of(result)
    assert usage["claude-sonnet-5-5"]["costUSD"] > usage["claude-haiku-5-5"]["costUSD"]
    # The agent's own model is not the whole cost: the total is over both.
    assert result.get("total_cost_usd") > usage["claude-sonnet-5-5"]["costUSD"]


def test_the_cost_basis_is_read_with_get_so_an_absent_key_counts_as_list(fixtures):
    result = result_event(load_trace(fixtures / "traces" / "two_models.trace.jsonl"))
    assert cost_basis_is_list(result) is True
    assert cost_basis_is_list({"model_usage": {"m": {"costBasis": "managed"}}}) is False
    assert cost_basis_is_list({"model_usage": {"m": {}}}) is True, "absent means list"
    assert cost_basis_is_list({"model_usage": {}}) is None, "nothing billed, nothing known"
    assert cost_basis_is_list(None) is None


def test_undeclared_model_usage_keys_never_raise():
    """`costBasis` and `thinkingTokens` are on the wire but not on the TypedDict."""
    assert model_usage_of({"model_usage": "not a dict"}) == {}
    assert model_usage_of({"model_usage": {"m": "not a dict"}}) == {}
    assert model_thinking_tokens({"model_usage": {"a": {"thinkingTokens": 7},
                                                  "b": {}}}) == 7
    assert model_thinking_tokens({}) == 0


def test_the_efficiency_rows_carry_the_models_and_the_basis(fixtures):
    document = json.loads(
        (fixtures / "results" / "series_5run" / "reserve-available.result.json").read_text()
    )
    rows = efficiency_rows([document])
    assert "models_billed" in rows[0] and "cost_basis_list" in rows[0]


# -- is_error on a success subtype (Python SDK docs, Claude Code 2.1.310) ----

def test_a_refusal_with_limit_words_is_not_read_as_a_usage_limit(traces):
    """The fixture's refusal text says "quota"; `stop_reason` is read first."""
    result = result_event(load_trace(traces / "refusal_success.trace.jsonl"))
    assert result.get("is_error") is True and result.get("subtype") == "success"
    assert "quota" in result.get("result_text")
    assert usage_limit_from_result(result) is None


def test_a_refusal_gets_its_own_results_finding_not_an_error_one(traces):
    findings = budget_findings(result_event(load_trace(traces / "refusal_success.trace.jsonl")))
    assert [f.id for f in findings] == ["RES012"]
    assert findings[0].severity == "warn"
    assert "not an API error" in findings[0].message
    assert "stop_reason" in findings[0].source


def test_a_deferred_tool_missing_on_resume_is_its_own_finding():
    result = {"subtype": "success", "is_error": True, "stop_reason": "tool_deferred_unavailable",
              "terminal_reason": "completed", "result_text": "rate limit tool not available",
              "deferred_tool_use": {"id": "toolu_1", "name": "mcp__x__y", "input": {}}}
    assert usage_limit_from_result(result) is None
    assert [f.id for f in budget_findings(result)] == ["RES013"]


def test_an_error_in_place_of_a_response_still_reads_its_limit_wording():
    """Any other `stop_reason` with `is_error` on `success` is an error, as before."""
    result = {"subtype": "success", "is_error": True, "stop_reason": None,
              "terminal_reason": "api_error", "result_text": "API Error: usage limit reached"}
    assert usage_limit_from_result(result)["confidence"] == "likely"
    assert [f.id for f in budget_findings(result)] == ["RES011"]


# -- the documented "+1" rule for max_turns (2026-10-29) ----------------------

PLUS_ONE = "plus one for the final text-only response"


def test_a_one_tool_call_run_under_max_turns_1_names_the_plus_one_rule(traces):
    """Measured 2026-10-29 (CLI 2.1.310): one tool call under `max_turns=1` ends
    `error_max_turns` with `stop_reason "tool_use"`, `num_turns 2`, no final text."""
    result = result_event(load_trace(traces / "max_turns_one.trace.jsonl"))
    assert (result.data["subtype"], result.data["stop_reason"], result.data["num_turns"],
            result.data["result_text"]) == ("error_max_turns", "tool_use", 2, None)
    findings = budget_findings(result)
    assert [f.id for f in findings] == ["RES010"]
    assert findings[0].severity == "warn"
    assert PLUS_ONE in findings[0].fix and "error_max_turns" in findings[0].fix
    assert "agent-loop" in findings[0].source


def test_the_plus_one_sentence_is_the_documented_wording():
    from agent_sdk_skills.budget import MAX_TURNS_PLUS_ONE
    assert MAX_TURNS_PLUS_ONE.startswith("count each turn with tool calls plus one for the final "
                                         "text-only response; without that extra turn the run "
                                         "ends `error_max_turns` with no final response")
    assert "read 2026-10-29" in MAX_TURNS_PLUS_ONE


def test_a_budget_grader_on_the_one_tool_call_run_keeps_its_own_ceiling(traces):
    result = result_event(load_trace(traces / "max_turns_one.trace.jsonl"))
    assert check_budget(result, {"max_turns": 1}).status == STATUS_FAILED
    assert check_budget(result, {"max_turns": 2}).status == STATUS_PASSED
