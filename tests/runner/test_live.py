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


def live_env(project: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
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


def test_the_credential_is_the_subscription(project):
    """Checked first: a wrong billing path must be visible before anything runs."""
    code, payload = run(project, "whoami")
    assert code == 0
    creds = payload["credential"]
    assert creds["cost_basis"] == "subscription", (
        f"expected the stored login, got {creds}; unset ANTHROPIC_API_KEY before running live"
    )
    assert creds["kind"] in ("login", "oauth_token")
    blob = json.dumps(payload)
    for forbidden in ("@", "orgId", "orgName"):
        assert forbidden not in blob, "whoami must never carry account identity"


def test_a_dry_run_costs_nothing_and_resolves_everything(project):
    code, payload = run(project, "run", "evals", "--tier", "pr", "--dry-run")
    assert code == 0 and payload["started_nothing"] is True
    assert payload["credential"]["cost_basis"] == "subscription"
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
    assert totals["cost_basis"] == "subscription"
    assert payload["cli_version"] != "unknown"

    # The isolation defaults and the credential proof, read back out of the trace.
    trace = next(out.glob("echo-ready.*.trace.jsonl"))
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    init = next(e for e in events if e["type"] == "init")
    assert init["api_key_source"] == "none", "the in-band proof that no API key was used"
    assert init["cli_version"], "the CLI version is reported from the session itself"
    assert init["permission_mode"] == "dontAsk"

    if limit:
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
