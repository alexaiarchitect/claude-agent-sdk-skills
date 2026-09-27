#!/usr/bin/env python3
"""Turn a reviewed run into a case: the golden-trace workflow.

The cheapest good case is one you have already seen work. Run the agent, read
the trace, decide the path it took was the path you want, and freeze it. This
script does the freezing: the first user prompt becomes `prompt.md`, the
tool-call sequence becomes a `trajectory` grader, and how the run ended becomes
a `terminal` grader.

Two things it does deliberately:

* **Synthetic calls are dropped.** The CLI reports `StructuredOutput` and
  `ToolSearch` as tool calls, but neither is a decision the agent made — one is
  how `output_format` is delivered, the other is deferred MCP tool loading. A
  trajectory that includes them fails on any machine that loads tools
  differently. `trajectory.calls_from_events` drops them for us.
* **It never overwrites a case.** A case directory that already exists is
  skipped, every file of it, and the plan says so. Re-freezing a case is a
  decision, not a default: the existing expectation may be the one that is
  right and the new run the one that regressed.

Read the trajectory before you commit it. A golden trace is a specification,
and a trace that happens to pass is not the same as a path you want defended:
a redundant lookup, a retry after an error, a tool called twice because the
first result was ignored — all of those freeze into the expectation and will
fail every future run that does the sensible thing instead.

    trace_to_case.py <trace.jsonl> --name N [--project P]
                     [--match EXACT|IN_ORDER] [--args-match subset|exact|ignore]
                     [--dry-run] [--json]

`--match EXACT` is the strict form: no extra calls anywhere. Use it for
restraint cases. `IN_ORDER` (the default) allows calls in between, which is the
right tolerance for a capability case.

Exit codes: 0 written or planned, 1 the case already exists or the trace has no
tool calls, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.frontmatter import dump  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan  # noqa: E402
from agent_sdk_skills.trace import events_of, load_trace, result_event  # noqa: E402
from agent_sdk_skills.trajectory import (  # noqa: E402
    ARGS_MODES, DEFAULT_ARGS_MATCH, MATCH_EXACT, MATCH_IN_ORDER, calls_from_events,
)

_TRAJECTORY_NOTE = """Frozen from a reviewed run: {trace}

Proves the agent takes this path. Each call is named with the arguments the
reviewed run sent; `args_match: {args_match}` decides how strictly they are
compared, and `match: {match}` decides whether calls in between are allowed.

It does not prove the answer was right — an agent can walk this exact path and
summarize it wrongly. It also does not prove the path is the *best* one: it is
the path one run took on one day, and everything in it is now a requirement.
Delete the steps you would not defend in review."""

_TERMINAL_NOTE = """Proves the run ends the way the reviewed run ended (`{subtype}`).

