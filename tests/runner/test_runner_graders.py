"""Every grader, positive and negative, plus the three semantics that were fixed
by measurement: synthetic-tool exclusion, Task/Agent aliasing, and the fact that
a `hook_event` grader without its hook is inconclusive rather than failed.
"""

from __future__ import annotations

import json

import pytest

from agent_sdk_evals import FAILED, INFORMATIONAL, NOT_EVALUATED, PASSED
from agent_sdk_evals.graders import grade_free


def tool_use(name, input_=None, *, synthetic=False, index=0):
    return {"i": index, "type": "tool_use", "tool": name, "id": f"t{index}",
            "input": input_ or {}, "synthetic": synthetic}


def result_event(**fields):
    base = {"type": "result", "subtype": "success", "is_error": False,
            "terminal_reason": "completed", "num_turns": 2, "duration_ms": 1200,
            "total_cost_usd": 0.02, "cost_delta_usd": 0.02, "structured_output": None,
            "usage": {"input_tokens": 10, "output_tokens": 40,
                      "cache_creation_input_tokens": 100, "cache_read_input_tokens": 200}}
    base.update(fields)
    return base


# -- regex ------------------------------------------------------------------

def test_regex_contains_passes_and_fails(grader, evidence):
    ev = evidence(last_message="The book is ready for collection.")
    assert grade_free(grader("regex", pattern=r"\bready\b", flags="i"), ev).status == PASSED
    assert grade_free(grader("regex", pattern=r"\bcancelled\b"), ev).status == FAILED


def test_regex_not_contains_and_count(grader, evidence):
    ev = evidence(last_message="ready ready")
    assert grade_free(grader("regex", pattern="ready", match="not_contains"), ev).status == FAILED
    assert grade_free(grader("regex", pattern="ready", match="count:2"), ev).status == PASSED
    assert grade_free(grader("regex", pattern="ready", match="count:3"), ev).status == FAILED


def test_regex_can_read_the_trace_and_the_mock_calls(grader, evidence):
    ev = evidence(events=[tool_use("mcp__library__lookup_book", {"title": "Dune"})],
                  mock_calls=[{"tool": "mcp__ledger__lookup", "input": {"member_id": "m7"}}])
    assert grade_free(grader("regex", pattern="lookup_book", target="trace"), ev).status == PASSED
    assert grade_free(grader("regex", pattern="m7", target="mock_calls"), ev).status == PASSED


def test_regex_on_files_abstains_without_a_working_directory(grader, evidence):
    got = grade_free(grader("regex", pattern="x", target="files"), evidence())
    assert got.status == NOT_EVALUATED


def test_regex_reads_a_file_target(grader, evidence, tmp_path):
    (tmp_path / "out.txt").write_text("reserved Dune for member-7")
    ev = evidence(run_cwd=tmp_path)
    got = grade_free(grader("regex", pattern="member-7",
                            target={"source": "file", "path": "out.txt"}), ev)
    assert got.status == PASSED


def test_an_unknown_target_abstains(grader, evidence):
    assert grade_free(grader("regex", pattern="x", target="nonsense"),
                      evidence()).status == NOT_EVALUATED


# -- final_text -------------------------------------------------------------

def test_final_text_modes(grader, evidence):
    ev = evidence(last_message="Two copies of Dune are available.")
    assert grade_free(grader("final_text", reference="two copies"), ev).status == PASSED
    assert grade_free(grader("final_text", reference="no copies"), ev).status == FAILED
    assert grade_free(grader("final_text", reference="Two copies of Dune are available.",
                             mode="exact"), ev).status == PASSED
    assert grade_free(grader("final_text", reference="Two copies of Dune are available",
                             mode="exact"), ev).status == FAILED


def test_final_text_rouge1_scores_word_overlap(grader, evidence):
    ev = evidence(last_message="two copies of Dune are available")
    good = grade_free(grader("final_text", reference="Dune has two copies available",
                             mode="rouge1", threshold=0.5), ev)
    assert good.status == PASSED and 0.0 < good.score <= 1.0
    bad = grade_free(grader("final_text", reference="the library is closed on Sundays",
                            mode="rouge1", threshold=0.5), ev)
    assert bad.status == FAILED


