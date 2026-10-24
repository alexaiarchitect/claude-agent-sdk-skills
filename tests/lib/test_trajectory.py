"""Trajectory comparison, failure signatures and the quadrant."""

from __future__ import annotations

import pytest
from agent_sdk_skills.trace import load_trace
from agent_sdk_skills.trajectory import (
    ARGS_EXACT,
    ARGS_IGNORE,
    ARGS_SUBSET,
    DEFAULT_ARGS_MATCH,
    DEFAULT_MATCH,
    MATCH_ANY_ORDER,
    MATCH_EXACT,
    MATCH_IN_ORDER,
    Call,
    calls_from_events,
    cascade_suspect,
    detect_signatures,
    diff,
    expected_from_grader,
    quadrant,
    to_calls,
)

LOOKUP = "mcp__library__lookup_book"
RESERVE = "mcp__library__reserve_book"
CANCEL = "mcp__library__cancel_reservation"


@pytest.fixture
def traces(fixtures):
    return fixtures / "traces"


def kinds(signatures):
    return sorted(s.kind for s in signatures)


# -- Call and to_calls -----------------------------------------------------

def test_the_subagent_tool_is_normalized_to_one_name():
    assert Call(tool="Agent").tool == Call(tool="Task").tool


def test_a_synthetic_tool_is_recognised_even_without_the_flag():
    assert Call(tool="StructuredOutput").synthetic
    assert not Call(tool=RESERVE).synthetic


def test_to_calls_accepts_every_call_shaped_thing():
    calls = to_calls([
        Call(tool="a"),
        {"tool": "b", "args": {"x": 1}},
        {"name": "c", "input": {"y": 2}},        # the SDK's own spelling
        "d",
    ])
    assert [c.tool for c in calls] == ["a", "b", "c", "d"]
    assert calls[2].args == {"y": 2}


def test_synthetic_calls_are_dropped_unless_asked_for():
    raw = [{"tool": "StructuredOutput"}, {"tool": RESERVE}]
    assert [c.tool for c in to_calls(raw)] == [RESERVE]
    assert len(to_calls(raw, include_synthetic=True)) == 2


def test_a_call_renders_short_without_cutting_mid_value():
    call = Call(tool=RESERVE, args={"title": "Dune", "member_id": "member-42"})
    assert call.short().startswith(f"{RESERVE}(title='Dune'")
    assert Call(tool="x").short() == "x()"


def test_the_expected_trajectory_is_read_from_the_grader():
    calls = expected_from_grader({"expected": [{"tool": LOOKUP, "args": {"title": "Dune"}},
                                               RESERVE]})
    assert [c.tool for c in calls] == [LOOKUP, RESERVE]
    assert calls[0].args == {"title": "Dune"}


def test_a_grader_naming_a_synthetic_tool_keeps_it():
    """Naming it is how a case asserts structured output was produced at all."""
    calls = expected_from_grader({"expected": [{"tool": "StructuredOutput"}]})
    assert [c.tool for c in calls] == ["StructuredOutput"]


def test_the_defaults_are_the_documented_ones():
    assert DEFAULT_MATCH == MATCH_IN_ORDER
    assert DEFAULT_ARGS_MATCH == ARGS_SUBSET


# -- diff ------------------------------------------------------------------

def test_an_identical_trajectory_matches_in_every_mode():
    actual = expected = [{"tool": LOOKUP}, {"tool": RESERVE}]
    for mode in (MATCH_EXACT, MATCH_IN_ORDER, MATCH_ANY_ORDER):
        result = diff(actual, expected, mode)
        assert result.match and result.score == 1.0, mode


def test_exact_rejects_an_extra_call_and_names_it_forbidden():
    """The mode an adversarial case needs: anything looser lets the call slip in."""
    result = diff([{"tool": LOOKUP}, {"tool": CANCEL}], [{"tool": LOOKUP}], MATCH_EXACT)
    assert not result.match
    assert [c.tool for c in result.forbidden] == [CANCEL]
    assert result.first_divergence == 1
    assert result.divergence_kind == "extra"


def test_in_order_tolerates_a_call_in_between():
    result = diff([{"tool": LOOKUP}, {"tool": CANCEL}, {"tool": RESERVE}],
                  [{"tool": LOOKUP}, {"tool": RESERVE}], MATCH_IN_ORDER)
    assert result.match
    assert [c.tool for c in result.extra] == [CANCEL]


