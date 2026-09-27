#!/usr/bin/env python3
"""Write one eval case, with the graders its category actually needs.

The generator's job is the scaffolding nobody gets right from memory: the
frontmatter keys, the grader types that suit the category, the required fields
for each, and a prose body in every grader saying what it proves and what it
does not. The prompt body is left as a TODO, because the one thing a generator
cannot know is what this agent is for.

Which graders each category gets, and why:

| `--category` | Graders written | The argument |
|---|---|---|
| `happy` | `trajectory` (IN_ORDER) + `terminal` | the path and the clean finish; IN_ORDER tolerates extra calls, which is right when you are proving the agent *can* do the job |
| `edge` | `terminal` + `llm` | a boundary has no single right trajectory, so the expectation has to be stated in words |
| `adversarial` | `no_tool` + `llm` | restraint is proved against the trace; the judge proves the explanation. Neither alone is enough |
| `memory` | `turns` in the frontmatter + `tool_order` | a session that carries context shows it in the *order* of calls across turns |
| `regression` | `terminal` + `regex` `not_contains` | a regression case names the exact string that must never come back |

`--tool` fills the tool name into every grader that needs one; without it the
generated graders carry a `TODO-tool` placeholder that `validate_cases.py` will
report as `EVC020` until you replace it. `--rule` is the system-prompt rule the
case exists to test; it becomes the judge's criterion and the prompt's TODO.

    gen_cases.py <project> --category happy|edge|adversarial|memory|regression
                 [--tool T] [--name N] [--rule "text"] [--dry-run] [--force] [--json]

Exit codes: 0 written or planned, 1 written with warnings (placeholder tool,
files skipped), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import rubrics  # noqa: E402
from agent_sdk_skills.evalcase import CATEGORIES  # noqa: E402
from agent_sdk_skills.frontmatter import dump  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan  # noqa: E402

PLACEHOLDER_TOOL = "TODO-tool"

PROMPT_TODO = (
    "TODO: replace this with the request that exercises the behaviour above.\n"
    "One behaviour per case — a prompt that asks for three things cannot tell\n"
    "you which one broke. Phrase it the way a user would, not the way the\n"
    "system prompt does; a case written in the agent's own words tests the\n"
    "agent's memory of its instructions, not its judgement.\n"
)

_NOTE_TERMINAL = """Proves the session finished its loop cleanly: `subtype: success`, not
`error_max_turns`, `error_during_execution` or `error_max_budget_usd`.

It does not prove the agent did the work. A run that declined and stopped ends
just as cleanly as one that succeeded — this is the floor the other graders in
this case stand on, and when it fails the others are usually noise."""

_NOTE_TRAJECTORY = """Proves the agent walked the expected path: each named call happened, in this
order, with the named arguments. `args_match: subset` lets the model send extra
arguments; the ones written here must match.

It does not prove the answer was right. An agent can walk the golden path and
still summarize it wrongly — that is the other half of the trajectory x answer
quadrant, and it needs a `terminal`, `regex` or `llm` grader beside this one.
`IN_ORDER` also allows calls in between; switch to `EXACT` when the case is
about restraint rather than capability."""

_NOTE_TOOL_ORDER = """Proves one call happened before another at least once. Across a multi-turn
case that is the cheapest evidence the session carried context: the second turn
acted on what the first turn established.

It does not prove anything happened in between, that either call was correct,
or that the agent remembered the *content* — only the relative order. Pair it
with a `regex` or `llm` grader on the final reply when the content matters."""

_NOTE_REGEX_REGRESSION = """Proves the exact string that caused the bug does not come back. A regression
case is a record that someone once saw this go wrong, so the pattern should be
the literal symptom, not a paraphrase of it.

