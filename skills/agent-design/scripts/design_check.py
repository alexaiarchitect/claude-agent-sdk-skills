#!/usr/bin/env python3
"""Review an agent's design against Anthropic's published guidance.

The wiring linters answer "does this work as written"; this answers "is it
shaped the way the model needs". It reads the same syntax tree
`lint_harness.py` reads and reports `DSG` findings about the parts of an
agent the model actually sees and chooses between:

  DSG001  a tool with no description, or one under 40 characters
  DSG002  ambiguous parameter names (`id`, `user`, `data`, `input`, ...)
  DSG003  a `list_*`/`get_all_*`/`fetch_*`/`dump_*` tool with nothing to bound it
  DSG004  four or more tools on one server with no shared name part
  DSG005  near-duplicate tools: same action on the same thing
  DSG006  more than 30 tool definitions reachable
  DSG007  (info) a subagent told nothing about what to return or where to stop
  DSG008  (info) nothing bounds or sustains a long run

Every finding carries a `Source:` naming the article (title, date, URL) the
rule comes from and the code.claude.com page for current behaviour. The
thresholds are heuristics from those articles, not SDK limits: a finding is a
question to ask, and the evals decide the answer.

Report only. It never edits.

    design_check.py <project> [--json] [--format json|md] [--strict]

Exit codes: 0 no warnings, 1 warnings (or, under `--strict`, any finding at
all, notes included), 2 nothing to check: a missing path, no SDK usage, or
source that does not parse.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _design import LoadError, check, load  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="project root or agent module")
    parser.add_argument("--format", choices=("json", "md"), default="md")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        help="print the report as JSON: path, findings, summary, discovered")
    parser.add_argument("--strict", action="store_true",
                        help="count notes (info) towards the exit code as well as warnings")
    args = parser.parse_args(argv)

    try:
        subject = load(args.project)
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    report, extra = check(subject)
    if args.format == "json":
        data = {"path": str(subject.root), **report.to_dict()}
        data["discovered"] = extra["discovered"]
        print(json.dumps(data, indent=2))
    else:
        print(report.to_md())

    failing = report.count("error") + report.count("warn")
    if args.strict:
        failing += report.count("info")
    return EXIT_FINDINGS if failing else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