# -- tool_used --------------------------------------------------------------

def test_tool_used_matches_a_bare_name_against_the_mcp_prefix(grader, evidence):
    ev = evidence(events=[tool_use("mcp__library__lookup_book", {"title": "Dune"})])
    assert grade_free(grader("tool_used", tool="lookup_book"), ev).status == PASSED
    assert grade_free(grader("tool_used", tool="mcp__library__lookup_book"), ev).status == PASSED
    assert grade_free(grader("tool_used", tool="reserve_book"), ev).status == FAILED


def test_tool_used_honours_min_max_and_input_match(grader, evidence):
    ev = evidence(events=[tool_use("Read", {"file_path": "/a"}, index=0),
                          tool_use("Read", {"file_path": "/b"}, index=1)])
    assert grade_free(grader("tool_used", tool="Read", min=2), ev).status == PASSED
    assert grade_free(grader("tool_used", tool="Read", min=3), ev).status == FAILED
    assert grade_free(grader("tool_used", tool="Read", max=1), ev).status == FAILED
    assert grade_free(grader("tool_used", tool="Read", min=0, max=0), ev).status == FAILED
    assert grade_free(grader("tool_used", tool="Read",
                             input_match={"file_path": "/a"}), ev).status == PASSED
    assert grade_free(grader("tool_used", tool="Read",
                             input_match={"file_path": "/zzz"}), ev).status == FAILED


def test_min_zero_max_zero_is_the_must_not_form(grader, evidence):
    ev = evidence(events=[tool_use("Write")])
    assert grade_free(grader("tool_used", tool="Read", min=0, max=0), ev).status == PASSED


def test_task_and_agent_are_the_same_tool(grader, evidence):
    """Measured: the CLI reports `Task`, the SDK and the docs say `Agent`."""
    cli = evidence(events=[tool_use("Task", {"subagent_type": "reviewer"})])
    assert grade_free(grader("tool_used", tool="Agent"), cli).status == PASSED
    docs = evidence(events=[tool_use("Agent", {})])
    assert grade_free(grader("tool_used", tool="Task"), docs).status == PASSED


def test_tool_used_can_count_mock_calls_instead(grader, evidence):
    ev = evidence(mock_calls=[{"tool": "mcp__ledger__lookup", "input": {"member_id": "m7"}}])
    got = grade_free(grader("tool_used", tool="lookup", target="mock_calls"), ev)
    assert got.status == PASSED


# -- synthetic tools --------------------------------------------------------

def test_the_synthetic_structured_output_call_is_invisible_by_default(grader, evidence):
    """Without this rule every structured-output case sees a phantom tool call."""
    ev = evidence(events=[tool_use("StructuredOutput", {"answer": "Paris"}, synthetic=True)])
    assert grade_free(grader("no_tool", tools=["Bash", "Read"]), ev).status == PASSED
    assert grade_free(grader("tool_used", tool="Read", min=0, max=0), ev).status == PASSED
    trajectory = grade_free(grader("trajectory", expected=[{"tool": "Read"}]), ev)
    assert trajectory.status == FAILED and trajectory.score == 0.0


def test_a_grader_that_names_the_synthetic_tool_can_still_see_it(grader, evidence):
    ev = evidence(events=[tool_use("StructuredOutput", {"answer": "Paris"}, synthetic=True)])
    assert grade_free(grader("tool_used", tool="StructuredOutput"), ev).status == PASSED
    assert grade_free(grader("no_tool", tools=["StructuredOutput"]), ev).status == FAILED


# -- tool_order and no_tool -------------------------------------------------

def test_tool_order(grader, evidence):
    good = evidence(events=[tool_use("mcp__library__lookup_book", index=0),
                            tool_use("mcp__library__reserve_book", index=1)])
    bad = evidence(events=[tool_use("mcp__library__reserve_book", index=0),
                           tool_use("mcp__library__lookup_book", index=1)])
    spec = grader("tool_order", before="lookup_book", after="reserve_book")
    assert grade_free(spec, good).status == PASSED
    assert grade_free(spec, bad).status == FAILED