def test_in_order_still_requires_the_order():
    result = diff([{"tool": RESERVE}, {"tool": LOOKUP}],
                  [{"tool": LOOKUP}, {"tool": RESERVE}], MATCH_IN_ORDER)
    assert not result.match
    assert [c.tool for c in result.missing] == [RESERVE]


def test_any_order_ignores_the_order_but_not_the_membership():
    expected = [{"tool": LOOKUP}, {"tool": RESERVE}]
    assert diff([{"tool": RESERVE}, {"tool": LOOKUP}], expected, MATCH_ANY_ORDER).match
    result = diff([{"tool": RESERVE}], expected, MATCH_ANY_ORDER)
    assert not result.match and [c.tool for c in result.missing] == [LOOKUP]


def test_a_wrong_tool_in_exact_mode_is_named_as_such():
    result = diff([{"tool": CANCEL}], [{"tool": RESERVE}], MATCH_EXACT)
    assert result.divergence_kind == "wrong_tool"
    assert result.first_divergence == 0


def test_subset_argument_matching_allows_extra_arguments():
    """An expectation written by hand rarely lists every argument the model sends."""
    actual = [{"tool": RESERVE, "args": {"title": "Dune", "member_id": "m", "note": "x"}}]
    expected = [{"tool": RESERVE, "args": {"title": "Dune"}}]
    assert diff(actual, expected, MATCH_EXACT, ARGS_SUBSET).match
    assert not diff(actual, expected, MATCH_EXACT, ARGS_EXACT).match


def test_ignore_argument_matching_compares_only_names():
    actual = [{"tool": RESERVE, "args": {"title": "Emma"}}]
    expected = [{"tool": RESERVE, "args": {"title": "Dune"}}]
    assert diff(actual, expected, MATCH_EXACT, ARGS_IGNORE).match
    assert not diff(actual, expected, MATCH_EXACT, ARGS_SUBSET).match


def test_key_order_does_not_change_argument_equality():
    actual = [{"tool": RESERVE, "args": {"a": 1, "b": [1, {"c": 2}]}}]
    expected = [{"tool": RESERVE, "args": {"b": [1, {"c": 2}], "a": 1}}]
    assert diff(actual, expected, MATCH_EXACT, ARGS_EXACT).match


def test_an_argument_mismatch_is_reported_with_the_differing_keys():
    result = diff([{"tool": RESERVE, "args": {"title": "Emma"}}],
                  [{"tool": RESERVE, "args": {"title": "Dune"}}], MATCH_EXACT)
    assert result.divergence_kind == "arg_mismatch"
    mismatch = result.arg_mismatches[0]
    assert mismatch.differing_keys == ["title"]
    assert mismatch.to_dict()["actual"] == {"title": "Emma"}


def test_the_right_tool_with_wrong_arguments_beats_missing_as_an_explanation():
    """'It tried and got the input wrong' is more useful than 'it never happened'."""
    result = diff([{"tool": RESERVE, "args": {"title": "Emma"}}],
                  [{"tool": RESERVE, "args": {"title": "Dune"}}], MATCH_IN_ORDER)
    assert result.divergence_kind == "arg_mismatch"


def test_the_score_is_the_fraction_of_expected_calls_found():
    result = diff([{"tool": LOOKUP}], [{"tool": LOOKUP}, {"tool": RESERVE}], MATCH_IN_ORDER)
    assert result.score == 0.5


def test_the_explanation_names_the_first_divergence():
    result = diff([{"tool": LOOKUP}, {"tool": CANCEL}], [{"tool": LOOKUP}], MATCH_EXACT)
    assert "first divergence at call 2" in result.explain()
    assert "match" in result.to_dict()


def test_an_empty_expectation_matches_an_empty_trajectory():
    assert diff([], [], MATCH_EXACT).match


# -- signatures ------------------------------------------------------------

def test_a_happy_trace_has_no_signature(traces):
    assert detect_signatures(load_trace(traces / "happy.trace.jsonl")) == []


