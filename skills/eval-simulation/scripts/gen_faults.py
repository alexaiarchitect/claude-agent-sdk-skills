#!/usr/bin/env python3
"""Write a faults file in the shape `agent_sdk_evals/faults.py` actually loads.

Fault injection is hooks, not mocks: a `PreToolUse` or `PostToolUse` callback
that denies a call, rewrites its input, replaces its output or makes it slow. Two
measured facts decide the file's shape:

* `HookMatcher` has **no** `probability` field, so per-tool probability lives
  inside the callback and is driven by a seeded RNG. That is why `seed` is a
  top-level key: a flaky-looking failure has to be reproducible, and the runner
  folds the run index into the seed so run 2 is a different but repeatable draw.
* Matchers on one event fire **concurrently**, so no fault may depend on another
  having run first. One entry per tool, and nothing chained.

    gen_faults.py <project> --tool NAME [--error "..."] [--latency-ms N]
                  [--probability P] [--seed N] [--out evals/faults/<name>.json]
                  [--dry-run] [--force] [--json]

`--error` writes a `PostToolUse` / `error_output` entry: the tool runs and its
result is replaced. `--latency-ms` alone writes a `PreToolUse` / `latency` entry:
the call is delayed and then allowed. Given both, one entry carries both — the
runner sleeps before it applies the action either way.

`--probability` is the share of matching calls the fault hits, in [0, 1]
(SIM002). Keep it at 1.0 in a dedicated case, where the assertion is about the
one thing that went wrong; a probability below 1 belongs in a soak run, not in a
gate.

Exit codes: 0 written (or planned), 1 nothing to write, 2 usage — including a
probability outside [0, 1] (SIM002) and a fault that injects nothing (SIM021).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan, dumps_json  # noqa: E402

DEFAULT_SEED = 20260930

#: `faults.ACTIONS`.
ACTIONS = ("deny", "updated_input", "error_output", "latency", "allow")


def slug_for(tool: str) -> str:
    """`mcp__library__lookup_book` -> `library-lookup-book`."""
    text = re.sub(r"^mcp__", "", tool)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or "fault"


def fault_entry(tool: str, *, error: str | None, latency_ms: int, probability: float,
                fault_id: str) -> dict[str, Any]:
    """One `faults[]` entry: exactly the keys `faults.load_plan` reads."""
    if error:
        entry: dict[str, Any] = {
            "id": fault_id,
            "event": "PostToolUse",
            "tool": tool,
            "action": "error_output",
            "probability": probability,
            "reason": error,
            "updated_tool_output": error,
        }
        if latency_ms:
            entry["latency_ms"] = latency_ms
        return entry
    return {
        "id": fault_id,
        "event": "PreToolUse",
        "tool": tool,
        "action": "latency",
        "probability": probability,
        "reason": f"injected latency of {latency_ms} ms on {tool}",
        "latency_ms": latency_ms,
    }


def faults_file(tool: str, *, error: str | None, latency_ms: int, probability: float,
                seed: int, fault_id: str) -> dict[str, Any]:
    return {
        "seed": seed,
        "faults": [fault_entry(tool, error=error, latency_ms=latency_ms,
                               probability=probability, fault_id=fault_id)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", help="the agent project whose evals/ to write into")
    parser.add_argument("--tool", required=True,
                        help="the tool to break: an exact name or a regex the runner "
                             "fullmatches, e.g. mcp__library__.*")
    parser.add_argument("--error", help="the error text the tool's result is replaced with")
    parser.add_argument("--latency-ms", type=int, default=0, help="delay before the call")
    parser.add_argument("--probability", type=float, default=1.0,
                        help="share of matching calls hit, in [0, 1] (default 1.0)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="RNG seed; the runner adds the run index to it")
    parser.add_argument("--id", dest="fault_id", help="the fault id a hook_event grader names")
    parser.add_argument("--out", help="path to write (default: <evals>/faults/<slug>.json)")
    parser.add_argument("--force", action="store_true", help="replace an existing faults file")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    def refuse(code: str, message: str) -> int:
        if args.json:
            print(json.dumps({"error": code, "message": message}, indent=2))
        else:
            print(f"{code}: {message}", file=sys.stderr)
        return EXIT_USAGE

    project = Path(args.project).expanduser()
    if not project.exists():
        print(f"no such project: {project}", file=sys.stderr)
        return EXIT_USAGE

    if not 0.0 <= args.probability <= 1.0:
        return refuse("SIM002", f"probability {args.probability} is outside [0, 1]; it is the "
                                "share of matching calls the fault hits")
    if args.latency_ms < 0:
        return refuse("SIM002", f"--latency-ms must be non-negative, got {args.latency_ms}")
    if not args.error and not args.latency_ms:
        return refuse("SIM021", "a fault that neither replaces a result nor delays one injects "
                                "nothing. Pass --error \"catalog service timed out\", "
                                "--latency-ms 2500, or both")

    slug = slug_for(args.tool)
    fault_id = args.fault_id or (f"{slug}-error" if args.error else f"{slug}-latency")

    layout = detect_layout(project)
    evals_dir = Path(layout.evals.dir) if layout.evals else project / "evals"
    out = Path(args.out).expanduser() if args.out else evals_dir / "faults" / f"{slug}.json"

    data = faults_file(args.tool, error=args.error, latency_ms=args.latency_ms,
                       probability=args.probability, seed=args.seed, fault_id=fault_id)

    plan = WritePlan()
    plan.add(out, dumps_json(data), force=args.force,
             reason=f"{data['faults'][0]['action']} on {args.tool} at p={args.probability}")

    written: list[str] = []
    if not args.dry_run:
        written = plan.apply()

    payload = {
        "faults": data,
        "out": str(out),
        "dry_run": args.dry_run,
        "plan": plan.to_dict(),
        "written": written,
        "grader_hint": {
            "type": "hook_event",
            "fault_id": fault_id,
            "note": "a hook_event grader with this fault_id proves the fault fired; without "
                    "one a fault run only proves the agent survived something unrecorded",
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(plan.to_md())
        if args.dry_run:
            print("\n--- faults (not written) ---")
            print(dumps_json(data))
        else:
            for path in written:
                print(f"wrote {path}")
        print(f"\nUse it from a case: `faults: faults/{out.name}`")
        print(f"Assert it fired: a `hook_event` grader with `fault_id: {fault_id}`.")
        if args.probability < 1.0:
            print(f"p={args.probability}: seeded from {args.seed} + the run index, so a failure "
                  "reproduces; keep p=1.0 in anything that gates a merge.")

    if not args.dry_run and not written:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
