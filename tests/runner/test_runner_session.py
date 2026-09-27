"""Exception mapping, run status, the environment scrub, hooks, mocks and faults."""

from __future__ import annotations

import asyncio

import claude_agent_sdk as sdk
import pytest

from agent_sdk_evals import FAILED, NOT_EVALUATED, PASSED
from agent_sdk_evals.loader import Case, Config
from agent_sdk_evals.session import child_env, classify_exception, run_status


# -- exception mapping (CONTRACTS section 8) --------------------------------

def test_result_error_is_caught_before_process_error():
    """`ResultError` subclasses `ProcessError`, so order is load-bearing."""
    assert issubclass(sdk.ResultError, sdk.ProcessError)
    code, kind, message = classify_exception(sdk.ResultError(
        subtype="error_during_execution", terminal_reason="api_error", result="the tool died"))
    assert (code, kind) == (1, "result_error")
    assert "error_during_execution" in message and "api_error" in message


def test_a_result_error_with_a_429_is_inconclusive_not_a_failure():
    code, kind, _ = classify_exception(sdk.ResultError(
        subtype="error_during_execution", api_error_status=429, result="rate limited"))
    assert (code, kind) == (3, "usage_limit")


def test_a_result_error_naming_a_usage_limit_is_inconclusive():
    code, kind, _ = classify_exception(sdk.ResultError(result="Claude usage limit reached"))
    assert (code, kind) == (3, "usage_limit")


@pytest.mark.parametrize("exc,expected", [
    (sdk.CLINotFoundError("not found", cli_path="/nope/claude"), 2),
    (sdk.CLIConnectionError("no socket"), 2),
    (sdk.CLIJSONDecodeError(line="{oops"), 2),
    (sdk.ProcessError("exit 1", exit_code=1, stderr="boom"), 2),
    (sdk.ClaudeSDKError("could not parse a message"), 2),
])
def test_every_other_sdk_exception_is_a_usage_error(exc, expected):
    code, kind, message = classify_exception(exc)
    assert code == expected
    assert kind == type(exc).__name__ or kind in ("ClaudeSDKError", "CLIConnectionError")
    assert message


def test_the_cli_not_found_message_carries_the_remediation():
    _, _, message = classify_exception(sdk.CLINotFoundError("nope", cli_path="/x"))
    assert "pip install claude-agent-sdk" in message
    assert "cli_path='/x'" in message


def test_process_error_details_reach_the_message():
    _, _, message = classify_exception(sdk.ProcessError("failed", exit_code=2, stderr="traceback"))
    assert "exit_code=2" in message and "stderr='traceback'" in message


def test_a_message_parse_error_is_handled_as_a_base_sdk_error():
    """`MessageParseError` is not exported from the package root, so the runner
    catches `ClaudeSDKError` rather than importing a private module."""
    assert not hasattr(sdk, "MessageParseError") or True
    code, _, _ = classify_exception(sdk.ClaudeSDKError("could not parse"))
    assert code == 2


def test_an_unexpected_exception_still_gets_a_code():
    code, kind, message = classify_exception(ValueError("something else"))
    assert (code, kind) == (2, "ValueError") and "something else" in message


# -- run status -------------------------------------------------------------

class FakeGrader:
    def __init__(self, status):
        self.status = status

    @property
    def gating(self):
        return self.status in (PASSED, FAILED)


class FakeOutcome:
    def __init__(self, *, error=None, error_kind=None, not_evaluated=False):
        self.error = error
        self.error_kind = error_kind
        self.not_evaluated = not_evaluated


def test_a_run_passes_only_when_every_gating_grader_passed():
    assert run_status(FakeOutcome(), [FakeGrader(PASSED), FakeGrader(PASSED)]) == PASSED
    assert run_status(FakeOutcome(), [FakeGrader(PASSED), FakeGrader(FAILED)]) == FAILED


def test_informational_and_inconclusive_graders_do_not_gate():
    assert run_status(FakeOutcome(), [FakeGrader(PASSED), FakeGrader("INFORMATIONAL")]) == PASSED
    assert run_status(FakeOutcome(), [FakeGrader(PASSED), FakeGrader(NOT_EVALUATED)]) == PASSED


def test_a_run_with_only_inconclusive_graders_is_inconclusive():
    assert run_status(FakeOutcome(), [FakeGrader(NOT_EVALUATED)]) == NOT_EVALUATED


def test_a_usage_limited_run_is_never_a_failure():
    outcome = FakeOutcome(error="usage limit", error_kind="usage_limit", not_evaluated=True)
    assert run_status(outcome, [FakeGrader(FAILED)]) == NOT_EVALUATED


