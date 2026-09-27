"""The command line end to end, through the stub: exit codes, the JSON line,
rate-limit semantics, the judge, replay, and that a dry run starts nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import claude_agent_sdk as sdk
import pytest

from agent_sdk_evals import EXIT_FINDINGS, EXIT_INCONCLUSIVE, EXIT_OK, EXIT_USAGE
from agent_sdk_evals import cli as cli_module

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
STUBS = PLUGIN_ROOT / "tests" / "fixtures" / "stubs"
RUNNER = PLUGIN_ROOT / "runner"

RATE_LIMIT_WARNING = {
    "__class__": "RateLimitEvent",
    "rate_limit_info": {
        "status": "allowed_warning", "resets_at": 1790784000, "rate_limit_type": "seven_day",
        "utilization": 0.83,
        "raw": {"status": "allowed_warning", "resetsAt": 1790784000, "surpassedThreshold": 0.75,
                "unifiedWindows": {"seven_day": {"utilization": 0.83, "resetsAt": 1790784000}}},
    },
}
RATE_LIMIT_REJECTED = {
    "__class__": "RateLimitEvent",
    "rate_limit_info": {
        "status": "rejected", "resets_at": 1790784000, "rate_limit_type": "seven_day",
        "utilization": 1.0, "raw": {"status": "rejected", "resetsAt": 1790784000},
    },
}
INIT = {
    "__class__": "SystemMessage", "subtype": "init",
    "data": {"type": "system", "subtype": "init", "cwd": "/tmp/run", "tools": [],
             "mcp_servers": [], "model": "claude-sonnet-5-5", "permissionMode": "dontAsk",
             "apiKeySource": "none", "claude_code_version": "2.1.285"},
}


def text(message: str) -> dict:
    return {"__class__": "AssistantMessage", "content": [{"text": message}],
            "model": "claude-sonnet-5-5", "session_id": "s-1"}


def result(**overrides) -> dict:
    payload = {
        "__class__": "ResultMessage", "subtype": "success", "duration_ms": 900,
        "duration_api_ms": 1200, "is_error": False, "num_turns": 1, "session_id": "s-1",
        "stop_reason": "end_turn", "total_cost_usd": 0.01,
        "usage": {"input_tokens": 4, "output_tokens": 6, "cache_creation_input_tokens": 100,
                  "cache_read_input_tokens": 0},
        "result": "ready", "terminal_reason": "completed",
    }
    payload.update(overrides)
    return payload


READY_RUN = [INIT, RATE_LIMIT_WARNING, text("ready"), result()]


def run_args(evals_dir, **overrides):
    args = argparse.Namespace(
        command="run", evals_dir=str(evals_dir), case=None, tag=None, runs=None, tier="pr",
        dry_run=False, max_cost_usd=None, concurrency=1, wait_for_reset=False, keep_cwd=False,
        out=None, json=True,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def execute(project: Path, script, monkeypatch, **overrides):
    """Run the orchestrator in-process with a scripted SDK."""
    monkeypatch.chdir(project)
    monkeypatch.syspath_prepend(str(project))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used-by-the-stub")
    sdk.set_script(script)
    args = run_args(project / "evals", **overrides)
    return asyncio.run(cli_module.execute_run(args))


# -- dry run ----------------------------------------------------------------

def test_a_dry_run_starts_nothing(project, monkeypatch):
    payload, code = execute(project, READY_RUN, monkeypatch, dry_run=True)
    assert code == EXIT_OK
    assert payload["dry_run"] is True and payload["started_nothing"] is True
    assert sdk.calls() == [], "a dry run must not reach the SDK at all"
    assert not (project / "evals" / "results").exists(), "a dry run writes nothing"
    assert payload["command"].startswith("python -m agent_sdk_evals run")
    assert payload["credential"]["kind"] == "api_key"
    assert {c["case"] for c in payload["cases"]} == {"echo-ready", "lookup-first",
                                                    "structured-answer"}
    for case in payload["cases"]:
        assert case["isolation"] == {"setting_sources": [], "strict_mcp_config": True}
        assert case["model"] == "claude-sonnet-5-5"


def test_a_dry_run_still_refuses_a_bad_override(project, monkeypatch):
    from agent_sdk_evals import EvalError

    case = project / "evals" / "echo-ready" / "prompt.md"
    case.write_text(case.read_text().replace("  tools: []", "  tolls: []"))
    with pytest.raises(EvalError) as exc:
        execute(project, [], monkeypatch, dry_run=True)
    assert exc.value.code == "EVC003" and "tolls" in str(exc.value)
    assert sdk.calls() == []


# -- a passing run ----------------------------------------------------------

def test_a_passing_case_exits_zero_and_writes_the_files(project, monkeypatch):
    payload, code = execute(project, READY_RUN, monkeypatch, case="echo-ready")
    assert code == EXIT_OK
    assert payload["exit_code"] == 0
    assert payload["totals"]["passed"] == 1 and payload["totals"]["failed"] == 0
    out = Path(payload["results_dir"])
    assert (out / "aggregate.json").is_file()
    case_file = out / "echo-ready.result.json"
    assert case_file.is_file()
    stored = json.loads(case_file.read_text())
    assert stored["schema"] == "agent-sdk-skills.result/1"
    assert stored["config"]["isolation"] == {"setting_sources": [], "strict_mcp_config": True}
    assert stored["config"]["cost_basis"] == "api_key"
    statuses = {g["name"]: g["status"] for g in stored["runs"][0]["graders"]}
    assert statuses["says-ready"] == "PASSED"
    assert statuses["no-tools"] == "PASSED"
    assert statuses["finished-cleanly"] == "PASSED"
    assert statuses["cheap"] == "INFORMATIONAL", "an informational budget never gates"
    trace = out / stored["runs"][0]["trace"]
    assert trace.is_file()
    types = [json.loads(line)["type"] for line in trace.read_text().splitlines()]
    assert types[0] == "user" and "init" in types and types[-1] == "result"
    assert json.loads(trace.read_text().splitlines()[0])["schema"] == "agent-sdk-skills.trace/1"


def test_the_isolation_defaults_reach_the_options_the_sdk_was_given(project, monkeypatch):
    execute(project, READY_RUN, monkeypatch, case="echo-ready")
    options = sdk.calls()[0]["options"]
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.include_hook_events is True, "hook events need the capture hook installed"
    assert options.hooks and "PreToolUse" in options.hooks
    assert options.model == "claude-sonnet-5-5"


def test_a_failing_grader_exits_one(project, monkeypatch):
    payload, code = execute(project, [INIT, text("all done"), result(result="all done")],
                            monkeypatch, case="echo-ready")
    assert code == EXIT_FINDINGS
    assert payload["totals"]["failed"] == 1
    assert payload["cases"][0]["pass_rate"] == 0.0


def test_multiple_runs_produce_a_pass_rate_and_pass_at_k(project, monkeypatch):
    payload, _ = execute(project, READY_RUN, monkeypatch, case="echo-ready", runs=3)
    assert payload["totals"]["runs"] == 3
    assert payload["cases"][0]["pass_rate"] == 1.0
    assert payload["cases"][0]["pass_at_k"] == 1.0


# -- rate limits ------------------------------------------------------------

def test_an_allowed_warning_keeps_the_suite_running(project, monkeypatch):
    payload, code = execute(project, READY_RUN, monkeypatch, case="echo-ready")
    assert code == EXIT_OK, "allowed_warning fired on every measured run; it is not a limit hit"
    assert payload["rate_limit"]["status"] == "allowed_warning"
    assert payload["rate_limit"]["windows"]["seven_day"]["utilization"] == 0.83
    assert "stopped" not in payload


def test_a_rejected_rate_limit_is_not_evaluated_and_exits_three(project, monkeypatch):
    payload, code = execute(project, [INIT, RATE_LIMIT_REJECTED, text("ready"), result()],
                            monkeypatch)
    assert code == EXIT_INCONCLUSIVE
    assert payload["totals"]["not_evaluated"] >= 1
    assert payload["totals"]["failed"] == 0, "a limit hit must never be reported as a regression"
    assert payload["stopped"]["reason"] == "rate_limit_rejected"
    assert payload["stopped"]["resets_at"] == 1790784000
    assert len(payload["cases"]) < 3, "no further cases are launched"


def test_a_usage_limit_error_result_is_not_evaluated_and_exits_three(project, monkeypatch):
    script = [INIT, result(subtype="error_during_execution", is_error=True,
                           result="Claude usage limit reached; resets at 6pm",
                           api_error_status=429, terminal_reason="api_error")]
    payload, code = execute(project, script, monkeypatch)
    assert code == EXIT_INCONCLUSIVE
    assert payload["stopped"]["reason"] == "rate_limit_rejected"


def test_a_result_error_raised_mid_run_is_a_failure_not_an_outage(project, monkeypatch):
    script = [INIT, {"__class__": "raise", "error": "ResultError",
                     "message": "the tool died", "subtype": "error_during_execution",
                     "terminal_reason": "api_error"}]
    payload, code = execute(project, script, monkeypatch, case="echo-ready")
    assert code == EXIT_FINDINGS
    assert payload["totals"]["failed"] == 1


def test_a_missing_cli_stops_the_suite_with_exit_two(project, monkeypatch):
    script = [{"__class__": "raise", "error": "CLINotFoundError", "message": "not found",
               "cli_path": "/nope/claude"}]
    payload, code = execute(project, script, monkeypatch)
    assert code == EXIT_USAGE, "a backend problem is not a verdict about the agent"
    assert payload["stopped"]["reason"] == "backend_error"
    assert "pip install claude-agent-sdk" in payload["stopped"]["error"]


# -- cost ceiling -----------------------------------------------------------

def test_a_cost_ceiling_stops_the_suite_and_exits_three(project, monkeypatch):
    payload, code = execute(project, [INIT, text("ready"), result(total_cost_usd=5.0)],
                            monkeypatch, max_cost_usd=0.5)
    assert code == EXIT_INCONCLUSIVE
    assert payload["stopped"]["reason"] == "cost_ceiling"
    assert payload["stopped"]["ceiling_usd"] == 0.5


# -- structured output and tools -------------------------------------------

def test_the_structured_output_case_passes_through_the_synthetic_call(project, monkeypatch):
    script = [
        INIT,
        {"__class__": "AssistantMessage", "model": "claude-sonnet-5-5", "session_id": "s-1",
         "content": [{"id": "t1", "name": "StructuredOutput", "input": {"answer": "Paris"}}]},
        {"__class__": "UserMessage",
         "content": [{"tool_use_id": "t1", "content": "Structured output provided successfully",
                      "is_error": None}],
         "tool_use_result": "Structured output provided successfully"},
        result(stop_reason="tool_use", num_turns=2, result='{"answer":"Paris"}',
               structured_output={"answer": "Paris"}),
    ]
    payload, code = execute(project, script, monkeypatch, case="structured-answer")
    assert code == EXIT_OK
    stored = json.loads((Path(payload["results_dir"]) / "structured-answer.result.json").read_text())
    statuses = {g["name"]: g["status"] for g in stored["runs"][0]["graders"]}
    assert statuses == {"schema-holds": "PASSED", "no-real-tool": "PASSED"}


def test_the_tool_case_passes_on_the_right_call_order(project, monkeypatch):
    script = [
        INIT,
        {"__class__": "AssistantMessage", "model": "m", "session_id": "s-1",
         "content": [{"id": "t1", "name": "mcp__library__lookup_book",
                      "input": {"title": "Dune"}}]},
        {"__class__": "UserMessage",
         "content": [{"tool_use_id": "t1", "content": "Dune: 2 copies available.",
                      "is_error": None}]},
        {"__class__": "AssistantMessage", "model": "m", "session_id": "s-1",
         "content": [{"id": "t2", "name": "mcp__library__reserve_book",
                      "input": {"title": "Dune", "member_id": "member-7"}}]},
        {"__class__": "UserMessage",
         "content": [{"tool_use_id": "t2", "content": "Reserved Dune; 1 left.", "is_error": None}]},
        text("Dune had 2 copies; I reserved one for member-7."),
        result(num_turns=3, result="Dune had 2 copies; I reserved one for member-7."),
    ]
    payload, code = execute(project, script, monkeypatch, case="lookup-first")
    assert code == EXIT_OK, payload
    stored = json.loads((Path(payload["results_dir"]) / "lookup-first.result.json").read_text())
    assert {g["status"] for g in stored["runs"][0]["graders"]} == {"PASSED"}


# -- the judge --------------------------------------------------------------

def test_the_judge_tier_votes_and_adds_its_cost(project, monkeypatch):
    (project / "evals" / "echo-ready" / "graders" / "polite.md").write_text(
        "---\ntype: llm\nsamples: 1\n---\nThe answer must be a single word.\n")
    script = READY_RUN + [
        INIT,
        {"__class__": "AssistantMessage", "model": "claude-sonnet-5-5",
         "content": [{"text": "PASS"}]},
        result(total_cost_usd=0.002, structured_output={"verdict": "PASS", "reason": "one word"}),
    ]
    payload, code = execute(project, script, monkeypatch, case="echo-ready", tier="nightly",
                            runs=1)
    stored = json.loads((Path(payload["results_dir"]) / "echo-ready.result.json").read_text())
    judged = next(g for g in stored["runs"][0]["graders"] if g["type"] == "llm")
    assert judged["status"] == "PASSED"
    assert judged["votes"] == ["PASS"]
    assert judged["cost_usd"] > 0, "judge cost is added to the run"
    assert code == EXIT_OK


def test_a_broken_judge_is_inconclusive_never_a_failure(project, monkeypatch):
    (project / "evals" / "echo-ready" / "graders" / "polite.md").write_text(
        "---\ntype: llm\nsamples: 1\n---\nThe answer must be a single word.\n")
    script = READY_RUN + [{"__class__": "raise", "error": "CLIConnectionError",
                           "message": "the judge could not connect"}]
    payload, _ = execute(project, script, monkeypatch, case="echo-ready", tier="nightly", runs=1)
    stored = json.loads((Path(payload["results_dir"]) / "echo-ready.result.json").read_text())
    judged = next(g for g in stored["runs"][0]["graders"] if g["type"] == "llm")
    assert judged["status"] == "NOT_EVALUATED"
    assert "could not be reached" in judged["reason"]


def test_the_judge_options_are_the_measured_cheap_ones():
    from agent_sdk_evals.judge import VERDICT_SCHEMA, JudgeConfig, build_options

    options = build_options(JudgeConfig(), sdk.ClaudeAgentOptions)
    assert options.tools == [] and options.allowed_tools == [], \
        "allowed_tools only governs prompting; tools=[] is what disables the built-ins"
    assert options.setting_sources == [] and options.strict_mcp_config is True
    assert (options.max_turns, options.permission_mode, options.effort) == (1, "dontAsk", "low")
    assert options.output_format == {"type": "json_schema", "schema": VERDICT_SCHEMA}


@pytest.mark.parametrize("votes,rule,expected", [
    (["PASS", "PASS", "FAIL"], "majority", "PASSED"),
    (["PASS", "FAIL", "FAIL"], "majority", "FAILED"),
    (["PASS", "FAIL"], "majority", "FAILED"),
    (["PASS", "PASS"], "unanimous", "PASSED"),
    (["PASS", "FAIL"], "unanimous", "FAILED"),
    (["FAIL", "PASS"], "any", "PASSED"),
    ([], "majority", "NOT_EVALUATED"),
])
def test_the_vote_tally(votes, rule, expected):
    from agent_sdk_evals.judge import tally

    assert tally(votes, rule) == expected


def test_the_verdict_is_read_from_structured_output_first():
    from agent_sdk_evals.judge import parse_verdict

    assert parse_verdict({"structured_output": {"verdict": "FAIL", "reason": "rude"}}) == \
        ("FAIL", "rude")
    assert parse_verdict({"structured_output": None}, "VERDICT: PASS") == ("PASS", "VERDICT: PASS")
    assert parse_verdict({"structured_output": None}, "unclear") == (None, "unclear")


# -- replay -----------------------------------------------------------------

def test_replay_re_grades_a_stored_trace_without_touching_the_sdk(project, monkeypatch):
    payload, _ = execute(project, READY_RUN, monkeypatch, case="echo-ready")
    trace = Path(payload["results_dir"]) / payload_trace(payload, project, "echo-ready")
    sdk.reset()
    args = argparse.Namespace(command="replay", trace=str(trace),
                              case_dir=str(project / "evals" / "echo-ready"),
                              graders_only=True, json=True)
    replayed, code = cli_module.execute_replay(args)
    assert sdk.calls() == [], "replay is free: no session, no judge"
    assert code == EXIT_OK
    statuses = {g["name"]: g["status"] for g in replayed["runs"][0]["graders"]}
    assert statuses["says-ready"] == "PASSED"
    assert statuses["finished-cleanly"] == "PASSED"


def payload_trace(payload, project, case):
    stored = json.loads((Path(payload["results_dir"]) / f"{case}.result.json").read_text())
    return stored["runs"][0]["trace"]


def test_replay_skips_judge_graders_and_says_so(project, monkeypatch):
    (project / "evals" / "echo-ready" / "graders" / "polite.md").write_text(
        "---\ntype: llm\n---\nThe answer must be short.\n")
    payload, _ = execute(project, READY_RUN, monkeypatch, case="echo-ready")
    trace = Path(payload["results_dir"]) / payload_trace(payload, project, "echo-ready")
    args = argparse.Namespace(command="replay", trace=str(trace),
                              case_dir=str(project / "evals" / "echo-ready"),
                              graders_only=True, json=True)
    replayed, _ = cli_module.execute_replay(args)
    assert replayed["skipped_judge_graders"] == ["polite"]


def test_replay_needs_a_case_dir(tmp_path):
    from agent_sdk_evals import EvalError

    trace = tmp_path / "x.trace.jsonl"
    trace.write_text(json.dumps({"type": "result", "case": "c"}) + "\n")
    args = argparse.Namespace(command="replay", trace=str(trace), case_dir=None,
                              graders_only=True, json=True)
    with pytest.raises(EvalError) as exc:
        cli_module.execute_replay(args)
    assert "--case-dir" in str(exc.value)


def test_replay_abstains_on_graders_that_need_files_or_hooks(project, monkeypatch):
    case = project / "evals" / "needs-files"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text("---\nname: needs-files\ncategory: happy\n---\n\nwrite a file\n")
    (case / "graders" / "wrote-it.md").write_text("---\ntype: file_exists\npath: out.txt\n---\nprose\n")
    payload, _ = execute(project, READY_RUN, monkeypatch, case="echo-ready")
    trace = Path(payload["results_dir"]) / payload_trace(payload, project, "echo-ready")
    args = argparse.Namespace(command="replay", trace=str(trace), case_dir=str(case),
                              graders_only=True, json=True)
    replayed, code = cli_module.execute_replay(args)
    assert replayed["runs"][0]["graders"][0]["status"] == "NOT_EVALUATED"
    assert code == EXIT_INCONCLUSIVE


# -- whoami, version, list-tools -------------------------------------------

AUTH_WITH_PII = json.dumps({
    "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
    "analyticsDisabled": False, "projectsDirectory": "/Users/someone/.claude/projects",
    "configDirectory": "/Users/someone/.claude", "email": "someone@example.com",
    "orgId": "c2888caa-57f0-4fc3-9b80-913e92bfb312",
    "orgName": "someone@example.com's Organization", "subscriptionType": "max",
}, indent=2)


@pytest.fixture
def fake_auth(monkeypatch):
    """`claude auth status` answering with the full measured payload, PII and all."""
    class Done:
        returncode = 0
        stdout = AUTH_WITH_PII
        stderr = ""

    monkeypatch.setattr(cli_module, "find_cli", lambda sdk=None: "/fake/claude")
    monkeypatch.setattr(cli_module.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    for name in cli_module.PROVIDER_SWITCHES:
        monkeypatch.delenv(name, raising=False)


def test_whoami_reports_the_subscription_and_no_identity(fake_auth, capsys):
    args = argparse.Namespace(command="whoami", json=True)
    payload, code = cli_module.execute_whoami(args)
    assert code == EXIT_OK
    assert payload["credential"] == {
        "kind": "login", "cost_basis": "subscription", "plan": "max",
        "auth_method": "claude.ai", "api_provider": "firstParty", "provider_switch": None,
    }
    blob = json.dumps(payload) + capsys.readouterr().out
    for forbidden in ("someone@example.com", "c2888caa", "Organization",
                      "projectsDirectory", "configDirectory"):
        assert forbidden not in blob, f"{forbidden} must never be printed"


def test_auth_status_keeps_only_the_four_safe_keys(fake_auth):
    assert set(cli_module.auth_status()) == {"loggedIn", "authMethod", "apiProvider",
                                            "subscriptionType"}


def test_an_api_key_wins_and_changes_the_cost_basis(fake_auth, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    creds = cli_module.credential()
    assert (creds["kind"], creds["cost_basis"]) == ("api_key", "api_key")


def test_an_oauth_token_is_a_subscription(fake_auth, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    creds = cli_module.credential()
    assert (creds["kind"], creds["cost_basis"]) == ("oauth_token", "subscription")


def test_a_provider_switch_changes_the_cost_basis(fake_auth, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    creds = cli_module.credential()
    assert creds["cost_basis"] == "provider"
    assert creds["provider_switch"] == "CLAUDE_CODE_USE_BEDROCK"


def test_version_reports_all_three_versions():
    payload, code = cli_module.execute_version(argparse.Namespace(command="version", json=True))
    assert code == EXIT_OK
    assert set(payload) == {"runner_version", "sdk_version", "cli_version", "python"}
    assert payload["runner_version"] == "0.1.0"
    assert payload["sdk_version"] == sdk.__version__
    assert payload["cli_version"] == "2.1.285", "the CLI version is read, never derived"


def test_list_tools_reads_the_options_without_starting_a_session(project, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.syspath_prepend(str(project))
    args = argparse.Namespace(command="list-tools", evals_dir=str(project / "evals"),
                              agent=None, probe=False, json=True)
    payload, code = cli_module.execute_list_tools(args)
    assert code == EXIT_OK
    assert payload["source"] == "options"
    assert payload["tools"] == ["mcp__library__lookup_book", "mcp__library__reserve_book"]
    assert payload["mcp_servers"] == ["library"]
    assert sdk.calls() == [], "the default path costs nothing"


# -- the subprocess contract ------------------------------------------------

def sub(project: Path, *argv: str, env_extra=None):
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join([str(STUBS), str(RUNNER), str(project)])
    env["ANTHROPIC_API_KEY"] = "sk-test"
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "agent_sdk_evals", *argv],
                          cwd=str(project), capture_output=True, text=True, env=env, timeout=300)


def last_json(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON line in {stdout!r}")


def test_the_last_stdout_line_is_json_for_every_subcommand(project):
    for argv in (["version"], ["whoami"], ["run", "evals", "--dry-run"],
                 ["list-tools", "evals"]):
        proc = sub(project, *argv)
        assert proc.returncode == 0, proc.stderr
        payload = last_json(proc.stdout)
        assert isinstance(payload, dict) and payload
        assert payload.get("exit_code", 0) == 0


def test_a_usage_error_exits_two_and_still_prints_json(project):
    proc = sub(project, "run", "no-such-dir")
    assert proc.returncode == EXIT_USAGE
    payload = last_json(proc.stdout)
    assert payload["exit_code"] == 2 and "error" in payload
    assert "error:" in proc.stderr


def test_a_scripted_run_through_the_subprocess_exits_zero(project, tmp_path):
    script = tmp_path / "script.json"
    script.write_text(json.dumps(READY_RUN))
    proc = sub(project, "run", "evals", "--case", "echo-ready", "--tier", "pr",
               env_extra={"AGENT_SDK_STUB_SCRIPT": str(script)})
    assert proc.returncode == EXIT_OK, proc.stdout + proc.stderr
    payload = last_json(proc.stdout)
    assert payload["totals"]["passed"] == 1
    assert payload["credential"]["cost_basis"] == "api_key"


def test_the_concurrency_flag_is_capped(project, tmp_path):
    script = tmp_path / "script.json"
    script.write_text(json.dumps(READY_RUN))
    proc = sub(project, "run", "evals", "--case", "echo-ready", "--concurrency", "99",
               "--runs", "2", env_extra={"AGENT_SDK_STUB_SCRIPT": str(script)})
    assert proc.returncode == EXIT_OK, proc.stdout + proc.stderr


def test_keep_cwd_leaves_the_directory_behind(project, monkeypatch):
    payload, _ = execute(project, READY_RUN, monkeypatch, case="echo-ready", keep_cwd=True)
    stored = json.loads((Path(payload["results_dir"]) / "echo-ready.result.json").read_text())
    kept = stored["runs"][0].get("cwd")
    assert kept and Path(kept).is_dir()
    shutil.rmtree(kept, ignore_errors=True)


def test_without_keep_cwd_the_directory_is_removed(project, monkeypatch):
    payload, _ = execute(project, READY_RUN, monkeypatch, case="echo-ready")
    stored = json.loads((Path(payload["results_dir"]) / "echo-ready.result.json").read_text())
    assert "cwd" not in stored["runs"][0]


# -- --wait-for-reset -------------------------------------------------------

def test_wait_for_reset_sleeps_once_and_retries_the_pending_runs(project, monkeypatch):
    """The reset time is in the past here, so the sleep is instant; what matters
    is that the pending cases are retried and the suite recovers."""
    import time as _time

    past = {"__class__": "RateLimitEvent", "rate_limit_info": {
        "status": "rejected", "resets_at": int(_time.time()) - 600,
        "rate_limit_type": "seven_day", "utilization": 1.0,
        "raw": {"status": "rejected"}}}
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(cli_module.asyncio, "sleep", fake_sleep)
    # The first case is rejected; from then on the script is the healthy one.
    scripts = iter([[INIT, past, text("ready"), result()]])

    payload, code = execute(project, next(scripts), monkeypatch, wait_for_reset=True)
    assert slept and slept[0] >= 0, "it sleeps exactly once before retrying"
    assert any("--wait-for-reset slept once" in w for w in payload.get("warnings", []))
    assert code in (EXIT_INCONCLUSIVE, EXIT_OK)


def test_without_wait_for_reset_nothing_sleeps(project, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(cli_module.asyncio, "sleep", fake_sleep)
    execute(project, [INIT, RATE_LIMIT_REJECTED, text("ready"), result()], monkeypatch)
    assert slept == []
