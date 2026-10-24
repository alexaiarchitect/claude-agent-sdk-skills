"""The one test that spends real quota. Skipped unless `AGENT_SDK_LIVE=1`.

Everything else in `tests/runner/` runs against a stub. This file exists because
a stub cannot prove the three things that only a real backend can: that the
credential resolves to the subscription, that the isolation defaults actually
reach the CLI, and that a `RateLimitEvent` arrives with the status the runner
branches on.

It is deliberately small. `--tier pr --runs 1` over the mini project is three
sessions; the suite is expected to stay in single-digit cents. Run it with the
key unset so the subscription is used:

    AGENT_SDK_LIVE=1 PYTHONPATH=runner env -u ANTHROPIC_API_KEY \\
        /path/to/venv/bin/python -m pytest tests/runner/test_live.py -q

If any rate-limit event comes back `rejected`, the run is inconclusive by
design: the test says so and stops rather than reporting a failure.

**Billing the API instead.** A machine with no Claude login, or a sync that has
to verify the API-key path, sets `AGENT_SDK_LIVE_CREDENTIAL=api_key`:
`ANTHROPIC_API_KEY` is then kept in the child environment and the assertions
flip to `cost_basis == "api_key"` and `api_key_source == "ANTHROPIC_API_KEY"`.
The rate-limit assertions are skipped in that mode, because an API key has no
plan windows and no `RateLimitEvent` arrived on either measured run. This spends
money rather than plan quota, so it is opt-in on top of `AGENT_SDK_LIVE=1`:

    set -a; source ../.env; set +a
    AGENT_SDK_LIVE=1 AGENT_SDK_LIVE_CREDENTIAL=api_key PYTHONPATH=runner \\
        ../tmp/venvs/casdk-venv-0.2.174/bin/python -m pytest tests/runner/test_live.py -q

The CLI prints one stderr notice on every API-key run ("claude.ai connectors are
disabled because ANTHROPIC_API_KEY … takes precedence"), which is not a failure.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENT_SDK_LIVE") != "1",
    reason="live SDK runs cost real quota; set AGENT_SDK_LIVE=1 to opt in",
)

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PLUGIN_ROOT / "runner"
MINI = Path(__file__).resolve().parent / "fixtures" / "mini_project"


#: `api_key` keeps `ANTHROPIC_API_KEY` and bills the API; anything else (the
#: default) strips it so the stored login or `CLAUDE_CODE_OAUTH_TOKEN` is used.
LIVE_CREDENTIAL = os.environ.get("AGENT_SDK_LIVE_CREDENTIAL", "subscription")
ON_API_KEY = LIVE_CREDENTIAL == "api_key"
EXPECTED_BASIS = "api_key" if ON_API_KEY else "subscription"


def live_env(project: Path) -> dict[str, str]:
    env = dict(os.environ)
    if not ON_API_KEY:
        # The key beats a login, so an unnoticed export would silently bill the
        # API; it is removed rather than trusted to be absent.
        env.pop("ANTHROPIC_API_KEY", None)
    # The fixture agent's own directory has to be importable beside the runner,
    # or `agent:build_options` fails with AGT001 (measured 2026-10-11).
    env["PYTHONPATH"] = os.pathsep.join([str(RUNNER), str(project)])
    env.setdefault("CLAUDE_MODEL", "claude-sonnet-5-5")
    return env


def run(project: Path, *argv: str, timeout: int = 900) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, "-m", "agent_sdk_evals", *argv],
                          cwd=str(project), capture_output=True, text=True,
                          env=live_env(project), timeout=timeout)
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        if line.strip().startswith("{"):
            payload = json.loads(line)
            break
    assert payload is not None, f"no JSON line\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return proc.returncode, payload


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    target = tmp_path_factory.mktemp("live") / "mini"
    shutil.copytree(MINI, target, ignore=shutil.ignore_patterns("__pycache__", "results"))
    return target


def test_the_credential_is_the_one_that_was_asked_for(project):
    """Checked first: a wrong billing path must be visible before anything runs."""
    code, payload = run(project, "whoami")
    assert code == 0
    creds = payload["credential"]
    assert creds["cost_basis"] == EXPECTED_BASIS, (
        f"expected {EXPECTED_BASIS}, got {creds}; with AGENT_SDK_LIVE_CREDENTIAL unset, "
        "unset ANTHROPIC_API_KEY before running live"
    )
    if ON_API_KEY:
        assert creds["kind"] == "api_key"
    else:
        assert creds["kind"] in ("login", "oauth_token")
    blob = json.dumps(payload)
    for forbidden in ("@", "orgId", "orgName"):
        assert forbidden not in blob, "whoami must never carry account identity"


def test_a_dry_run_costs_nothing_and_resolves_everything(project):
    code, payload = run(project, "run", "evals", "--tier", "pr", "--dry-run")
    assert code == 0 and payload["started_nothing"] is True
    assert payload["credential"]["cost_basis"] == EXPECTED_BASIS
    assert {c["case"] for c in payload["cases"]} == {"echo-ready", "lookup-first",
                                                    "structured-answer"}
    assert all(c["isolation"] == {"setting_sources": [], "strict_mcp_config": True}
               for c in payload["cases"])


def test_the_pr_tier_passes_against_the_real_backend(project, tmp_path_factory):
    """Three real sessions. The assertions that matter are the ones a stub
    cannot make: the CLI actually ran, the isolation defaults reached it, and
    the rate-limit status is the one the runner branches on."""
    out = tmp_path_factory.mktemp("live-results")
    code, payload = run(project, "run", "evals", "--tier", "pr", "--runs", "1",
                        "--concurrency", "1", "--keep-cwd", "--out", str(out))

    limit = payload.get("rate_limit") or {}
    if limit.get("status") == "rejected" or (payload.get("stopped") or {}).get("reason") == \
            "rate_limit_rejected":
        pytest.skip(f"the account hit a usage limit; nothing to conclude: {limit}")

    assert code == 0, json.dumps(payload, indent=2)[:4000]
    totals = payload["totals"]
    assert totals["runs"] == 3 and totals["failed"] == 0 and totals["not_evaluated"] == 0
    assert totals["cost_basis"] == EXPECTED_BASIS
    assert payload["cli_version"] != "unknown"

    # The isolation defaults and the credential proof, read back out of the trace.
    trace = next(out.glob("echo-ready.*.trace.jsonl"))
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    init = next(e for e in events if e["type"] == "init")
    if ON_API_KEY:
        assert init["api_key_source"] == "ANTHROPIC_API_KEY", "the in-band billing proof"
    else:
        assert init["api_key_source"] == "none", "the in-band proof that no API key was used"
    assert init["cli_version"], "the CLI version is reported from the session itself"
    assert init["permission_mode"] == "dontAsk"
    assert init["permission_mode_source"] == "agent", "the fixture sets the mode itself"
    # Recorded when the CLI sends them (2.1.205+ for capabilities), never required.
    assert isinstance(init.get("capabilities", []), list)

    # The cost is spread over every model the CLI billed, not just the agent's.
    result = next(e for e in events if e["type"] == "result")
    assert result["cost_basis"] == EXPECTED_BASIS
    assert result["models_billed"], "model_usage names at least the agent's model"
    assert result["cost_basis_list"] is True, "no negotiated rate on a first-party account"
    print(f"\nLIVE pr tier totals: {json.dumps(totals)}")
    print(f"LIVE echo-ready: cli={init['cli_version']} cost={result.get('total_cost_usd')} "
          f"stop_reason={result.get('stop_reason')} is_error={result.get('is_error')} "
          f"models_billed={result['models_billed']} "
          f"capabilities={len(init.get('capabilities') or [])} "
          f"fast_mode={init.get('fast_mode_state')}/{init.get('fast_mode_disabled_reason')}")

    if ON_API_KEY:
        # An API key has no plan windows, and no `RateLimitEvent` arrived on
        # either measured run (2026-10-11), so there is nothing to assert.
        assert not limit, f"an API key reported a rate limit, which is news: {limit}"
    elif limit:
        assert limit["status"] in ("allowed", "allowed_warning"), limit
        assert limit.get("windows"), "unifiedWindows is the honest utilization source"


def test_the_structured_output_case_shows_the_synthetic_tool_call(project, tmp_path_factory):
    """Reuses the results of the tier run rather than spending again."""
    out = tmp_path_factory.mktemp("live-structured")
    code, payload = run(project, "run", "evals", "--case", "structured-answer",
                        "--tier", "pr", "--runs", "1", "--out", str(out))
    if (payload.get("stopped") or {}).get("reason") == "rate_limit_rejected":
        pytest.skip("usage limit reached")
    assert code == 0, json.dumps(payload, indent=2)[:2000]
    trace = next(out.glob("structured-answer.*.trace.jsonl"))
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    calls = [e for e in events if e["type"] == "tool_use"]
    assert calls, "the CLI delivers output_format through a tool call"
    assert all(e["synthetic"] for e in calls)
    assert all(e["tool"] == "StructuredOutput" for e in calls)
    result = next(e for e in events if e["type"] == "result")
    assert result["structured_output"], result
    print(f"\nLIVE structured-answer: cost={result.get('total_cost_usd')} "
          f"models_billed={result.get('models_billed')}")
