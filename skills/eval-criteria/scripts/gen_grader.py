#!/usr/bin/env python3
"""Write one grader file, with the fields its type actually requires.

Each grader type has a small, exact contract — `trajectory` needs `expected`,
`terminal` needs a `subtype` or a `terminal_reason`, `budget` needs at least one
ceiling — and getting it wrong is an `EVC011` discovered at validation time.
This writes the right frontmatter for the type you ask for and a prose body
saying what the check proves and, more usefully, what it does not.

For `--type llm` it writes a PASS/FAIL skeleton in the shape a judge can act
on, then lints it with the same rules `/agent-sdk:eval-review` applies:

* one claim per criterion — a compound question gets a compound answer;
* an explicit FAIL clause naming the near-misses, because "otherwise FAIL" puts
  the burden on the judge's imagination;
* no graded language ("mostly", "reasonably", "a good answer") — there is no
  partial credit, so a scale in the wording just moves the threshold into the
  judge's head;
* nothing unobservable ("the agent understood", "intended to") — a judge sees
  text, not intent.

The skeleton is a skeleton. It will carry a TODO and the lint will say so; the
point is to start from the right shape instead of from a blank file.

    gen_grader.py <case-dir> --type T [--name N] [--tool X] [--pattern P]
                  [--reference R] [--max-cost-usd X] [--max-turns N]
                  [--event E] [--subtype S] [--criteria "text"]
                  [--force] [--dry-run] [--json]

Exit codes: 0 written or planned and complete, 1 written with findings — a
missing field, a criterion the linter objects to, or a TODO placeholder still
in the file — 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import rubrics  # noqa: E402
from agent_sdk_skills.frontmatter import dump  # noqa: E402
from agent_sdk_skills.graders import GRADER_CATALOG, spec_for, validate_grader  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, Finding, GapReport,
)
from agent_sdk_skills.templating import WritePlan  # noqa: E402

TODO_TOOL = "TODO-tool"
TODO_TEXT = "TODO"


def _note(spec) -> str:
    """The prose every grader file carries: the claim, then the limit."""
    return (f"Proves: {spec.description}.\n\n"
            f"It does not prove {spec.not_proven}.\n\n"
            "TODO: replace both paragraphs with what this check means in *this* case. "
            "The second one is the useful half — it is what tells the next reader which "
            "other grader has to exist beside this one.")


def build_grader(grader_type: str, args) -> tuple[str, dict, str]:
    """`(slug, frontmatter, body)` for one grader."""
    spec = spec_for(grader_type)
    assert spec is not None
    tool = args.tool or TODO_TOOL
    meta: dict = {"name": args.name or grader_type, "type": grader_type}
    body = _note(spec)

    if grader_type == "llm":
        criteria = args.criteria or (
            f"(TODO) one claim about {tool if args.tool else 'the agent'}, phrased so a "
            "reader of the evidence can answer it yes or no")
        text = rubrics.build_positive_rubric(
            criteria,
            evidence="the final reply",
            fail_clause="the evidence does not show it, or shows it only by implication")
        slug = args.name or rubrics.suggest_grader_slug(text)
        return slug, {}, rubrics.grader_file(
            slug, text, focus=args.focus, samples=args.samples,
            body_note="Proves the judge's one question about this run.\n\n"
                      "It does not prove that another sample would agree: a judge verdict is a "
                      "distribution, so majority voting over an odd number of samples is what "
                      "keeps a borderline reply from flipping the case. And it reads text, so "
                      "it cannot prove what the agent did — a trace-level grader has to.")

    if grader_type == "regex":
        meta["pattern"] = args.pattern or f"{TODO_TEXT}: the expression to look for"
        meta["match"] = args.match or "contains"
        meta["target"] = args.target or "last_message"
    elif grader_type == "tool_used":
        meta["tool"] = tool
        meta["min"] = 1
    elif grader_type == "tool_order":
        meta["before"] = tool
        meta["after"] = args.after or TODO_TOOL
    elif grader_type == "file_exists":
        meta["path"] = args.path or f"{TODO_TEXT}/*.json"
    elif grader_type == "trajectory":
        meta["match"] = args.match_mode or "IN_ORDER"
        meta["args_match"] = args.args_match or "subset"
        meta["expected"] = [{"tool": tool}]
    elif grader_type == "structured_output":
        meta["schema"] = {"type": "object", "required": [f"{TODO_TEXT}_field"],
                          "properties": {f"{TODO_TEXT}_field": {"type": "string"}}}
    elif grader_type == "budget":
        if args.max_cost_usd is not None:
            meta["max_cost_usd"] = args.max_cost_usd
        if args.max_turns is not None:
            meta["max_turns"] = args.max_turns
        if "max_cost_usd" not in meta and "max_turns" not in meta:
            meta["max_cost_usd"] = 0.50
        meta["informational"] = True
    elif grader_type == "hook_event":
        meta["event"] = args.event or "PreToolUse"
        meta["min"] = 1
    elif grader_type == "final_text":
        meta["reference"] = args.reference or f"{TODO_TEXT}: the text the reply should carry"
        meta["mode"] = args.match or "contains"
    elif grader_type == "no_tool":
        meta["tools"] = [tool]
    elif grader_type == "terminal":
        meta["subtype"] = args.subtype or "success"

    return meta["name"], meta, body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_dir", help="the case directory (graders/ is created under it)")
    parser.add_argument("--type", dest="grader_type", required=True, choices=tuple(GRADER_CATALOG))
    parser.add_argument("--name", help="grader name and filename stem")
    parser.add_argument("--tool", help="tool name, fully qualified: mcp__<server>__<tool>")
    parser.add_argument("--after", help="tool_order: the tool that must come second")
    parser.add_argument("--pattern", help="regex: the expression")
    parser.add_argument("--match", help="regex: contains|not_contains|count:N; final_text: mode")
    parser.add_argument("--match-mode", help="trajectory: EXACT|IN_ORDER|ANY_ORDER")
    parser.add_argument("--args-match", help="trajectory: exact|subset|ignore")
    parser.add_argument("--target", help="what the check reads")
    parser.add_argument("--path", help="file_exists: the glob")
    parser.add_argument("--reference", help="final_text: the reference text")
    parser.add_argument("--event", help="hook_event: a Python SDK HookEvent value")
    parser.add_argument("--subtype", help="terminal: the result subtype")
    parser.add_argument("--criteria", help="llm: the claim, in your own words")
    parser.add_argument("--focus", help="llm: what the judge should ignore")
    parser.add_argument("--samples", type=int, help="llm: judge samples; keep it odd")
    parser.add_argument("--max-cost-usd", type=float, help="budget: cost ceiling")
    parser.add_argument("--max-turns", type=int, help="budget: turn ceiling")
    parser.add_argument("--force", action="store_true", help="replace an existing grader file")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    case_dir = Path(args.case_dir).expanduser()
    if not case_dir.is_dir():
        print(f"error: {case_dir} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    if not (case_dir / "prompt.md").is_file():
        print(f"error: {case_dir} has no prompt.md, so it is not a case directory",
              file=sys.stderr)
        return EXIT_USAGE

    slug, meta, body = build_grader(args.grader_type, args)
    if args.grader_type == "llm":
        text = body                       # rubrics.grader_file already wrote the whole file
    else:
        text = dump(meta, body)

    path = case_dir / "graders" / f"{slug}.md"
    plan = WritePlan()
    plan.add(path, text, force=args.force)

    # Validate what is about to be written, so a TODO placeholder that breaks a
    # required field is reported here rather than by the next validation pass.
    from agent_sdk_skills.frontmatter import parse

    document = parse(text)
    findings: list[Finding] = validate_grader(
        document.meta, body=document.body, path=str(path), name=slug)

    critiques: list[str] = []
    if args.grader_type == "llm":
        criteria, _ = rubrics.split_criteria(document.body)
        critiques = rubrics.lint_criteria(criteria)
        for critique in critiques:
            findings.append(Finding(
                id="EVC050", severity=rubrics.severity_of([critique]), area="grader",
                message=critique, path=str(path),
                fix="rewrite the criterion: one claim, an explicit FAIL clause naming the "
                    "near-misses, and nothing a reader of the evidence cannot check",
                source="skills/eval-criteria/references/rubric-authoring.md"))

    #: A placeholder is not a validation error — the file parses and every
    #: required field is present — but a grader left this way asserts nothing,
    #: so it still has to reach the exit code. Only the *assertion* counts: the
    #: prose note always asks to be rewritten, and that is advice, not a defect.
    assertion = json.dumps(document.meta) + (
        rubrics.split_criteria(document.body)[0] if args.grader_type == "llm" else "")
    has_todo = TODO_TEXT in assertion or TODO_TOOL in assertion

    written = [] if args.dry_run else plan.apply()
    report = GapReport(subject=str(path), skill="eval-criteria")
    report.extend(findings)
    report.discovered = {"type": args.grader_type, "name": slug,
                         "tier": (spec_for(args.grader_type) or None).tier,
                         "fields": sorted(document.meta)}

    payload = {"case_dir": str(case_dir), "path": str(path), "type": args.grader_type,
               "name": slug, "dry_run": args.dry_run, "plan": plan.to_dict(),
               "written": written, "findings": [f.to_dict() for f in findings],
               "critiques": critiques, "has_placeholders": has_todo}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(report.to_md())
        print()
        print(plan.to_md())
        print("\n_Dry run: nothing was written._" if args.dry_run
              else f"\n_Wrote {len(written)} file(s)._")
        if has_todo:
            print("\n- this grader carries TODO placeholders. Fill them in before running the "
                  "suite: a grader with a placeholder tool name asserts nothing (EVC020), and "
                  "a placeholder pattern matches nothing.")
    return EXIT_FINDINGS if (findings or has_todo) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
