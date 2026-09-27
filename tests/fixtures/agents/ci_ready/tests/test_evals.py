"""Eval gate for ci_ready, expressed as a pytest test.

Why a test and not just a workflow step: a project that already runs pytest in
CI gets the eval gate for free, with pytest's own exit code, its own reporting
and `-k` selection. The test is a thin wrapper: it runs the runner copy
committed under `evals/runner/` as a subprocess, reads the last JSON line it
printed, and turns the runner's four exit codes into the three verdicts pytest
knows about.

    0  every case at or above threshold  -> pass
    1  a case below threshold            -> fail, with the totals in the message
    2  the runner could not run          -> fail, with its stderr tail
    3  inconclusive (usage limit, cost ceiling, unreachable judge)
                                         -> skip, with the reason

Exit 3 is a skip rather than a failure on purpose. Nothing was scored, so
nothing regressed; a red test for a quota problem teaches people to ignore the
gate. The skip reason says what happened, and the result files are still on
disk.

This test costs real model sessions (pr tier). Keep it out of the default
unit-test selection if that matters: `pytest -m "not evals"`, or run it only in
the workflow that is meant to pay for it.

Written by the `agent-sdk` Claude Code plugin (`/agent-sdk:eval-ci`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
EVALS = PROJECT / "evals"
RUNNER = EVALS / "runner"
TIER = "pr"
MAX_COST_USD = "5"

# Register the marker so `-m "not evals"` works and `--strict-markers` stays
# happy: add `markers = ["evals: runs real model sessions"]` under
# `[tool.pytest.ini_options]` in pyproject.toml.
pytestmark = pytest.mark.evals


def _last_json_line(text: str) -> dict:
    """The runner prints progress lines and one JSON summary last."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def _run_suite() -> tuple[int, dict, str]:
    env = dict(os.environ)
    # The runner is imported from the copy in this repository, never installed;
    # `.` keeps the agent module importable beside it. Getting this wrong makes
    # the suite fail at `import agent_sdk_evals`, which looks like a broken gate
    # rather than a missing path.
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(RUNNER), str(PROJECT)] + ([existing] if existing else [])
    )
    proc = subprocess.run(
        [
            sys.executable, "-m", "agent_sdk_evals", "run", str(EVALS),
            "--tier", TIER,
            "--concurrency", "1",
            "--max-cost-usd", MAX_COST_USD,
            "--json",
        ],
        cwd=str(PROJECT), env=env, capture_output=True, text=True, timeout=3600,
    )
    return proc.returncode, _last_json_line(proc.stdout), proc.stderr


def test_the_eval_suite_passes() -> None:
    if not (RUNNER / "agent_sdk_evals").is_dir():
        pytest.fail(
            f"no runner copy under {RUNNER}. Install one with "
            "`/agent-sdk:agent-create` (install_runner.py)."
        )
    if not any(p.is_dir() and (p / "prompt.md").is_file() for p in EVALS.iterdir()):
        pytest.fail(f"no eval cases under {EVALS}. Write some with `/agent-sdk:eval-create`.")

    code, summary, stderr = _run_suite()
    totals = summary.get("totals") or {}
    shape = ", ".join(f"{key}={totals[key]}" for key in sorted(totals)) or "no totals reported"

    if code == 3:
        stopped = summary.get("stopped") or {}
        reason = stopped.get("reason") or summary.get("rate_limit", {}).get("status") or "unknown"
        pytest.skip(f"inconclusive: nothing could be scored ({reason}); {shape}")
    if code == 2:
        pytest.fail(f"the runner could not run the suite (exit 2): {stderr.strip()[-2000:]}")
    if code == 1:
        pytest.fail(f"eval failures in the {TIER} tier: {shape}")

    assert code == 0, f"unexpected runner exit {code}: {shape}; {stderr.strip()[-2000:]}"
    assert totals.get("passed", 0) > 0, f"the suite exited 0 but scored nothing: {shape}"
