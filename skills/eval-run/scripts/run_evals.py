#!/usr/bin/env python3
"""Run a tier of the project's eval suite through its runner copy, honestly.

The runner lives in the project (`evals/runner/agent_sdk_evals`) and needs the
project's own interpreter, credential and SDK. This wrapper does the part that
should happen before any session starts: it finds the runner copy and refuses a
missing or newer one, resolves an interpreter that imports the SDK, reports the
credential the subprocess will inherit (an API key bills the API; a login or
OAuth token draws on the subscription and makes costs estimates), and prints
the exact command. Only then does it run, and afterwards it reads the result
directory rather than the terminal scroll.

    run_evals.py <project> [--tier pr|nightly|free|run|judge] [--runs N] [--case GLOB]
                 [--tag T] [--dry-run] [--max-cost-usd X] [--concurrency N]
                 [--wait-for-reset] [--not-evaluated fail|warn] [--timeout S] [--json]

Exit codes: 0 every case at or above threshold, 1 a case below threshold (or
never-evaluated under `--not-evaluated fail`), 2 the environment could not run
it (no runner copy, no interpreter, import failure), 3 inconclusive (only
never-evaluated cases under `warn`, a cost ceiling, or a usage limit).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.env import detect_credential, resolve_runner  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_INCONCLUSIVE, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.results import load_run_dir  # noqa: E402
from agent_sdk_skills.runner_version import findings_for, inspect_runner_copy  # noqa: E402
from agent_sdk_skills.sdk_subprocess import build_runner_cmd, describe_runner, run_project_runner  # noqa: E402

TIERS = ("pr", "nightly", "free", "run", "judge")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--tier", default="pr", choices=TIERS)
    parser.add_argument("--runs", type=int)
    parser.add_argument("--case", help="glob on case names")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true", help="print the command and start nothing")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--wait-for-reset", action="store_true")
    parser.add_argument("--not-evaluated", choices=("fail", "warn"), default="warn")
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--no-cli", action="store_true", help="skip `claude auth status`")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    layout = detect_layout(Path(args.project).expanduser())
    if not layout.project_root or not Path(layout.project_root).is_dir():
        print(f"error: {args.project} is not a project directory", file=sys.stderr)
        return EXIT_USAGE
    project = Path(layout.project_root)
    if not layout.evals or layout.evals.case_count == 0:
        print(f"error: no eval cases under {project / 'evals'}. Write some with /agent-sdk:eval-create",
              file=sys.stderr)
        return EXIT_USAGE

    copy = inspect_runner_copy(project / "evals" / "runner")
    blocking = [f for f in findings_for(copy) if f.severity == "error"]
    if blocking:
        for finding in blocking:
            print(f"error: {finding.id} {finding.message}. {finding.fix}", file=sys.stderr)
        return EXIT_USAGE
    warnings = [f for f in findings_for(copy) if f.severity == "warn"]

    credential = detect_credential(project, ask_cli=not args.no_cli)
    runner = resolve_runner(project, probe=not args.dry_run)
    if not runner.available and not args.dry_run:
        print(f"error: {runner.note}", file=sys.stderr)
        return EXIT_USAGE

    stamp = time.strftime("%Y%m%dT%H%M%S")
    out_dir = project / "evals" / "results" / stamp
    runner_args = ["run", "evals", "--tier", args.tier, "--out", str(out_dir), "--json"]
    if args.runs:
        runner_args += ["--runs", str(args.runs)]
    if args.case:
        runner_args += ["--case", args.case]
    for tag in args.tag:
        runner_args += ["--tag", tag]
    if args.max_cost_usd is not None:
        runner_args += ["--max-cost-usd", str(args.max_cost_usd)]
    if args.concurrency:
        runner_args += ["--concurrency", str(args.concurrency)]
    if args.wait_for_reset:
        runner_args.append("--wait-for-reset")

    plan = {
        "project": str(project), "tier": args.tier, "cases": layout.evals.case_count,
        "runs": args.runs, "credential": credential.describe(), "cost_basis": credential.cost_basis,
        "interpreter": describe_runner(runner),
        "runner_copy": {"version": copy.version, "status": copy.status},
        "warnings": [f"{f.id} {f.message}" for f in warnings],
        "command": " ".join(build_runner_cmd(runner, runner_args)) if runner.available
                   else f"<python> -m agent_sdk_evals {' '.join(runner_args)}",
        "results_dir": str(out_dir),
    }
    if args.dry_run:
        if not credential.ready:
            plan["warnings"].append("no credential: " + credential.describe())
        if args.json:
            print(json.dumps({"dry_run": True, **plan}, indent=2))
        else:
            print("# eval-run (dry run)\n")
            for key in ("project", "tier", "cases", "credential", "interpreter", "command", "results_dir"):
                print(f"- {key}: {plan[key]}")
            for warning in plan["warnings"]:
                print(f"- warning: {warning}")
        return EXIT_OK

    if not credential.ready:
        print("error: " + credential.describe(), file=sys.stderr)
        return EXIT_USAGE

    outcome = run_project_runner(project, runner_args, runner=runner, timeout=args.timeout)
    payload = outcome.last_json() or {}
    run_dir = load_run_dir(out_dir) if out_dir.is_dir() else None
    counts = run_dir.status_counts() if run_dir else {}
    stopped = payload.get("stopped")

    if outcome.returncode == 2 or (not run_dir and not payload):
        code = EXIT_USAGE
    elif counts.get("FAILED"):
        code = EXIT_FINDINGS
    elif stopped or outcome.returncode == 3:
        code = EXIT_INCONCLUSIVE
    elif counts.get("NOT_EVALUATED"):
        code = EXIT_FINDINGS if args.not_evaluated == "fail" else EXIT_INCONCLUSIVE
    elif outcome.returncode == 0 and counts.get("PASSED"):
        code = EXIT_OK
    else:
        code = outcome.returncode if outcome.returncode in (0, 1, 2, 3) else EXIT_USAGE

    summary = {
        **plan, "dry_run": False, "runner_exit": outcome.returncode, "status_counts": counts,
        "totals": payload.get("totals"), "stopped": stopped, "rate_limit": payload.get("rate_limit"),
        "duration_seconds": round(outcome.duration, 1), "exit_code": code,
        "stderr_tail": outcome.tail(10) if outcome.returncode not in (0, 1, 3) else "",
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"# eval-run: {project.name} tier={args.tier}\n")
        print(f"- credential: {plan['credential']}")
        print(f"- interpreter: {plan['interpreter']}")
        print(f"- results: {out_dir}")
        if counts:
            print("- statuses: " + ", ".join(f"{k.lower()}={v}" for k, v in counts.items()))
        if payload.get("totals"):
            totals = payload["totals"]
            print(f"- cost: {totals.get('cost_usd', '?')} USD ({totals.get('cost_basis') or credential.cost_basis}"
                  f"{'; an estimate' if credential.cost_basis == 'subscription' else ''})")
        if stopped:
            print(f"- stopped: {stopped}")
        if summary["stderr_tail"]:
            print("\n```\n" + summary["stderr_tail"] + "\n```")
        print(f"\nexit {code}: " + {0: "all cases passed", 1: "failures", 2: "environment error",
                                     3: "inconclusive"}[code])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