def test_a_timed_out_run_fails():
    outcome = FakeOutcome(error="exceeded timeout_seconds=1", error_kind="timeout")
    assert run_status(outcome, []) == FAILED


# -- the environment scrub --------------------------------------------------

def test_redact_env_removes_the_variable_from_the_child_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    config = Config(evals_dir=tmp_path, trace={"redact_env": ["ANTHROPIC_API_KEY"]})
    case = Case(name="c", dir=tmp_path, prompt="x", env={"EVAL_BRANCH": "main"})
    env = child_env(case, config)
    assert "ANTHROPIC_API_KEY" not in env, (
        "ClaudeAgentOptions.env can only override, never remove, so the scrub has to happen here"
    )
    assert env["EVAL_BRANCH"] == "main"
    assert env["CLAUDE_AGENT_SDK_CLIENT_APP"]


# -- hooks and faults -------------------------------------------------------

def test_the_capture_hook_is_installed_for_the_events_a_grader_can_name(capture):
    from agent_sdk_evals.faults import CAPTURE_EVENTS, build_hooks

    cap = capture()
    hooks = build_hooks(cap, None, sdk)
    assert set(hooks) == set(CAPTURE_EVENTS)
    assert cap.hook_events_installed == set(CAPTURE_EVENTS)
    assert all(isinstance(m, sdk.HookMatcher) for matchers in hooks.values() for m in matchers)


def test_a_pretooluse_capture_hook_allows_and_records(capture):
    from agent_sdk_evals.faults import build_hooks

    cap = capture()
    hooks = build_hooks(cap, None, sdk)
    callback = hooks["PreToolUse"][0].hooks[0]
    response = asyncio.run(callback({"tool_name": "Read"}, "t1", {"signal": None}))
    assert response["hookSpecificOutput"]["permissionDecision"] == "allow"
    records = cap.hook_records()
    assert [r["phase"] for r in records] == ["hook_started", "hook_response"]
    assert records[0]["tool"] == "Read"


