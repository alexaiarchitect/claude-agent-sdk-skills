#!/usr/bin/env python3
"""Explain a results directory: what failed, why, and what it cost.

A score is not a diagnosis. For each case this reads the worst run, names the
graders that failed with their reasons, places the failure in the quadrant
(trajectory graders versus answer graders), separates never-evaluated runs
from failures and says why they happened, and reports efficiency (turns,
tokens, cost) in its own table where lower is better and nothing is a verdict.
On a subscription the cost column is an estimate, and the report says so.

    summarize_results.py <project|evals|results|run-dir> [--last N] [--case NAME] [--json]

Exit codes: 0 every run passed, 1 failures, 3 only never-evaluated runs,
2 nothing to read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_INCONCLUSIVE, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.results import efficiency_rows, load_all, not_evaluated_cause  # noqa: E402

TRAJECTORY_GRADERS = {"trajectory", "tool_used", "tool_order", "no_tool", "hook_event"}
ANSWER_GRADERS = {"llm", "regex", "final_text", "structured_output"}


def quadrant(run) -> str:
    """Q1 both good, Q2 path good/answer weak, Q3 path weak/answer good, Q4 both weak."""
    path_ok = all(g.status != "FAILED" for g in run.graders if g.type in TRAJECTORY_GRADERS)
    answer_ok = all(g.status != "FAILED" for g in run.graders if g.type in ANSWER_GRADERS)
    has_path = any(g.type in TRAJECTORY_GRADERS for g in run.graders)
    has_answer = any(g.type in ANSWER_GRADERS for g in run.graders)
    if not has_path or not has_answer:
        return "n/a (needs both a trajectory-type and an answer-type grader)"
    return {(True, True): "Q1", (True, False): "Q2", (False, True): "Q3 (right answer, wrong path)",
            (False, False): "Q4"}[(path_ok, answer_ok)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--last", type=int, default=1, help="how many result directories to read (default 1)")
    parser.add_argument("--case")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    runs = load_all(Path(args.path).expanduser(), last=args.last)
    if not runs:
        print(f"error: no result directories under {args.path} (run /agent-sdk:eval-run first)", file=sys.stderr)
        return EXIT_USAGE

    report = {"directories": [], "efficiency": efficiency_rows(runs)}
    failed = never = passed = 0
    for run_dir in runs:
        entry = {"path": run_dir.path, "tier": run_dir.aggregate.tier if run_dir.aggregate else None,
                 "cost_basis": run_dir.aggregate.cost_basis if run_dir.aggregate else None,
                 "totals": run_dir.aggregate.totals if run_dir.aggregate else None,
                 "stopped": run_dir.aggregate.stopped if run_dir.aggregate else None,
                 "status_counts": run_dir.status_counts(), "cases": []}
        for name, case in sorted(run_dir.cases.items()):
            if args.case and name != args.case:
                continue
            worst = case.worst_run
            item = {"case": name, "category": case.category, "statuses": case.statuses(),
                    "pass_rate": round(case.pass_rate, 3), "cost_usd": case.cost_usd, "error": case.error}
            if worst:
                item["worst_run"] = worst.run
                item["quadrant"] = quadrant(worst) if worst.status == "FAILED" else None
                item["failed_graders"] = [{"name": g.name, "type": g.type, "reason": g.reason, "score": g.score}
                                          for g in worst.failed_graders()]
                item["not_evaluated"] = [g.name for g in worst.not_evaluated_graders()]
                item["not_evaluated_cause"] = not_evaluated_cause(worst) if worst.status == "NOT_EVALUATED" else None
                item["informational"] = [{"name": g.name, "score": g.score} for g in worst.informational_graders()]
                item["terminal"] = {"subtype": worst.result.get("subtype"),
                                    "terminal_reason": worst.result.get("terminal_reason"),
                                    "num_turns": worst.num_turns}
                item["rate_limit"] = worst.rate_limit
            entry["cases"].append(item)
        counts = entry["status_counts"]
        failed += counts.get("FAILED", 0)
        never += counts.get("NOT_EVALUATED", 0)
        passed += counts.get("PASSED", 0)
        report["directories"].append(entry)

    code = EXIT_FINDINGS if failed else (EXIT_INCONCLUSIVE if never and not passed else EXIT_OK)
    if never and not failed and passed:
        code = EXIT_INCONCLUSIVE
    report["exit_code"] = code
    if args.json:
        print(json.dumps(report, indent=2))
        return code

    for entry in report["directories"]:
        print(f"# results: {Path(entry['path']).name} (tier {entry['tier'] or '?'})\n")
        counts = entry["status_counts"]
        print("- statuses: " + ", ".join(f"{k.lower()}={v}" for k, v in counts.items()))
        if entry["totals"]:
            basis = entry["cost_basis"] or "?"
            print(f"- cost: {entry['totals'].get('cost_usd', '?')} USD, {basis}"
                  f"{' (estimate)' if basis == 'subscription' else ''}")
        if entry["stopped"]:
            print(f"- stopped early: {entry['stopped']}")
        print()
        for item in entry["cases"]:
            head = f"## `{item['case']}` — {'/'.join(item['statuses'])}"
            print(head)
            if item.get("quadrant"):
                print(f"- quadrant: {item['quadrant']}")
            for grader in item.get("failed_graders", []):
                reason = f": {grader['reason']}" if grader.get("reason") else ""
                print(f"- failed `{grader['name']}` ({grader['type']}){reason}")
            if item.get("not_evaluated_cause"):
                print(f"- never evaluated: {item['not_evaluated_cause']}")
            elif item.get("not_evaluated"):
                print(f"- graders not evaluated: {', '.join(item['not_evaluated'])}")
            for info in item.get("informational", []):
                print(f"- informational `{info['name']}`: {info['score']}")
            terminal = item.get("terminal") or {}
            if terminal.get("terminal_reason") not in (None, "completed"):
                print(f"- ended by: {terminal.get('terminal_reason')} ({terminal.get('subtype')})")
            print()
    print("## Efficiency (lower is better, never a verdict)\n")
    print("| case | runs | turns | input tok | output tok | cache read | cost USD | ms |")
    print("|---|---|---|---|---|---|---|---|")
    for row in report["efficiency"]:
        print(f"| `{row['case']}` | {row['runs']} | {row['mean_turns']} | {row['mean_input_tokens']} | "
              f"{row['mean_output_tokens']} | {row['mean_cache_read_tokens']} | {row['mean_cost_usd']} | "
              f"{row['mean_duration_ms']} |")
    if any(r.get("cost_basis") == "subscription" for r in report["efficiency"]):
        print("\nCosts are API-equivalent estimates: these runs drew on a subscription.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