It does not prove the work was done; `success` only means the loop finished
without erroring. It is here because a trajectory grader on its own passes a
run that made the right calls and then hit the turn limit."""


def _first_prompt(events) -> str:
    for event in events_of(events, "user"):
        text = (event.text or "").strip()
        if text:
            return text
    return ""


def build_plan(trace_path: Path, case_dir: Path, *, match: str, args_match: str,
               name: str) -> tuple[WritePlan, dict]:
    events = load_trace(trace_path)
    calls = calls_from_events(events)
    prompt = _first_prompt(events)
    result = result_event(events)
    subtype = (result.get("subtype") if result else None) or "success"

    turns = [e.text for e in events_of(events, "user") if (e.text or "").strip()]
    meta: dict = {"name": name, "category": "regression", "tags": ["regression", "golden-trace"],
                  "runs": 3}
    if len(turns) > 1:
        meta["turns"] = turns
    body = "" if len(turns) > 1 else prompt

    plan = WritePlan()
    exists = case_dir.exists()
    plan.add(case_dir / "prompt.md", dump(meta, body),
             reason="frozen from the trace's first user event"
                    if not exists else "case exists; nothing is overwritten from a trace")
    plan.add(case_dir / "graders" / "follows_the_golden_path.md", dump(
        {"name": "follows_the_golden_path", "type": "trajectory",
         "match": match, "args_match": args_match,
         "expected": [{"tool": call.tool, "args": call.args} if call.args
                      else {"tool": call.tool} for call in calls]},
        _TRAJECTORY_NOTE.format(trace=trace_path.name, match=match, args_match=args_match)))
    plan.add(case_dir / "graders" / "ends_as_before.md", dump(
        {"name": "ends_as_before", "type": "terminal", "subtype": subtype},
        _TERMINAL_NOTE.format(subtype=subtype)))

    if exists:
        # The whole case is refused, not just the files that happen to collide:
        # a half-frozen case — this run's trajectory beside the old prompt —
        # would be worse than either version on its own.
        for item in plan.items:
            item.action = "skip"
            item.reason = ("the case directory already exists; re-freezing is a decision, "
                           "so nothing here is written")

    summary = {
        "trace": str(trace_path),
        "events": len(events),
        "calls": [call.to_dict() for call in calls],
        "dropped_synthetic": len([e for e in events_of(events, "tool_use") if e.synthetic]),
        "prompt_chars": len(prompt),
        "turns": len(turns),
        "terminal_subtype": subtype,
        "case_existed": exists,
    }
    return plan, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace")
    parser.add_argument("--name", required=True, help="case directory name")
    parser.add_argument("--project", default=".", help="project root (the case lands in evals/)")
    parser.add_argument("--match", choices=(MATCH_EXACT, MATCH_IN_ORDER), default=MATCH_IN_ORDER)
    parser.add_argument("--args-match", choices=ARGS_MODES, default=DEFAULT_ARGS_MATCH)
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    trace_path = Path(args.trace).expanduser()
    if not trace_path.is_file():
        print(f"error: {trace_path} is not a file", file=sys.stderr)
        return EXIT_USAGE
    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    case_dir = project / "evals" / args.name

    try:
        plan, summary = build_plan(trace_path, case_dir, match=args.match,
                                   args_match=args.args_match, name=args.name)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {trace_path}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    warnings: list[str] = []
    if not summary["calls"]:
        warnings.append(
            "the trace has no non-synthetic tool calls, so the trajectory grader expects "
            "nothing and passes any run. Either the agent used no tools, or this trace is an "
            "imported session with the tool blocks stripped — check before committing it.")
    if summary["case_existed"]:
        warnings.append(
            f"evals/{args.name}/ already exists; nothing was overwritten. Re-freezing a case "
            "is a decision: the old expectation may be the right one and this run the "
            "regression. Delete the directory yourself if you mean to replace it.")
    if not summary["prompt_chars"] and not summary["turns"]:
        warnings.append("no user event in the trace, so prompt.md has an empty body (EVC001)")
    if args.match == MATCH_EXACT and len(summary["calls"]) > 6:
        warnings.append(
            f"EXACT over {len(summary['calls'])} calls is a brittle expectation: every future "
            "run must make exactly these calls and no others. IN_ORDER is usually what you want "
            "for a path this long.")

    written = [] if args.dry_run else plan.apply()
    payload = {**summary, "case": args.name, "case_dir": str(case_dir),
               "match": args.match, "args_match": args.args_match,
               "dry_run": args.dry_run, "plan": plan.to_dict(),
               "written": written, "warnings": warnings}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# trace_to_case: `{args.name}` from {trace_path.name}\n")
        print(f"- events: {summary['events']}, tool calls kept: {len(summary['calls'])}, "
              f"synthetic dropped: {summary['dropped_synthetic']}")
        print(f"- terminal subtype: `{summary['terminal_subtype']}`")
        for call in summary["calls"]:
            print(f"  - `{call['tool']}` {json.dumps(call['args'])}")
        print()
        print(plan.to_md())
        print("\n_Dry run: nothing was written._" if args.dry_run
              else f"\n_Wrote {len(written)} file(s)._")
        for warning in warnings:
            print(f"\n- warning: {warning}")
    return EXIT_FINDINGS if warnings else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
