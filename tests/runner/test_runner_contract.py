"""The contract the two sides of the plugin share.

The runner is copied verbatim into users' projects, so it cannot import the
plugin's library — which means the two carry duplicate copies of the same facts.
These tests are what stops the copies drifting: the frontmatter reader must be
byte-identical, and every option and semantics tuple must be equal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_sdk_evals as runner
import agent_sdk_skills as plugin
from agent_sdk_evals import RUNNER_VERSION


def test_the_frontmatter_reader_is_a_byte_identical_copy(plugin_root: Path):
    theirs = plugin_root / "lib" / "agent_sdk_skills" / "frontmatter.py"
    ours = plugin_root / "runner" / "agent_sdk_evals" / "frontmatter.py"
    assert ours.read_bytes() == theirs.read_bytes(), (
        "runner/agent_sdk_evals/frontmatter.py must be a verbatim copy of the plugin's; "
        "copy the plugin's file over it rather than editing either one"
    )


@pytest.mark.parametrize("name", [
    "OPTION_NAMES", "OVERRIDABLE_OPTIONS", "RUNNER_OWNED_OPTIONS", "DEPRECATED_OPTIONS",
    "SYNTHETIC_TOOLS", "SUBAGENT_TOOL_NAMES", "PYTHON_HOOK_EVENTS",
    "HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT", "RESULT_SUBTYPES", "TERMINAL_REASONS",
    "RATE_LIMIT_STATUSES", "PERMISSION_MODES", "SETTING_SOURCES", "EFFORT_LEVELS",
    "CURRENT_MODELS", "DEPRECATED_MODELS", "RETIRING_MODELS", "RETIRED_MODELS",
])
def test_the_two_copies_of_every_sdk_tuple_are_equal(name: str):
    assert getattr(runner, name) == getattr(plugin, name), f"{name} has drifted"


def test_the_isolation_defaults_match():
    assert runner.ISOLATION_DEFAULTS == plugin.ISOLATION_DEFAULTS
    assert runner.ISOLATION_DEFAULTS == {"setting_sources": [], "strict_mcp_config": True}


def test_the_runner_version_matches_the_library():
    assert RUNNER_VERSION == plugin.RUNNER_VERSION


def test_the_docs_read_at_version_matches_the_library():
    assert runner.DOCS_READ_AT_CLI == plugin.DOCS_READ_AT_CLI == "2.1.312"


def test_the_option_list_matches_the_stub():
    """The pinned list is 49 names in declaration order, and the stub agrees.

    `claude_agent_sdk` here is the stub in `tests/fixtures/stubs/`, so this
    checks that the stub and the pinned tuple were updated together — not that
    either matches the released wheel. The test that can actually fail on an
    upstream change is `tests/lib/test_sdk_surface_live.py`, which runs the same
    comparison inside an interpreter with the real SDK installed.
    """
    import claude_agent_sdk as sdk

    live = tuple(sdk.ClaudeAgentOptions.__dataclass_fields__)
    assert len(runner.OPTION_NAMES) == 49
    assert runner.OPTION_NAMES == live


def test_the_schema_strings_are_the_frozen_ones():
    assert runner.SCHEMA_TRACE == "agent-sdk-skills.trace/1"
    assert runner.SCHEMA_RESULT == "agent-sdk-skills.result/1"
    assert runner.SCHEMA_AGGREGATE == "agent-sdk-skills.aggregate/1"
    assert runner.SCHEMA_EVAL_CONFIG == "agent-sdk-skills.eval-config/1"


def test_the_exit_codes_match_the_plugin_contract():
    from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_INCONCLUSIVE, EXIT_OK, EXIT_USAGE

    assert (runner.EXIT_OK, runner.EXIT_FINDINGS, runner.EXIT_USAGE, runner.EXIT_INCONCLUSIVE) == \
           (EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_INCONCLUSIVE) == (0, 1, 2, 3)


def test_the_result_file_carries_every_required_key(mini_evals: Path):
    """CONTRACTS section 6: the keys `eval-analyze` is allowed to rely on."""
    from agent_sdk_evals.results import CaseResult, RunRecord

    case = CaseResult(
        case="c", category="edge",
        config={"tier": "nightly", "model": "claude-sonnet-5-5",
                "judge": {"model": "claude-sonnet-5-5", "samples": 3},
                "isolation": {"setting_sources": [], "strict_mcp_config": True},
                "cost_basis": "subscription", "sdk_version": "0.2.174", "cli_version": "2.1.310"},
        runs=[RunRecord(run=1, trace="c.1.trace.jsonl", status="PASSED",
                        graders=[{"name": "g", "type": "regex", "status": "PASSED", "score": 1.0}],
                        result={"subtype": "success", "terminal_reason": "completed",
                                "num_turns": 3, "duration_ms": 8123, "total_cost_usd": 0.042,
                                "cost_delta_usd": 0.042,
                                "usage": {"input_tokens": 12, "output_tokens": 430,
                                          "cache_creation_input_tokens": 4620,
                                          "cache_read_input_tokens": 4418}},
                        rate_limit={"status": "allowed_warning", "utilization": 0.83,
                                    "resets_at": 1790784000})],
    )
    payload = json.loads(json.dumps(case.to_dict()))
    assert payload["schema"] == "agent-sdk-skills.result/1"
    assert set(payload) >= {"schema", "case", "category", "config", "runs", "summary"}
    assert set(payload["config"]) >= {"tier", "model", "judge", "isolation", "cost_basis",
                                      "sdk_version", "cli_version"}
    run = payload["runs"][0]
    assert set(run) >= {"run", "trace", "status", "graders", "result", "rate_limit"}
    assert set(run["result"]) >= {"subtype", "terminal_reason", "num_turns", "duration_ms",
                                 "total_cost_usd", "cost_delta_usd", "usage"}
    assert set(payload["summary"]) == {"passed", "failed", "not_evaluated", "informational",
                                      "pass_rate", "cost_usd"}


def test_the_aggregate_carries_every_required_key():
    """CONTRACTS section 7, including that `credential` holds no identity."""
    from agent_sdk_evals.results import Aggregate, CaseResult, RunRecord

    aggregate = Aggregate(
        tier="nightly", sdk_version="0.2.174", cli_version="2.1.310",
        credential={"kind": "login", "cost_basis": "subscription", "plan": "max",
                    "auth_method": "claude.ai", "api_provider": "firstParty"},
        rate_limit={"status": "allowed_warning", "windows": {"seven_day": {"utilization": 0.83}}},
    )
    aggregate.cases.append(CaseResult(
        case="c", category="happy", config={},
        runs=[RunRecord(run=1, trace="c.1.trace.jsonl", status="PASSED",
                        result={"total_cost_usd": 0.1})],
    ))
    payload = json.loads(json.dumps(aggregate.to_dict(pass_k=3)))
    assert payload["schema"] == "agent-sdk-skills.aggregate/1"
    assert set(payload) >= {"schema", "started", "finished", "tier", "cases", "totals",
                           "exit_code", "runner_version", "sdk_version", "cli_version",
                           "credential", "rate_limit"}
    assert set(payload["cases"][0]) == {"case", "pass_rate", "pass_at_k", "cost", "not_evaluated"}
    assert set(payload["totals"]) >= {"cases", "runs", "passed", "failed", "not_evaluated",
                                     "cost_usd", "cost_basis", "duration_ms"}
    for forbidden in ("email", "orgId", "orgName"):
        assert forbidden not in json.dumps(payload), f"{forbidden} must never reach a result file"


def test_the_trace_envelope_matches_the_contract(capture):
    cap = capture()
    cap.user_turn("hello")
    cap.emit("assistant_text", text="hi", model="claude-sonnet-5-5")
    first, second = cap.events
    assert first["schema"] == "agent-sdk-skills.trace/1"
    assert "schema" not in second, "only line 0 carries the schema"
    for event in cap.events:
        assert set(event) >= {"i", "t", "type", "run_id", "case", "session_id"}
    assert [e["i"] for e in cap.events] == [0, 1]
