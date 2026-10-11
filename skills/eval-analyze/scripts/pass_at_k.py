#!/usr/bin/env python3
"""Measure reliability across repeated runs: pass@1, pass@k, pass^k, fragility.

One green run is one sample. This gathers every run of every case, from
`--runs N` inside a results directory and from several directories, and reports
pass@1 (production behaviour: one attempt per request), pass@k (the chance a
retry rescues it), pass^k (the chance k attempts all pass) and the gap between
them, which is fragility. A case that passes 2 runs in 5 is not "mostly
working"; it fails three requests in five.

Pooling only means something over repeats of one suite: when the directories
read differ in tier or in case set, the report warns and says to pass `--last`
or a single directory instead.

    pass_at_k.py <project|evals|results> [--last N] [--case NAME] [--k 1,3,5] [--json]

Exit codes: 0 every case reliable (pass@1 >= 0.95), 1 not, 2 nothing to read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.passk import aggregate  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.results import load_all, suite_runs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--last", type=int, help="only the last N result directories")
    parser.add_argument("--case")
    parser.add_argument("--k", default="1,3,5")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    runs = load_all(Path(args.path).expanduser(), last=args.last)
    if not runs:
        print(f"error: no result directories under {args.path}", file=sys.stderr)
        return EXIT_USAGE
    ks = [int(k) for k in args.k.split(",") if k.strip()]
    samples = suite_runs(runs)
    if args.case:
        samples = [{args.case: r[args.case]} for r in samples if args.case in r]
    pooled = [{"path": r.path, "tier": r.aggregate.tier if r.aggregate else None,
               "cases": sorted(r.cases)} for r in runs]
    report = aggregate(samples, ks=ks, suite=Path(runs[0].path).parent.name,
                       sources=[r.path for r in runs], pooled=pooled)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_md())
    return EXIT_OK if report.all_reliable else EXIT_FINDINGS


if __name__ == "__main__":
    raise SystemExit(main())
