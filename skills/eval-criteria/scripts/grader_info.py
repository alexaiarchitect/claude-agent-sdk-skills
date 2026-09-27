#!/usr/bin/env python3
"""The grader catalog: what each type checks, and what it cannot prove.

Twelve grader types, eleven of them free (deterministic, no model call) and one
— `llm` — that costs a judge call per sample. Choosing between them is most of
the work of writing a good case, and the column people skip is the last one:
*what this check does not prove*. A suite of graders that each prove something
narrow, with nothing covering the gap between them, passes a broken agent.

    grader_info.py [--type T] [--json]

With no `--type`, the whole catalog plus the semantics that were fixed by
measurement rather than by design. With one, everything about that type:
required fields, optional fields, valid targets, and the argument for and
against using it.

Exit codes: 0 always, except 2 for an unknown `--type`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.graders import (  # noqa: E402
    FREE_TYPES, GRADER_CATALOG, JUDGE_TYPES, RESULT_SHAPED_TYPES, TOOL_SHAPED_TYPES,
    catalog_rows, catalog_table, semantics_lines, spec_for,
)
from agent_sdk_skills.report import EXIT_OK, EXIT_USAGE  # noqa: E402


def _one(name: str) -> str:
    spec = spec_for(name)
    assert spec is not None
    lines = [f"# `{spec.type}` — {spec.tier} tier", "", spec.description, ""]
    lines.append(f"**Does not prove:** {spec.not_proven}.")
    lines.append("")
    if spec.required:
        lines.append(f"- required: {', '.join(f'`{f}`' for f in spec.required)}")
    for group in spec.one_of:
        lines.append("- required, at least one of: "
                     + ", ".join(f"`{f}`" for f in group))
    if spec.body_is:
        lines.append(f"- the file **body** is `{spec.body_is}`; for `llm` the text above a "
                     "bare `---` line is sent to the judge and everything below it is a note "
                     "for the next reader")
    lines.append(f"- optional: {', '.join(f'`{f}`' for f in spec.optional) or '—'}")
    lines.append(f"- targets: {', '.join(f'`{t}`' for t in spec.targets) or '—'}"
                 + (f" (default `{spec.default_target}`)" if spec.default_target else ""))
    if spec.tool_shaped:
        lines.append("- reads the tool-call sequence, so it skips synthetic tools "
                     "(`StructuredOutput`, `ToolSearch`) unless one is named explicitly, and "
                     "treats `Task` and `Agent` as the same tool")
    if spec.type in RESULT_SHAPED_TYPES:
        lines.append("- reads the `result` event, so it reports NOT_EVALUATED on an imported "
                     "session that carries no result line")
    lines.append(f"- source: {spec.source}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", dest="grader_type", help="one grader type, in detail")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.grader_type:
        spec = spec_for(args.grader_type)
        if spec is None:
            print(f"error: unknown grader type {args.grader_type!r}; known: "
                  + ", ".join(GRADER_CATALOG), file=sys.stderr)
            return EXIT_USAGE
        if args.json:
            print(json.dumps(spec.to_dict(), indent=2))
        else:
            print(_one(spec.type))
        return EXIT_OK

    if args.json:
        print(json.dumps({
            "types": catalog_rows(),
            "free": list(FREE_TYPES),
            "judge": list(JUDGE_TYPES),
            "tool_shaped": list(TOOL_SHAPED_TYPES),
            "result_shaped": list(RESULT_SHAPED_TYPES),
            "semantics": semantics_lines(),
        }, indent=2))
        return EXIT_OK

    print("# Grader catalog\n")
    print(catalog_table())
    print()
    print(f"- free (no model call): {', '.join(f'`{t}`' for t in FREE_TYPES)}")
    print(f"- judge (a model call per sample): {', '.join(f'`{t}`' for t in JUDGE_TYPES)}")
    print()
    print("## What each does not prove\n")
    for row in catalog_rows():
        print(f"- **`{row['type']}`** — {row['not_proven']}.")
    print()
    print("## Semantics fixed by measurement\n")
    for line in semantics_lines():
        print(line)
    print("\nRun with `--type <name>` for one type in full.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