def test_tool_order_fails_loudly_when_a_tool_never_ran(grader, evidence):
    ev = evidence(events=[tool_use("mcp__library__lookup_book")])
    got = grade_free(grader("tool_order", before="lookup_book", after="reserve_book"), ev)
    assert got.status == FAILED and "never called" in got.reason


def test_no_tool(grader, evidence):
    assert grade_free(grader("no_tool", tools=["Bash"]), evidence()).status == PASSED
    ev = evidence(events=[tool_use("Bash", {"command": "ls"})])
    assert grade_free(grader("no_tool", tools=["Bash"]), ev).status == FAILED


# -- trajectory -------------------------------------------------------------

def test_trajectory_in_order_allows_extras_between(grader, evidence):
    ev = evidence(events=[tool_use("lookup_book", {"title": "Dune"}, index=0),
                          tool_use("Read", index=1),
                          tool_use("reserve_book", {"title": "Dune"}, index=2)])
    spec = grader("trajectory", expected=[{"tool": "lookup_book"}, {"tool": "reserve_book"}])
    got = grade_free(spec, ev)
    assert got.status == PASSED and got.score == 1.0


def test_trajectory_exact_forbids_extras(grader, evidence):
    ev = evidence(events=[tool_use("lookup_book", index=0), tool_use("Read", index=1),
                          tool_use("reserve_book", index=2)])
    spec = grader("trajectory", match="EXACT",
                  expected=[{"tool": "lookup_book"}, {"tool": "reserve_book"}])
    got = grade_free(spec, ev)
    assert got.status == FAILED and "EXACT wants exactly 2" in got.reason


def test_trajectory_any_order(grader, evidence):
    ev = evidence(events=[tool_use("reserve_book", index=0), tool_use("lookup_book", index=1)])
    spec = grader("trajectory", match="ANY_ORDER",
                  expected=[{"tool": "lookup_book"}, {"tool": "reserve_book"}])
    assert grade_free(spec, ev).status == PASSED


def test_trajectory_threshold_and_args_match(grader, evidence):
    ev = evidence(events=[tool_use("lookup_book", {"title": "Dune"}, index=0)])
    partial = grader("trajectory", threshold=0.5,
                     expected=[{"tool": "lookup_book"}, {"tool": "reserve_book"}])
    got = grade_free(partial, ev)
    assert got.status == PASSED and got.score == 0.5
    subset = grader("trajectory", expected=[{"tool": "lookup_book", "args": {"title": "dune"}}])
    assert grade_free(subset, ev).status == PASSED, "subset matching is case-insensitive on strings"
    exact = grader("trajectory", args_match="exact",
                   expected=[{"tool": "lookup_book", "args": {"title": "dune"}}])
    assert grade_free(exact, ev).status == FAILED
    ignore = grader("trajectory", args_match="ignore",
                    expected=[{"tool": "lookup_book", "args": {"title": "anything"}}])
    assert grade_free(ignore, ev).status == PASSED


def test_trajectory_refuses_a_simulated_user_case(grader, evidence):
    ev = evidence(events=[tool_use("lookup_book")], simulated_user_turns=["I need a book"])
    got = grade_free(grader("trajectory", expected=[{"tool": "lookup_book"}]), ev)
    assert got.status == NOT_EVALUATED and "EVC040" in got.reason


def test_trajectory_with_an_empty_expected_list_abstains(grader, evidence):
    assert grade_free(grader("trajectory", expected=[]), evidence()).status == NOT_EVALUATED


# -- file_exists ------------------------------------------------------------

