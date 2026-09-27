#!/usr/bin/env python3
"""Discover a Claude Agent SDK project and print a gap report.

Every skill in this plugin starts with this pass, because the three things
people guess wrong about an Agent SDK project are exactly the three that
decide what to do next: which module is the agent (the SDK prescribes no
layout), how the SDK subprocess will authenticate (an API key silently beats a
subscription login), and whether the project's eval runner copy matches this
plugin. The report says what was found, what is missing, and what the user can
choose to do, each option with its cost tier.

    discover.py <path> [--format md|json] [--focus layout,env,...] [--no-probe] [--no-cli]

`--no-probe` skips importing the SDK in a candidate interpreter (slow), and
`--no-cli` skips `claude auth status`. Both leave the corresponding facts as
"not verified" rather than guessed.

Exit codes: 0 nothing wrong, 1 errors found, 2 the target is unusable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.discover import ALL_FOCUS, discover  # noqa: E402
from agent_sdk_skills.report import EXIT_USAGE, exit_code_for  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", nargs="?", default=".", help="project root, agent module, or evals/ dir")
    parser.add_argument("--format", choices=("json", "md"), default="md")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        help="shorthand for --format json")
    parser.add_argument("--focus", default=",".join(ALL_FOCUS),
                        help=f"comma-separated subset of {', '.join(ALL_FOCUS)}")
    parser.add_argument("--no-probe", action="store_true", help="skip the interpreter/SDK probe")
    parser.add_argument("--no-cli", action="store_true", help="skip `claude auth status`")
    args = parser.parse_args(argv)

    target = Path(args.path).expanduser()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_USAGE
    focus = [f.strip() for f in args.focus.split(",") if f.strip()]
    unknown = sorted(set(focus) - set(ALL_FOCUS))
    if unknown:
        print(f"error: unknown focus {', '.join(unknown)}; choose from {', '.join(ALL_FOCUS)}", file=sys.stderr)
        return EXIT_USAGE

    report = discover(target, focus=focus, probe_runner=not args.no_probe, ask_cli=not args.no_cli)
    print(report.render(args.format))
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