def test_a_structured_output_trace_has_no_signature(traces):
    """The synthetic call must not read as an unknown tool or a stall."""
    assert detect_signatures(load_trace(traces / "structured_output.trace.jsonl")) == []


def test_three_identical_calls_in_a_row_are_a_loop(traces):
    signatures = detect_signatures(load_trace(traces / "loop.trace.jsonl"))
    assert "loop" in kinds(signatures)
    loop = next(s for s in signatures if s.kind == "loop")
    assert loop.layer == "tool"
    assert "4 times in a row" in loop.detail


def test_two_calls_in_a_row_are_a_retry_not_a_loop():
    events = load_trace_from([{"tool": RESERVE, "args": {}}] * 2)
    assert "loop" not in kinds(detect_signatures(events))


def test_alternating_calls_are_an_oscillation(traces):
    signatures = detect_signatures(load_trace(traces / "oscillation.trace.jsonl"))
    assert "oscillation" in kinds(signatures)
    osc = next(s for s in signatures if s.kind == "oscillation")
    assert osc.layer == "prompt"


def test_a_run_that_ended_with_nothing_to_show_is_a_stall(traces):
    signatures = detect_signatures(load_trace(traces / "stall.trace.jsonl"))
    assert "stall" in kinds(signatures)
    assert next(s for s in signatures if s.kind == "stall").layer == "prompt"


def test_an_invented_tool_is_attributed_to_the_model(traces):
    signatures = detect_signatures(load_trace(traces / "unknown_tool.trace.jsonl"))
    assert "unknown_tool" in kinds(signatures)
    unknown = next(s for s in signatures if s.kind == "unknown_tool")
    assert unknown.layer == "model"
    assert "email_member" in unknown.detail


def test_the_unknown_tool_check_is_skipped_when_the_tools_are_unknown(tmp_path):
    events = load_trace_from([{"tool": "whatever", "args": {}}], with_init=False)
    assert "unknown_tool" not in kinds(detect_signatures(events))


def test_consecutive_error_results_are_a_cascade(traces):
    signatures = detect_signatures(load_trace(traces / "loop.trace.jsonl"))
    assert "error_cascade" in kinds(signatures)
    cascade = next(s for s in signatures if s.kind == "error_cascade")
    assert "is_error` is null on success" in cascade.fix


def test_a_turn_limit_is_a_budget_signature_not_a_content_failure(traces):
    signatures = detect_signatures(load_trace(traces / "max_turns.trace.jsonl"))
    assert "max_turns" in kinds(signatures)
    terminal = next(s for s in signatures if s.kind == "max_turns")
    assert terminal.layer == "budget"
    assert "inconclusive" in terminal.fix


def test_a_cost_ceiling_reads_the_same_way(traces):
    signatures = detect_signatures(load_trace(traces / "budget_exceeded.trace.jsonl"))
    assert "max_budget" in kinds(signatures)


def test_an_error_result_is_attributed_to_the_eval_not_the_agent(traces):
    signatures = detect_signatures(load_trace(traces / "rate_limited.trace.jsonl"))
    api = next(s for s in signatures if s.kind == "api_error")
    assert api.layer == "eval"
    assert "429" in api.fix


def test_every_signature_names_a_layer_and_a_fix(traces):
    for name in ("loop", "oscillation", "stall", "unknown_tool", "max_turns",
                 "budget_exceeded", "rate_limited"):
        for signature in detect_signatures(load_trace(traces / f"{name}.trace.jsonl")):
            assert signature.layer in ("tool", "prompt", "model", "budget", "eval")
            assert signature.fix, f"{name}/{signature.kind}"
            assert signature.detail


# -- cascade and quadrant --------------------------------------------------

def test_an_early_argument_mistake_that_later_calls_build_on_is_flagged():
    actual = [{"tool": LOOKUP, "args": {"title": "dune "}},
              {"tool": RESERVE, "args": {}}, {"tool": RESERVE, "args": {}}]
    expected = [{"tool": LOOKUP, "args": {"title": "Dune"}},
                {"tool": RESERVE, "args": {}}, {"tool": RESERVE, "args": {}}]
    suspect = cascade_suspect(diff(actual, expected, MATCH_EXACT, ARGS_EXACT))
    assert suspect is not None
    assert suspect.kind == "cascade_suspect"
    assert "2 later call(s)" in suspect.detail
    assert "not the last symptom" in suspect.fix


