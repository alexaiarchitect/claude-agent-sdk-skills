#!/usr/bin/env python3
"""Sample passing runs for a human to check that they deserved to pass.

Criteria that are too lenient produce a green suite and a bad agent, and nothing
in the system notices. Once in a while a person reads a few passing runs and
asks "would I have passed this?". This picks a reproducible random sample of
PASSED runs, prefers cases judged by an `llm` grader (where leniency hides),
and prints the trace path to read with the grader verdicts beside it.

    calibration_sample.py <project|evals|results> [--n 5] [--seed 0] [--last N] [--json]

Exit codes: 0, 2 nothing to read.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.report import EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.results import load_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--last", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    runs = load_all(Path(args.path).expanduser(), last=args.last)
    if not runs:
        print(f"error: no result directories under {args.path}", file=sys.stderr)
        return EXIT_USAGE
    pool = []
    for run_dir in runs:
        for name, case in run_dir.cases.items():
            for run in case.runs:
                if run.status == "PASSED":
                    judged = any(g.type == "llm" for g in run.graders)
                    pool.append({"case": name, "run": run.run, "judged": judged,
                                 "trace": str(Path(run_dir.path) / run.trace) if run.trace else None,
                                 "graders": [g.to_dict() for g in run.graders]})
    rng = random.Random(args.seed)
    judged = [p for p in pool if p["judged"]]
    others = [p for p in pool if not p["judged"]]
    rng.shuffle(judged)
    rng.shuffle(others)
    sample = (judged + others)[: args.n]
    if args.json:
        print(json.dumps({"sample": sample, "pool": len(pool), "seed": args.seed}, indent=2))
    else:
        print(f"# calibration sample ({len(sample)} of {len(pool)} passing runs, seed {args.seed})\n")
        for item in sample:
            print(f"- `{item['case']}` run {item['run']}" + (" (judged)" if item["judged"] else ""))
            print(f"  - trace: {item['trace']}")
            for grader in item["graders"]:
                reason = f" — {grader['reason']}" if grader.get("reason") else ""
                print(f"  - {grader['name']} ({grader['type']}): {grader['status']}{reason}")
        print("\nFor each: read the trace, decide whether you would have passed it, and note disagreements.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