It does not prove the underlying cause was fixed — a model can avoid one
phrasing and reproduce the fault in another. Keep the case narrow and add a
second grader for what the agent should say instead."""


#: Words that make `evalcase` read a case name as restraint-shaped. A rule is
#: often phrased as a prohibition even when the case under it is a happy path,
#: so they are dropped from every generated name except an adversarial one —
#: otherwise the generator plants its own EVC041.
_RESTRAINT_WORDS = frozenset({
    "no", "not", "never", "refuse", "refuses", "refusal", "deny", "denies",
    "reject", "rejects", "without", "cannot", "dont",
})


def _slug(text: str, *, limit: int = 5, drop_restraint: bool = False) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2]
    if drop_restraint:
        words = [w for w in words if w not in _RESTRAINT_WORDS]
    return "-".join(words[:limit])


def _default_name(category: str, tool: str | None, rule: str | None) -> str:
    drop = category != "adversarial"
    stem = (_slug(rule, drop_restraint=drop)
            or (_slug(tool.split("__")[-1], drop_restraint=drop) if tool else ""))
    return f"{category}-{stem}" if stem else f"{category}-case"


def _case_meta(name: str, category: str, tool: str | None) -> dict:
    meta: dict = {"name": name, "category": category,
                  "tags": [category], "runs": 3, "max_turns": 6}
    if category == "memory":
        meta["turns"] = [
            "TODO: the first turn — establish something the agent must remember.",
            "TODO: the second turn — refer to it without naming it again.",
        ]
    if category == "adversarial":
        meta["runs"] = 5
    return meta


def _graders_for(category: str, tool: str, rule: str | None) -> list[tuple[str, str]]:
    """`(filename, file text)` for every grader this category needs."""
    out: list[tuple[str, str]] = []
    claim = rule or "the agent does what this case asks"

    if category == "happy":
        out.append(("follows_the_path.md", dump(
            {"name": "follows_the_path", "type": "trajectory",
             "match": "IN_ORDER", "args_match": "subset",
             "expected": [{"tool": tool, "args": {"TODO_arg": "TODO value"}}]},
            _NOTE_TRAJECTORY)))
        out.append(("ends_cleanly.md", dump(
            {"name": "ends_cleanly", "type": "terminal", "subtype": "success"},
            _NOTE_TERMINAL)))

    elif category == "edge":
        out.append(("ends_cleanly.md", dump(
            {"name": "ends_cleanly", "type": "terminal", "subtype": "success"},
            _NOTE_TERMINAL)))
        criteria = rubrics.build_positive_rubric(
            claim,
            evidence="the final reply",
            fail_clause="the reply guesses, invents a value, or answers as if the edge case "
                        "had not happened")
        out.append((f"{rubrics.suggest_grader_slug(criteria)}.md", rubrics.grader_file(
            rubrics.suggest_grader_slug(criteria), criteria,
            focus="the final reply only", samples=3,
            body_note="Proves the agent handled the boundary the way this case says it should. "
                      "An edge case has no single right trajectory, so the expectation has to "
                      "be stated in words.\n\nIt does not prove the agent took a sensible route "
                      "to get there, and a judge verdict is a distribution: `samples: 3` with "
                      "majority voting is what stops a borderline reply flipping the case.")))

    elif category == "adversarial":
        out.append(("no_forbidden_call.md", dump(
            {"name": "no_forbidden_call", "type": "no_tool", "tools": [tool]},
            f"Proves the agent did not call `{tool}` — the action this case tries to provoke.\n"
            "This is the half of the case that cannot be talked out of: it reads the trace, "
            "not the reply.\n\n"
            "It does not prove the agent refused for the right reason, or said anything useful; "
            "an agent that crashed or stalled also passes. The `llm` grader beside it carries "
            "that half, and neither is meaningful alone.")))
        criteria = rubrics.build_restraint_rubric(
            tool, rule or "the request would break the rule this case tests",
            instead="explain why, and offer the action that would be allowed")
        out.append((f"{rubrics.suggest_grader_slug(criteria)}.md", rubrics.grader_file(
            rubrics.suggest_grader_slug(criteria), criteria,
            focus="the final reply only", samples=3,
            body_note="Proves the refusal is usable by the person who asked: a refusal with no "
                      "reason is indistinguishable from a bug.\n\nIt does not prove the agent "
                      "actually held back — a model can write a convincing refusal and still "
                      "have called the tool. `no_forbidden_call` is what proves the restraint.")))

    elif category == "memory":
        out.append(("second_turn_follows_first.md", dump(
            {"name": "second_turn_follows_first", "type": "tool_order",
             "before": tool, "after": tool},
            "TODO: set `before` and `after` to the two different tools the two turns should "
            "call, in that order. They are the same placeholder here because the generator "
            "does not know this agent's tools.\n\n" + _NOTE_TOOL_ORDER)))

    elif category == "regression":
        out.append(("ends_cleanly.md", dump(
            {"name": "ends_cleanly", "type": "terminal", "subtype": "success"},
            _NOTE_TERMINAL)))
        out.append(("symptom_is_gone.md", dump(
            {"name": "symptom_is_gone", "type": "regex",
             "pattern": "TODO: the literal string the bug produced",
             "match": "not_contains", "target": "last_message"},
            _NOTE_REGEX_REGRESSION)))

    return out


def build_plan(evals: Path, name: str, category: str, tool: str, rule: str | None,
               *, force: bool) -> WritePlan:
    plan = WritePlan()
    case_dir = evals / name
    header = (f"Behaviour under test: {rule}\n\n" if rule else "")
    # A case driven by `turns` ignores its body (EVC002 info), so a multi-turn
    # case is written with none and its TODOs live in the turns themselves.
    body = "" if category == "memory" else header + PROMPT_TODO
    plan.add(case_dir / "prompt.md",
             dump(_case_meta(name, category, tool), body),
             force=force,
             reason="the body is a TODO: only the author knows what this agent does"
                    if body else "multi-turn: the `turns` list is the prompt, the body is ignored")
    for filename, text in _graders_for(category, tool, rule):
        plan.add(case_dir / "graders" / filename, text, force=force)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--category", required=True, choices=CATEGORIES)
    parser.add_argument("--tool", help="the tool the graders name, e.g. mcp__library__reserve_book")
    parser.add_argument("--name", help="case directory name (default: derived from the rule)")
    parser.add_argument("--rule", help="the system-prompt rule this case tests")
    parser.add_argument("--force", action="store_true", help="replace files that already exist")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    evals = project / "evals"

    tool = args.tool or PLACEHOLDER_TOOL
    name = args.name or _default_name(args.category, args.tool, args.rule)
    plan = build_plan(evals, name, args.category, tool, args.rule, force=args.force)

    warnings: list[str] = []
    if not args.tool:
        warnings.append(
            f"no --tool given, so the graders name {PLACEHOLDER_TOOL!r}. `validate_cases.py` "
            "will report EVC020 until you replace it with a real tool name — MCP tools reach "
            "the model as `mcp__<server>__<tool>` and the trace records that form.")
    if args.rule and args.category != "adversarial" and rubrics.is_restraint_criteria(args.rule):
        warnings.append(
            f"--rule reads as a prohibition but --category is {args.category!r}. A rule the "
            "agent must NOT break needs an adversarial case with a `no_tool` grader; without "
            "one `validate_cases.py` reports EVC041 (restraint-shaped case, no restraint "
            "check). Re-run with --category adversarial, or rephrase the rule.")
    if args.category == "adversarial" and not args.rule:
        warnings.append(
            "no --rule given: the judge criterion says 'the request would break the rule this "
            "case tests', which is not something a judge can evaluate. Name the rule.")
    skipped = [i.path for i in plan.items if i.action == "skip"]
    if skipped:
        warnings.append(f"{len(skipped)} file(s) already existed and were left alone "
                        "(pass --force to replace)")

    written = [] if args.dry_run else plan.apply()
    payload = {
        "project": str(project), "case": name, "category": args.category,
        "tool": tool, "rule": args.rule, "dry_run": args.dry_run,
        "plan": plan.to_dict(), "written": written, "warnings": warnings,
        "next": [
            f"fill in the TODOs in evals/{name}/prompt.md and its graders",
            f"validate: ../eval-review/scripts/validate_cases.py {project}",
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# gen_cases: {args.category} case `{name}`\n")
        print(plan.to_md())
        print("\n_Dry run: nothing was written._" if args.dry_run
              else f"\n_Wrote {len(written)} file(s)._")
        for warning in warnings:
            print(f"\n- warning: {warning}")
        print("\nNext: " + "; ".join(payload["next"]))
    return EXIT_FINDINGS if warnings else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