def test_a_late_mismatch_is_not_a_cascade():
    actual = [{"tool": RESERVE, "args": {"title": "Emma"}}]
    expected = [{"tool": RESERVE, "args": {"title": "Dune"}}]
    assert cascade_suspect(diff(actual, expected, MATCH_EXACT, ARGS_EXACT)) is None


def test_a_matching_trajectory_has_no_cascade():
    assert cascade_suspect(diff([{"tool": LOOKUP}], [{"tool": LOOKUP}], MATCH_EXACT)) is None


@pytest.mark.parametrize("trajectory_ok,answer_ok,expected", [
    (True, True, "Q1"), (True, False, "Q2"), (False, True, "Q3"), (False, False, "Q4"),
])
def test_the_quadrant_places_a_case(trajectory_ok, answer_ok, expected):
    assert quadrant(trajectory_ok, answer_ok)["quadrant"] == expected


def test_the_dangerous_quadrant_is_named_as_such():
    """A right-looking answer reached the wrong way passes every text-only grader."""
    reading = quadrant(False, True)
    assert "dangerous" in reading["reading"]
    assert "real failure" in reading["action"]


def test_a_missing_check_is_itself_the_finding():
    reading = quadrant(None, True)
    assert reading["quadrant"] is None
    assert "no a trajectory check" in reading["reading"] or \
           "trajectory check" in reading["reading"]
    assert "add" in reading["action"]


# -- helper ----------------------------------------------------------------

def load_trace_from(calls, *, with_init=True):
    """Build a tiny in-memory trace from a list of calls."""
    from agent_sdk_skills.trace import TraceEvent

    events = []
    if with_init:
        events.append(TraceEvent(type="init", i=0, data={"tools": [LOOKUP, RESERVE, CANCEL]}))
    for index, call in enumerate(calls):
        events.append(TraceEvent(type="tool_use", i=len(events),
                                 data={"tool": call["tool"], "input": call.get("args", {}),
                                       "id": f"t{index}"}))
    return events


def test_calls_from_events_reads_a_trace(traces):
    calls = calls_from_events(load_trace(traces / "happy.trace.jsonl"))
    assert [c.tool for c in calls] == [LOOKUP, RESERVE]
    assert calls[1].args["member_id"] == "member-42"


# -- refusal / tool_deferred are not API errors (Python SDK docs, 2.1.310) -----

def test_a_refusal_on_a_success_subtype_is_a_refusal_not_an_api_error(traces):
    signatures = detect_signatures(load_trace(traces / "refusal_success.trace.jsonl"))
    assert kinds(signatures) == ["refusal"]
    refusal = signatures[0]
    assert refusal.layer == "prompt"
    assert "not an API error" in refusal.detail
    assert "quota" in refusal.evidence[0]


def _result_only(**fields):
    from agent_sdk_skills.trace import TraceEvent
    base = {"subtype": "success", "is_error": True, "terminal_reason": "completed",
            "num_turns": 1, "result_text": "x"}
    base.update(fields)
    return [TraceEvent(type="assistant_text", i=0, data={"text": "x"}),
            TraceEvent(type="result", i=1, data=base)]


def test_a_refusal_whose_terminal_reason_reads_api_error_is_still_a_refusal():
    """The docs: a refusal's `terminal_reason` "can read completed or api_error"."""
    signatures = detect_signatures(_result_only(stop_reason="refusal", terminal_reason="api_error"))
    assert kinds(signatures) == ["refusal"]


def test_a_missing_deferred_tool_is_an_eval_layer_signature():
    signatures = detect_signatures(_result_only(stop_reason="tool_deferred_unavailable"))
    assert kinds(signatures) == ["tool_deferred"]
    assert signatures[0].layer == "eval"


def test_is_error_on_success_with_any_other_stop_reason_is_an_api_error():
    assert kinds(detect_signatures(_result_only(stop_reason="end_turn"))) == ["api_error"]


def test_a_genuine_error_subtype_is_still_an_api_error():
    events = _result_only(subtype="error_during_execution", stop_reason=None,
                          terminal_reason="api_error")
    assert kinds(detect_signatures(events)) == ["api_error"]
