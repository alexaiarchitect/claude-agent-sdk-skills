#!/usr/bin/env python3
"""Which of the agent's rules does the suite actually test?

Cases get written from what the agent *does*; rules get written from what it
*must*. Nothing connects the two lists, so a suite can have twenty cases and
still leave the one rule that matters untested. This puts the two side by side.

Four sections:

1. **Rules** read from the system prompt with `ast` — numbered or bulleted
   items, each flagged as a refusal or an ordering rule.
2. **The matrix** — which rules have at least one case aimed at them. "Aimed
   at" means a case mentions the rule's tool, or two of its key phrases. That
   is evidence somebody wrote a case for the rule; it is never evidence the
   rule holds.
3. **Shape** — one case of each category, and adversarial cases at 20% of the
   suite or more. Happy cases are the easy ones to write, so the adversarial
   share decays unless someone watches it.
4. **n+1 gaps** — every refusal rule needs a case that *attempts* the forbidden
   action, scored against the trace (`no_tool`, an EXACT trajectory, or
   `tool_used` with `max: 0`). A judge reading the final reply grades the
   apology, and a model that called the tool and then apologized passes.

Everything here is a heuristic over text, and the report says so. **Gaps are
advice, not failures**: the script exits 0 unless you pass `--strict`. A rule
the matrix calls uncovered may be covered by a case that words it differently,
and only you can tell.

When the system prompt is built at runtime — an f-string, a file read, a
preset — there are no rules to read, and the report says `unknown` rather than
reporting zero coverage.

    coverage_matrix.py <project> [--json] [--strict]

Exit codes: 0 reported (even with gaps), 1 gaps under `--strict`, 2 nothing to
analyse.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.coverage import (  # noqa: E402
    extract_rules, matrix, n_plus_one_gaps, read_system_prompt, shape,
    summarize_cases, tool_coverage,
)
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport,
)

# The sibling script holds the AST tool reader both of these need. No
# bytecode: a stray __pycache__ inside a published skill directory is
# noise in every diff and every package listing.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_cases import agent_tools_for  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--agent-dir", help="where the agent modules live, if not the project root")
    parser.add_argument("--strict", action="store_true", help="gaps count towards the exit code")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    evals = Path(layout.evals.dir) if layout.evals else project / "evals"
    if not evals.is_dir():
        print(f"error: no evals/ directory at {evals}", file=sys.stderr)
        return EXIT_USAGE

    agent_dir = Path(args.agent_dir).expanduser() if args.agent_dir else project
    prompt = read_system_prompt(agent_dir)
    rules = extract_rules(prompt.text) if prompt.readable else []
    cases = summarize_cases(evals)
    agent_tools, tools_source = agent_tools_for(agent_dir)

    grid = matrix(rules, cases)
    suite_shape = shape(cases)
    n_plus_one = n_plus_one_gaps(rules, cases)
    tools = tool_coverage(agent_tools, cases)

    report = GapReport(subject=str(project), skill="eval-review")
    report.discovered = {
        "system_prompt": prompt.to_dict(),
        "rules": len(rules),
        "refusal_rules": sum(1 for r in rules if r.is_refusal),
        "ordering_rules": sum(1 for r in rules if r.is_ordering),
        "cases": suite_shape["total"],
        "by_category": suite_shape["counts"],
        "adversarial_share": f"{suite_shape['adversarial_ratio']:.0%} "
                             f"(target {suite_shape['adversarial_target']:.0%})",
        "rule_coverage": (f"{grid['covered']}/{grid['total_rules']}"
                          if rules else "unknown — no literal system prompt to read"),
        "tool_coverage": (f"{tools['covered']}/{tools['total']}"
                          if tools["status"] == "ok" else "unknown"),
        "agent_tools_source": tools_source,
    }

    if not prompt.readable:
        report.add_gap(
            "system-prompt", f"the system prompt could not be read ({prompt.kind})",
            (prompt.note or "no literal prompt found")
            + " — so the rule matrix below is empty, which means 'not measured', not 'no rules'",
            "point --agent-dir at the module that holds the prompt, or move the prompt into a "
            "module-level `SYSTEM_PROMPT` constant so it can be reviewed without running the agent")
    for row in grid["rows"]:
        if row["covered"]:
            continue
        rule = row["rule"]
        report.add_gap(
            rule["id"], f"no case aimed at rule {rule['index']}: {rule['text'][:90]}",
            "a rule with no case is a rule nobody is testing; it survives only as long as the "
            "prompt wording does, and every model upgrade is a chance to lose it silently",
            "write a case whose prompt exercises it: `/agent-sdk:eval-create` "
            f"(gen_cases.py --category {'adversarial' if rule['is_refusal'] else 'happy'} "
            f"--rule \"{rule['text'][:60]}\")")
    for gap in suite_shape["gaps"]:
        report.add_gap(gap["id"], gap["what"], gap["why"], gap["recommendation"])
    for gap in n_plus_one:
        report.add_gap(f"n+1-{gap['rule']['id']}", gap["what"], gap["why"],
                       gap["recommendation"])
    for tool in tools.get("untested", []):
        report.add_gap(
            f"tool-{tool}", f"no grader mentions `{tool}`",
            "a tool no case asserts about can be removed, renamed or broken without any case "
            "noticing",
            "add a `tool_used` grader to the case that should call it, or a `no_tool` grader "
            "to a case that must not")

    payload = {**report.to_dict(), "matrix": grid, "shape": suite_shape,
               "n_plus_one": n_plus_one, "tools": tools, "strict": args.strict}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(report.to_md())
        if rules:
            print("\n## Rule matrix\n")
            print("| rule | kind | cases |")
            print("|---|---|---|")
            for row in grid["rows"]:
                rule = row["rule"]
                kind = ", ".join(
                    k for k, on in (("refusal", rule["is_refusal"]),
                                    ("ordering", rule["is_ordering"])) if on) or "—"
                names = ", ".join(f"`{c['case']}`" for c in row["cases"]) or "**none**"
                print(f"| {rule['index']}. {rule['text'][:70]} | {kind} | {names} |")
            print(f"\n_{grid['basis']}._")

    if args.strict and report.gaps:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
