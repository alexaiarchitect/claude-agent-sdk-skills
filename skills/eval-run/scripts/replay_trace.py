#!/usr/bin/env python3
"""Re-grade a saved trace with the free graders, without starting a session.

A trace is a complete record of what the agent did. When a grader changes, or
a case is tightened, the question "would the last run still pass" costs nothing
to answer: the runner copy's `replay` subcommand runs every free grader against
the stored events. Judge graders are reported `NOT_EVALUATED` on replay unless
`--judge` is passed, because a judge call spends.

    replay_trace.py <project> <trace.jsonl> [--case-dir DIR] [--judge] [--json]

Exit codes: 0 passed, 1 a grader failed, 2 the environment could not run it,
3 only never-evaluated graders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.env import resolve_runner  # noqa: E402
from agent_sdk_skills.report import EXIT_USAGE  # noqa: E402
from agent_sdk_skills.runner_version import inspect_runner_copy  # noqa: E402
from agent_sdk_skills.sdk_subprocess import run_project_runner  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("trace")
    parser.add_argument("--case-dir", help="the case whose graders to apply (default: inferred from the trace)")
    parser.add_argument("--judge", action="store_true", help="also run llm graders (spends judge calls)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser().resolve()
    trace = Path(args.trace).expanduser().resolve()
    if not project.is_dir() or not trace.is_file():
        print("error: project must be a directory and trace an existing file", file=sys.stderr)
        return EXIT_USAGE
    if not inspect_runner_copy(project / "evals" / "runner").present:
        print("error: DEP003 no runner copy; run /agent-sdk:agent-create to install it", file=sys.stderr)
        return EXIT_USAGE
    runner = resolve_runner(project, probe=True)
    if not runner.available:
        print(f"error: {runner.note}", file=sys.stderr)
        return EXIT_USAGE
    runner_args = ["replay", str(trace), "--json"]
    if args.case_dir:
        runner_args += ["--case-dir", args.case_dir]
    runner_args.append("--judge" if args.judge else "--graders-only")
    outcome = run_project_runner(project, runner_args, runner=runner, timeout=600)
    payload = outcome.last_json()
    if args.json:
        print(json.dumps({"runner_exit": outcome.returncode, "result": payload,
                          "stderr_tail": outcome.tail(5) if outcome.returncode == 2 else ""}, indent=2))
    else:
        print(f"# replay: {trace.name}\n")
        if payload:
            for grader in payload.get("graders") or []:
                print(f"- {grader.get('name')}: {grader.get('status')} ({grader.get('type')})")
            print(f"\nstatus: {payload.get('status')}")
        else:
            print(outcome.tail(10))
    return outcome.returncode if outcome.returncode in (0, 1, 2, 3) else EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
