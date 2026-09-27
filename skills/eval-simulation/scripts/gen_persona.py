#!/usr/bin/env python3
"""Write `evals/personas/<name>.json` in the shape the runner actually loads.

A simulated user is a second model, on its own session, with no tools, writing
the next thing a person would say. It is the only way to test a conversation
nobody scripted — and the easiest thing in an eval suite to fool yourself with,
because a simulator that drifts off its persona produces a transcript that
proves nothing.

Two fields do the work:

`constraints`   the behaviour instructions. The runner renders them under
                "Rules you follow no matter what", so each one is an imperative
                the simulator obeys: *never volunteer your member id*, not
                *the user is reluctant*.
`violation_rubrics`
                the judge's check on the **simulated user**, not on the agent.
                A violated rubric makes the case NOT_EVALUATED rather than
                FAILED, because the run measured a broken simulator. Writing
                them about the agent is the classic mistake: that is what the
                case's own graders are for.

So this refuses to write a persona with no violation rubrics (SIM001): an
unsupervised simulator will eventually give the agent the answer, and the case
will pass for the wrong reason without anyone noticing.

    gen_persona.py <project> --name NAME [--goal "..."] [--style "..."]
                   [--opening "..."] [--behaviour "..."]... [--violation "..."]...
                   [--max-turns N] [--stop-marker DONE] [--model M]
                   [--out path] [--dry-run] [--force] [--json]

Exit codes: 0 written (or planned), 1 nothing to write (the file exists and
`--force` was not passed), 2 usage — including no `--violation`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.env import classify_model_id  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan, dumps_json  # noqa: E402

#: `simulate.DEFAULT_MAX_USER_TURNS` / `DEFAULT_STOP_MARKER`.
DEFAULT_MAX_USER_TURNS = 4
DEFAULT_STOP_MARKER = "DONE"

DEFAULT_STYLE = "plain, one or two sentences per turn, no narration"


def persona_dict(
    name: str,
    *,
    goal: str,
    style: str,
    opening: str | None,
    behaviours: list[str],
    violations: list[str],
    max_turns: int,
    stop_marker: str,
    model: str | None,
) -> dict[str, Any]:
    """Exactly the keys `simulate.Persona.from_dict` reads, in its order.

    Anything else is silently ignored by the runner, so nothing else is written.
    """
    data: dict[str, Any] = {
        "name": name,
        "goal": goal,
        "style": style,
    }
    if model:
        data["model"] = model
    if opening:
        data["opening"] = opening
    data["max_user_turns"] = max_turns
    data["stop_marker"] = stop_marker
    data["constraints"] = behaviours
    data["violation_rubrics"] = violations
    return data


def default_behaviours(name: str) -> list[str]:
    return [
        f"Stay in character as {name} for the whole conversation.",
        "Say one thing per turn. Never narrate, never use quotation marks.",
        "Never do the agent's work for it: do not name a tool, and do not "
        "supply a detail it has not asked for.",
    ]


def default_violations(name: str) -> list[str]:
    return [
        f"every turn is something {name} would plausibly say, in character",
        "the user never states a fact the agent has not asked for and the "
        "persona was not given",
        "the user never instructs the agent on which tool to call",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", help="the agent project whose evals/ to write into")
    parser.add_argument("--name", required=True, help="the persona, e.g. impatient-renewer")
    parser.add_argument("--goal", help="what this person is trying to get done")
    parser.add_argument("--style", default=DEFAULT_STYLE, help="how they speak")
    parser.add_argument("--opening", help="their first turn, verbatim (skips one judge call)")
    parser.add_argument("--behaviour", "--behavior", dest="behaviours", action="append",
                        default=[], metavar="TEXT",
                        help="an imperative the simulator must obey; repeatable")
    parser.add_argument("--violation", dest="violations", action="append", default=[],
                        metavar="TEXT",
                        help="a rubric the simulated USER's turns must satisfy; repeatable, "
                             "and required")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_USER_TURNS,
                        help=f"user turns before the conversation stops (default {DEFAULT_MAX_USER_TURNS})")
    parser.add_argument("--stop-marker", default=DEFAULT_STOP_MARKER,
                        help=f"what the simulator says when it is done (default {DEFAULT_STOP_MARKER})")
    parser.add_argument("--model", help="the model that plays the user (default: the judge tier's)")
    parser.add_argument("--out", help="path to write (default: <evals>/personas/<name>.json)")
    parser.add_argument("--defaults", action="store_true",
                        help="fill --behaviour and --violation with a starting set when none given")
    parser.add_argument("--force", action="store_true", help="replace an existing persona")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.exists():
        print(f"no such project: {project}", file=sys.stderr)
        return EXIT_USAGE

    violations = [v.strip() for v in args.violations if v.strip()]
    if not violations and args.defaults:
        violations = default_violations(args.name)
    if not violations:
        message = (
            "SIM001: a persona with no `violation_rubrics` is unsupervised. Nothing would "
            "notice a simulator that drifted off character and handed the agent the answer, "
            "so the case would pass for a reason that has nothing to do with the agent. "
            "Pass --violation \"the user never states a fact the agent has not asked for\" "
            "(repeatable), or --defaults for a starting set."
        )
        if args.json:
            print(json.dumps({"error": "SIM001", "message": message}, indent=2))
        else:
            print(message, file=sys.stderr)
        return EXIT_USAGE

    if args.max_turns < 1:
        message = f"SIM005: --max-turns must be at least 1, got {args.max_turns}"
        if args.json:
            print(json.dumps({"error": "SIM005", "message": message}, indent=2))
        else:
            print(message, file=sys.stderr)
        return EXIT_USAGE

    behaviours = [b.strip() for b in args.behaviours if b.strip()] or default_behaviours(args.name)

    model_note = None
    if args.model:
        grade = classify_model_id(args.model)
        if grade in ("retired", "retiring", "unknown"):
            model_note = f"SIM006: persona model {args.model!r} is {grade}"

    layout = detect_layout(project)
    evals_dir = Path(layout.evals.dir) if layout.evals else project / "evals"
    out = Path(args.out).expanduser() if args.out else evals_dir / "personas" / f"{args.name}.json"

    persona = persona_dict(
        args.name,
        goal=args.goal or f"get what {args.name} came for, in their own words",
        style=args.style,
        opening=args.opening,
        behaviours=behaviours,
        violations=violations,
        max_turns=args.max_turns,
        stop_marker=args.stop_marker,
        model=args.model,
    )

    plan = WritePlan()
    plan.add(out, dumps_json(persona), force=args.force,
             reason=f"{args.max_turns} user turn(s), {len(violations)} violation rubric(s)")

    written: list[str] = []
    if not args.dry_run:
        written = plan.apply()

    payload = {
        "persona": persona,
        "out": str(out),
        "dry_run": args.dry_run,
        "plan": plan.to_dict(),
        "written": written,
        "cost": {
            "judge_calls_per_run": args.max_turns - (1 if args.opening else 0),
            "note": "one judge-tier call per generated user turn, plus the agent's own "
                    "session, plus one judge call per violation rubric",
        },
    }
    if model_note:
        payload["note"] = model_note

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(plan.to_md())
        if model_note:
            print(f"\n{model_note}")
        if args.dry_run:
            print("\n--- persona (not written) ---")
            print(dumps_json(persona))
        else:
            for path in written:
                print(f"wrote {path}")
        print(f"\nCost per run: up to {payload['cost']['judge_calls_per_run']} judge-tier "
              f"call(s) for the user's turns, plus {len(violations)} for the rubrics.")
        print(f"Use it from a case: `simulated_user: personas/{args.name}.json`")

    if not args.dry_run and not written:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