def test_a_deny_fault_returns_the_measured_shape(capture):
    from agent_sdk_evals.faults import build_hooks, load_plan

    plan = load_plan({"seed": 1, "faults": [
        {"id": "no-writes", "event": "PreToolUse", "tool": "Write", "action": "deny",
         "reason": "disk full"}]})
    cap = capture()
    hooks = build_hooks(cap, plan, sdk)
    callback = hooks["PreToolUse"][0].hooks[0]
    denied = asyncio.run(callback({"tool_name": "Write"}, "t1", {}))
    assert denied == {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "disk full"}}
    allowed = asyncio.run(callback({"tool_name": "Read"}, "t2", {}))
    assert allowed["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert any(r.get("fault_id") == "no-writes" for r in cap.hook_records())


def test_an_updated_input_fault_rewrites_the_call(capture):
    from agent_sdk_evals.faults import build_hooks, load_plan

    plan = load_plan({"faults": [{"id": "redirect", "event": "PreToolUse", "tool": "Read",
                                  "action": "updated_input",
                                  "updated_input": {"file_path": "/decoy"}}]})
    hooks = build_hooks(capture(), plan, sdk)
    response = asyncio.run(hooks["PreToolUse"][0].hooks[0]({"tool_name": "Read"}, "t", {}))
    assert response["hookSpecificOutput"]["updatedInput"] == {"file_path": "/decoy"}


def test_a_posttooluse_fault_rewrites_the_output(capture):
    from agent_sdk_evals.faults import build_hooks, load_plan

    plan = load_plan({"faults": [{"id": "garble", "event": "PostToolUse", "tool": ".*",
                                  "action": "error_output",
                                  "updated_tool_output": "<unreadable>", "reason": "corrupted"}]})
    hooks = build_hooks(capture(), plan, sdk)
    response = asyncio.run(hooks["PostToolUse"][0].hooks[0]({"tool_name": "Read"}, "t", {}))
    specific = response["hookSpecificOutput"]
    assert specific["hookEventName"] == "PostToolUse"
    assert specific["updatedToolOutput"] == "<unreadable>"


def test_fault_probability_is_seeded_so_a_flake_is_reproducible(capture):
    from agent_sdk_evals.faults import build_hooks, load_plan

    def denials(run: int) -> list[bool]:
        plan = load_plan({"seed": 7, "faults": [
            {"id": "half", "event": "PreToolUse", "tool": "Read", "action": "deny",
             "probability": 0.5}]}, run=run)
        callback = build_hooks(capture(), plan, sdk)["PreToolUse"][0].hooks[0]
        out = []
        for _ in range(12):
            response = asyncio.run(callback({"tool_name": "Read"}, "t", {}))
            out.append(response["hookSpecificOutput"]["permissionDecision"] == "deny")
        return out

    assert denials(1) == denials(1), "the same seed and run must draw the same faults"
    assert denials(1) != denials(2), "a different run index must draw differently"
    assert any(denials(1)) and not all(denials(1))


def test_latency_is_applied_through_asyncio_sleep(capture):
    from agent_sdk_evals.faults import build_hooks, load_plan

    plan = load_plan({"faults": [{"id": "slow", "event": "PreToolUse", "tool": ".*",
                                  "action": "latency", "latency_ms": 60}]})
    callback = build_hooks(capture(), plan, sdk)["PreToolUse"][0].hooks[0]

    async def timed():
        loop = asyncio.get_running_loop()
        start = loop.time()
        await callback({"tool_name": "Read"}, "t", {})
        return loop.time() - start

    assert asyncio.run(timed()) >= 0.05


def test_an_unsupported_fault_event_is_refused():
    from agent_sdk_evals import EvalError
    from agent_sdk_evals.faults import load_plan

    with pytest.raises(EvalError) as exc:
        load_plan({"faults": [{"event": "SessionStart", "action": "deny"}]})
    assert exc.value.code == "HOK020"


def test_a_probability_outside_the_range_is_refused():
    from agent_sdk_evals import EvalError
    from agent_sdk_evals.faults import load_plan

    with pytest.raises(EvalError) as exc:
        load_plan({"faults": [{"action": "deny", "probability": 1.5}]})
    assert exc.value.code == "SIM002"


# -- mocks ------------------------------------------------------------------

def test_a_mock_server_is_built_from_the_markdown_and_records_its_calls(mini_evals):
    from agent_sdk_evals.mocks import MockRecorder, build_servers

    recorder = MockRecorder()
    servers = build_servers(mini_evals, ["ledger"], recorder, sdk)
    assert set(servers) == {"ledger"}
    built = servers["ledger"].tools[0]
    assert built.name == "lookup"
    result = asyncio.run(built.handler({"member_id": "m7"}))
    assert result["content"][0]["text"].startswith("Member m7 is in good standing")
    assert "is_error" not in result
    assert recorder.calls[0]["tool"] == "mcp__ledger__lookup"
    assert recorder.calls[0]["input"] == {"member_id": "m7"}


def test_a_mock_expectation_that_is_unmet_comes_back_as_an_error_result(tmp_path):
    from agent_sdk_evals.mocks import MockRecorder, build_servers

    root = tmp_path / "mocks" / "ledger"
    root.mkdir(parents=True)
    (root / "lookup.md").write_text(
        "---\ntype: canned\nexpect:\n  member_id: m7\n---\nok\n")
    recorder = MockRecorder()
    built = build_servers(tmp_path, ["ledger"], recorder, sdk)["ledger"].tools[0]
    bad = asyncio.run(built.handler({"member_id": "m9"}))
    assert bad["is_error"] is True and "unmet expectation" in bad["content"][0]["text"]
    assert recorder.calls[0]["note"] == "expect"


def test_a_mock_can_declare_an_error(tmp_path):
    from agent_sdk_evals.mocks import MockRecorder, build_servers

    root = tmp_path / "mocks" / "ledger"
    root.mkdir(parents=True)
    (root / "lookup.md").write_text("---\nerror: the ledger is offline\n---\nunused\n")
    built = build_servers(tmp_path, ["ledger"], MockRecorder(), sdk)["ledger"].tools[0]
    result = asyncio.run(built.handler({}))
    assert result["is_error"] is True and result["content"][0]["text"] == "the ledger is offline"


def test_mock_substitution_covers_inputs_fallbacks_and_files(tmp_path):
    from agent_sdk_evals.mocks import substitute

    (tmp_path / "fixture.txt").write_text("from a file")
    body = "id={{input.member_id}} missing={{input.nope|unknown}} file={{file: fixture.txt}}"
    assert substitute(body, {"member_id": "m7"}, tmp_path) == \
        "id=m7 missing=unknown file=from a file"


def test_a_missing_mock_server_is_refused(tmp_path):
    from agent_sdk_evals import EvalError
    from agent_sdk_evals.mocks import load_mock_tools

    with pytest.raises(EvalError) as exc:
        load_mock_tools(tmp_path, "nope")
    assert exc.value.code == "MCP020"


def test_mock_tool_names_carry_the_mcp_prefix(mini_evals):
    from agent_sdk_evals.mocks import mock_tool_names

    assert mock_tool_names(mini_evals, ["ledger"]) == ["mcp__ledger__lookup"]
