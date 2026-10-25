#!/usr/bin/env python3
"""A fake "Python that has the SDK", for tests that must never need the real one.

The plugin resolves an interpreter through `AGENT_SDK_PYTHON` and then runs one
of two things in it: a probe (`-c <source>`) or the project's runner copy
(`-m agent_sdk_evals ...`). Tests point `AGENT_SDK_PYTHON` at this file, so the
resolution chain is exercised end to end and no mocking is needed anywhere.
Output shapes follow the real runner (`runner/agent_sdk_evals/cli.py`, and
`.dev/CONTRACTS.md` §6, §7, §12).

What it answers:

* ``-c <source>`` — the version probe prints ``FAKE_SDK_VERSION`` (default
  0.2.174); the load probe (source mentions ``build_options``) reads the
  target ``agent.py`` textually and prints a JSON summary; anything else is
  executed with the stub ``claude_agent_sdk`` on ``sys.path``.
* ``-m agent_sdk_evals version|whoami|list-tools|run|replay`` — mimics the
  runner: prints one JSON line last and writes result files, controlled by:

    FAKE_SDK_VERSION          reported SDK version (default 0.2.174)
    FAKE_SDK_CLI_VERSION      reported bundled CLI version (default 2.1.310)
    FAKE_SDK_RUNNER_VERSION   reported runner version (default: the plugin's)
    FAKE_SDK_PASSED/FAILED/NOT_EVALUATED   per-case statuses for `run`, in order
    FAKE_SDK_COST             est. USD per run (default 0.0123)
    FAKE_SDK_CREDENTIAL       api_key | oauth_token | login | none (default login)
    FAKE_SDK_RETURNCODE       force the runner's exit code
    FAKE_SDK_NO_RESULT        1 = write no result files
    FAKE_SDK_IMPORT_ERROR     1 = fail like an agent import failure (exit 2)
    FAKE_SDK_BACKEND_ERROR    1 = stop mid-suite on a backend error (exit 2)
    FAKE_SDK_USAGE_LIMIT      1 = a rejected rate limit after the first run (exit 3)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUBS = HERE.parent / "stubs"
VERSION = os.environ.get("FAKE_SDK_VERSION", "0.2.174")
CLI_VERSION = os.environ.get("FAKE_SDK_CLI_VERSION", "2.1.310")
RESET_EPOCH = 1790784000


def _runner_version() -> str:
    explicit = os.environ.get("FAKE_SDK_RUNNER_VERSION")
    if explicit:
        return explicit
    version_file = HERE.parents[2] / "runner" / "agent_sdk_evals" / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.2.0"


def _probe(code: str, args: list[str]) -> int:
    if "build_options" in code:
        project = Path(args[0]) if args else Path.cwd()
        module = project / "agent.py"
        try:
            text = module.read_text(encoding="utf-8")
        except OSError:
            print(json.dumps({"loaded": False, "error_type": "FileNotFoundError", "error": str(module)}))
            return 1
        if os.environ.get("FAKE_SDK_IMPORT_ERROR"):
            print(json.dumps({"loaded": False, "error_type": "ImportError",
                              "error": "No module named 'claude_agent_sdk'"}))
            return 1
        model = re.search(r'model=os\.getenv\("CLAUDE_MODEL",\s*"([^"]+)"\)', text)
        tools = re.findall(r'@tool\("([a-z_]+)"', text)
        print(json.dumps({
            "loaded": True, "entry": "agent:build_options",
            "options": {"model": model.group(1) if model else None,
                        "permission_mode": (re.search(r'permission_mode="([a-zA-Z]+)"', text) or [None, None])[1],
                        "max_turns": int(m.group(1)) if (m := re.search(r"max_turns=(\d+)", text)) else None},
            "tools": [f"mcp__library__{t}" for t in tools],
        }))
        return 0
    if "claude_agent_sdk" in code and "__version__" in code:
        print(VERSION)
        return 0
    sys.path.insert(0, str(STUBS))
    sys.argv = ["-c", *args]
    exec(compile(code, "<probe>", "exec"), {"__name__": "__main__"})
    return 0


def _credential() -> dict:
    kind = os.environ.get("FAKE_SDK_CREDENTIAL", "login")
    basis = {"api_key": "api_key", "oauth_token": "subscription", "login": "subscription"}.get(kind, "unknown")
    return {"kind": kind, "cost_basis": basis, "plan": "max" if kind == "login" else None,
            "auth_method": "claude.ai" if kind == "login" else None,
            "api_provider": "firstParty" if kind != "none" else None, "provider_switch": None}


def _versions() -> dict:
    return {"runner_version": _runner_version(), "sdk_version": VERSION, "cli_version": CLI_VERSION,
            "python": "3.12.10"}


def _runner(argv: list[str]) -> int:
    if not argv:
        print("fake-sdk: missing runner subcommand", file=sys.stderr)
        return 2
    sub, rest = argv[0], argv[1:]
    forced = os.environ.get("FAKE_SDK_RETURNCODE")
    if sub == "version":
        print(json.dumps({**_versions(), "exit_code": 0}))
        return 0
    if sub == "whoami":
        print(json.dumps({"credential": _credential(), **_versions(),
                          "cli_path": "/fake/site-packages/claude_agent_sdk/_bundled/claude", "exit_code": 0}))
        return 0
    if sub == "list-tools":
        print(json.dumps({"source": "options", "agent": "agent:build_options",
                          "tools": ["mcp__library__lookup_book", "mcp__library__reserve_book",
                                    "mcp__library__cancel_reservation"],
                          "disallowed_tools": ["Bash"], "builtin_tools": None, "mcp_servers": ["library"],
                          "sdk_version": VERSION, "exit_code": 0}))
        return 0
    if sub == "replay":
        trace = rest[0] if rest else "?"
        print(json.dumps({"schema": "agent-sdk-skills.result/1", "case": Path(trace).name.split(".")[0],
                          "replay": trace, "graders_only": True,
                          "runs": [{"run": 1, "status": "PASSED", "graders": [
                              {"name": "ok", "type": "regex", "status": "PASSED", "score": 1.0}]}],
                          "summary": {"passed": 1, "failed": 0, "not_evaluated": 0, "informational": 0},
                          "skipped_judge_graders": [], "exit_code": 0, "status": "PASSED",
                          "graders": [{"name": "ok", "type": "regex", "status": "PASSED", "score": 1.0}]}))
        return 0
    if sub != "run":
        print(f"fake-sdk: unsupported runner subcommand {sub}", file=sys.stderr)
        return 2

    if os.environ.get("FAKE_SDK_IMPORT_ERROR"):
        print("Traceback (most recent call last):\n  ...\nModuleNotFoundError: No module named 'agent'", file=sys.stderr)
        print(json.dumps({"schema": "agent-sdk-skills.aggregate/1", "exit_code": 2,
                          "error": "import failed: No module named 'agent'", "code": "AGT001",
                          "fix": "expose build_options() in agent.py or set `agent` in eval_config.json"}))
        return int(forced) if forced else 2

    evals_dir = Path(rest[0]) if rest and not rest[0].startswith("-") else Path("evals")
    out_dir = None
    tier = "pr"
    for i, arg in enumerate(rest):
        if arg == "--out" and i + 1 < len(rest):
            out_dir = Path(rest[i + 1])
        if arg == "--tier" and i + 1 < len(rest):
            tier = rest[i + 1]
    passed = int(os.environ.get("FAKE_SDK_PASSED", "2"))
    failed = int(os.environ.get("FAKE_SDK_FAILED", "0"))
    not_evaluated = int(os.environ.get("FAKE_SDK_NOT_EVALUATED", "0"))
    cost = float(os.environ.get("FAKE_SDK_COST", "0.0123"))
    usage_limit = bool(os.environ.get("FAKE_SDK_USAGE_LIMIT"))
    backend_error = bool(os.environ.get("FAKE_SDK_BACKEND_ERROR"))
    cases = sorted(p.name for p in evals_dir.iterdir() if p.is_dir() and (p / "prompt.md").is_file()) \
        if evals_dir.is_dir() else []
    statuses = ["PASSED"] * passed + ["FAILED"] * failed + ["NOT_EVALUATED"] * not_evaluated
    if usage_limit or backend_error:
        statuses = statuses[:1] + ["NOT_EVALUATED"] * max(len(cases) - 1, 0)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out_dir = out_dir or (evals_dir / "results" / stamp)
    credential = _credential()
    rate_limit = {"status": "rejected" if usage_limit else "allowed_warning", "utilization": 0.83,
                  "resets_at": RESET_EPOCH,
                  "windows": {"five_hour": {"utilization": 0.55, "resets_at": RESET_EPOCH - 10200},
                              "seven_day": {"utilization": 0.83, "resets_at": RESET_EPOCH}}}
    aggregate = {
        "schema": "agent-sdk-skills.aggregate/1",
        "started": stamp, "finished": stamp, "tier": tier,
        "cases": [],
        "totals": {"cases": 0, "runs": 0, "passed": 0, "failed": 0, "not_evaluated": 0,
                   "cost_usd": 0.0, "cost_basis": credential["cost_basis"], "duration_ms": 0},
        "exit_code": 0, **_versions(),
        "credential": credential, "rate_limit": rate_limit, "results_dir": str(out_dir), "warnings": [],
    }
    for index, case in enumerate(cases):
        status = statuses[index] if index < len(statuses) else "PASSED"
        totals = aggregate["totals"]
        totals["cases"] += 1
        totals["runs"] += 1
        totals[status.lower()] += 1
        totals["cost_usd"] = round(totals["cost_usd"] + cost, 4)
        totals["duration_ms"] += 4200
        aggregate["cases"].append({"case": case, "pass_rate": 1.0 if status == "PASSED" else 0.0,
                                   "pass_at_k": 1.0 if status == "PASSED" else 0.0, "cost": cost,
                                   "not_evaluated": int(status == "NOT_EVALUATED")})
        if not os.environ.get("FAKE_SDK_NO_RESULT"):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{case}.result.json").write_text(json.dumps({
                "schema": "agent-sdk-skills.result/1", "case": case, "category": "happy",
                "config": {"tier": tier, "model": "claude-sonnet-5-5", "agent": "agent:build_options",
                           "judge": {"model": "claude-sonnet-5-5", "samples": 3},
                           "isolation": {"setting_sources": [], "strict_mcp_config": True},
                           "cost_basis": credential["cost_basis"], **_versions()},
                "runs": [{"run": 1, "trace": f"{case}.1.trace.jsonl", "status": status,
                          "graders": [{"name": "criteria", "type": "regex", "status": status,
                                       "score": 1.0 if status == "PASSED" else 0.0}],
                          "result": {"subtype": "success", "terminal_reason": "completed", "num_turns": 3,
                                     "duration_ms": 4200, "total_cost_usd": cost, "cost_delta_usd": cost,
                                     "cost_basis": credential["cost_basis"],
                                     "usage": {"input_tokens": 1200, "output_tokens": 180,
                                               "cache_creation_input_tokens": 4600,
                                               "cache_read_input_tokens": 4400}},
                          "rate_limit": rate_limit}],
                "summary": {"passed": int(status == "PASSED"), "failed": int(status == "FAILED"),
                            "not_evaluated": int(status == "NOT_EVALUATED"), "informational": 0,
                            "pass_rate": 1.0 if status == "PASSED" else 0.0, "cost_usd": cost},
            }, indent=2) + "\n")
    totals = aggregate["totals"]
    if totals["failed"]:
        aggregate["exit_code"] = 1
    if usage_limit:
        aggregate["exit_code"] = 3
        aggregate["stopped"] = {"reason": "rate_limit_rejected", "resets_at": RESET_EPOCH, "status": "rejected"}
    elif backend_error:
        aggregate["exit_code"] = 2
        aggregate["stopped"] = {"reason": "backend_error", "error": "CLIConnectionError: Failed to start Claude Code"}
    elif totals["not_evaluated"] and not totals["passed"] and not totals["failed"]:
        aggregate["exit_code"] = 3
    if not os.environ.get("FAKE_SDK_NO_RESULT"):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2) + "\n")
    print(json.dumps(aggregate))
    return int(forced) if forced else aggregate["exit_code"]


def main(argv: list[str]) -> int:
    if not argv:
        print("fake-sdk: nothing to do", file=sys.stderr)
        return 2
    if argv[0] == "-c":
        return _probe(argv[1], argv[2:])
    if argv[0] == "-m" and len(argv) > 1 and argv[1] == "agent_sdk_evals":
        return _runner(argv[2:])
    if argv[0] == "-m" and len(argv) > 1 and argv[1] == "pytest":
        print("1 passed")
        return 0
    print(f"fake-sdk: unsupported invocation {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