def test_file_exists(grader, evidence, tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("x")
    ev = evidence(run_cwd=tmp_path)
    assert grade_free(grader("file_exists", path="notes/*.md"), ev).status == PASSED
    assert grade_free(grader("file_exists", path="missing/*.md"), ev).status == FAILED


def test_file_exists_abstains_on_a_replayed_trace(grader, evidence):
    got = grade_free(grader("file_exists", path="*.md"), evidence())
    assert got.status == NOT_EVALUATED and "--keep-cwd" in got.reason


# -- structured_output ------------------------------------------------------

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"]}


def test_structured_output_validates_and_compares(grader, evidence):
    ev = evidence(result=result_event(structured_output={"answer": "Paris"}))
    assert grade_free(grader("structured_output", schema=SCHEMA), ev).status == PASSED
    assert grade_free(grader("structured_output", schema=SCHEMA,
                             contains={"answer": "paris"}), ev).status == PASSED
    assert grade_free(grader("structured_output", schema=SCHEMA,
                             equals={"answer": "Paris"}), ev).status == PASSED
    assert grade_free(grader("structured_output", schema=SCHEMA,
                             equals={"answer": "Lyon"}), ev).status == FAILED


def test_structured_output_reports_the_schema_violation(grader, evidence):
    ev = evidence(result=result_event(structured_output={"answer": 42}))
    got = grade_free(grader("structured_output", schema=SCHEMA), ev)
    assert got.status == FAILED and "expected string, got int" in got.reason


def test_structured_output_notices_a_missing_required_key(grader, evidence):
    ev = evidence(result=result_event(structured_output={}))
    got = grade_free(grader("structured_output", schema=SCHEMA), ev)
    assert got.status == FAILED and "missing required property" in got.reason


def test_structured_output_fails_when_there_is_none(grader, evidence):
    ev = evidence(result=result_event(structured_output=None))
    got = grade_free(grader("structured_output", schema=SCHEMA), ev)
    assert got.status == FAILED and "output_format" in got.reason


def test_structured_output_abstains_without_a_result(grader, evidence):
    assert grade_free(grader("structured_output", schema=SCHEMA),
                      evidence()).status == NOT_EVALUATED


def test_structured_output_reads_a_schema_file(grader, evidence, tmp_path):
    (tmp_path / "shape.json").write_text(json.dumps(SCHEMA))
    ev = evidence(result=result_event(structured_output={"answer": "Paris"}), case_dir=tmp_path)
    assert grade_free(grader("structured_output", schema_file="shape.json"), ev).status == PASSED


def test_a_boolean_is_not_a_number_in_the_schema_check(grader, evidence):
    schema = {"type": "object", "properties": {"n": {"type": "number"}}}
    ev = evidence(result=result_event(structured_output={"n": True}))
    got = grade_free(grader("structured_output", schema=schema), ev)
    assert got.status == FAILED and "boolean" in got.reason


# -- budget -----------------------------------------------------------------

def test_budget_uses_the_case_total_for_cost(grader, evidence):
    ev = evidence(result=result_event(total_cost_usd=0.5), case_cost_usd=0.5)
    assert grade_free(grader("budget", max_cost_usd=1.0), ev).status == PASSED
    assert grade_free(grader("budget", max_cost_usd=0.1), ev).status == FAILED


def test_budget_token_fields_map_to_the_measured_usage_keys(grader, evidence):
    ev = evidence(result=result_event())
    assert grade_free(grader("budget", max_input_tokens=10), ev).status == PASSED
    assert grade_free(grader("budget", max_input_tokens=9), ev).status == FAILED
    assert grade_free(grader("budget", max_output_tokens=39), ev).status == FAILED
    assert grade_free(grader("budget", max_cache_read_tokens=200), ev).status == PASSED
    assert grade_free(grader("budget", max_cache_creation_tokens=99), ev).status == FAILED


def test_budget_max_turns_is_the_graders_own_ceiling(grader, evidence):
    """Measured: `max_turns=1` produced `num_turns=2` on a successful run, so the
    grader's ceiling is independent of the option."""
    ev = evidence(result=result_event(num_turns=2))
    assert grade_free(grader("budget", max_turns=2), ev).status == PASSED
    assert grade_free(grader("budget", max_turns=1), ev).status == FAILED


def test_budget_informational_never_gates(grader, evidence):
    ev = evidence(result=result_event(total_cost_usd=99.0), case_cost_usd=99.0)
    got = grade_free(grader("budget", max_cost_usd=0.01, informational=True), ev)
    assert got.status == INFORMATIONAL and got.gating is False


def test_budget_abstains_on_an_imported_session(grader, evidence):
    got = grade_free(grader("budget", max_cost_usd=1.0), evidence())
    assert got.status == NOT_EVALUATED and "imported" in got.reason


# -- hook_event -------------------------------------------------------------

def hook(event, phase="hook_response", **fields):
    return {"type": "hook", "event": event, "phase": phase, **fields}


def test_hook_event_abstains_without_an_installed_hook(grader, evidence):
    """`include_hook_events=True` alone emits nothing, so this is inconclusive."""
    got = grade_free(grader("hook_event", event="PreToolUse"), evidence())
    assert got.status == NOT_EVALUATED and "no capture hook was installed" in got.reason


def test_hook_event_counts_firings_when_the_hook_was_installed(grader, evidence):
    ev = evidence(events=[hook("PreToolUse", tool="Read", decision="allow"),
                          hook("PreToolUse", tool="Write", decision="deny")],
                  hook_events_installed={"PreToolUse"})
    assert grade_free(grader("hook_event", event="PreToolUse", min=2), ev).status == PASSED
    assert grade_free(grader("hook_event", event="PreToolUse", min=3), ev).status == FAILED
    assert grade_free(grader("hook_event", event="PreToolUse", decision="deny"),
                      ev).status == PASSED
    assert grade_free(grader("hook_event", event="PreToolUse", matcher="Write", min=1),
                      ev).status == PASSED
    assert grade_free(grader("hook_event", event="PreToolUse", matcher="Bash", min=1),
                      ev).status == FAILED


def test_session_start_is_not_a_python_hook_event(grader, evidence):
    got = grade_free(grader("hook_event", event="SessionStart"),
                     evidence(hook_events_installed={"SessionStart"}))
    assert got.status == NOT_EVALUATED and "HOK020" in got.reason


# -- terminal ---------------------------------------------------------------

def test_terminal_asserts_the_subtype_and_the_reason(grader, evidence):
    ev = evidence(result=result_event())
    assert grade_free(grader("terminal", subtype="success"), ev).status == PASSED
    assert grade_free(grader("terminal", terminal_reason="completed"), ev).status == PASSED
    assert grade_free(grader("terminal", subtype="error_max_turns"), ev).status == FAILED


def test_terminal_is_how_a_tripped_limit_is_asserted(grader, evidence):
    ev = evidence(result=result_event(subtype="error_max_turns", terminal_reason="max_turns",
                                      is_error=True, num_turns=9))
    assert grade_free(grader("terminal", subtype="error_max_turns", allow_error=True),
                      ev).status == PASSED
    assert grade_free(grader("terminal", terminal_reason="max_turns", allow_error=True),
                      ev).status == PASSED


def test_terminal_fails_an_error_result_unless_allow_error(grader, evidence):
    ev = evidence(result=result_event(is_error=True))
    assert grade_free(grader("terminal", subtype="success"), ev).status == FAILED
    assert grade_free(grader("terminal", subtype="success", allow_error=True), ev).status == PASSED


def test_terminal_accepts_a_list_of_allowed_values(grader, evidence):
    ev = evidence(result=result_event(subtype="error_max_turns", is_error=True))
    got = grade_free(grader("terminal", subtype=["success", "error_max_turns"], allow_error=True), ev)
    assert got.status == PASSED


def test_terminal_abstains_when_the_reason_is_null(grader, evidence):
    ev = evidence(result=result_event(terminal_reason=None))
    got = grade_free(grader("terminal", terminal_reason="completed"), ev)
    assert got.status == NOT_EVALUATED and "older CLI" in got.reason


def test_terminal_abstains_without_a_result(grader, evidence):
    assert grade_free(grader("terminal", subtype="success"),
                      evidence()).status == NOT_EVALUATED


# -- the registry -----------------------------------------------------------

def test_an_unknown_grader_type_abstains_rather_than_crashing(grader, evidence):
    spec = grader("regex", pattern="x")
    spec.type = "telepathy"
    assert grade_free(spec, evidence()).status == NOT_EVALUATED


def test_a_grader_that_raises_abstains_with_the_exception_in_its_reason(grader, evidence):
    got = grade_free(grader("regex", pattern="(unclosed"), evidence(last_message="x"))
    assert got.status == NOT_EVALUATED and "error" in got.reason.lower()


@pytest.mark.parametrize("type_", ["regex", "tool_used", "tool_order", "file_exists",
                                   "trajectory", "structured_output", "budget", "hook_event",
                                   "final_text", "no_tool", "terminal"])
def test_every_free_grader_type_is_implemented(type_: str):
    from agent_sdk_evals.graders import _registry

    assert type_ in _registry()
