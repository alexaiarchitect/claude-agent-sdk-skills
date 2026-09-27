#!/usr/bin/env python3
"""Name the failure shape in a trace, find the first divergence, assign a layer.

Evidence first: this reads a runner trace (`*.trace.jsonl`), an imported Claude
Code session (converted by `import_session.py`) or a whole result directory, and
prints what the events show: the tool calls in order, the failure signatures
(loop, oscillation, stall, unknown tool, error cascade, a ceiling that fired),
the first divergence from the case's `trajectory` grader when a case directory
is given, the terminal reason, the rate-limit state and the cost with its basis.
Each signature names the layer the fix belongs to, so a tool bug is not treated
with a prompt tweak. Nothing here starts a session.

    analyze_trace.py --trace FILE [--case-dir DIR] [--json]
    analyze_trace.py --session FILE [--json]
    analyze_trace.py --results DIR [--case NAME] [--json]

Exit codes: 0 no signature found, 1 signatures or a divergence found,
2 nothing readable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.budget import cost_label, rate_limit_summary, usage_limit_from_result  # noqa: E402
from agent_sdk_skills.frontmatter import parse as parse_frontmatter  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.trace import (  # noqa: E402
    final_text, init_event, is_imported, load_session, load_trace, result_event, to_summary,
    tool_calls,
)
from agent_sdk_skills.trajectory import (  # noqa: E402
    calls_from_events, cascade_suspect, detect_signatures, diff, expected_from_grader,
)


def trajectory_grader(case_dir: Path) -> dict | None:
    """The first `trajectory` grader of a case, or None."""
    graders = case_dir / "graders"
    if not graders.is_dir():
        return None
    for path in sorted(graders.glob("*.md")):
        try:
            doc = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a broken grader is eval-review's business
            continue
        if doc.meta.get("type") == "trajectory":
            return {"path": str(path), **doc.meta}
    return None


def analyze(events, *, case_dir: Path | None, label: str) -> dict:
    summary = to_summary(events)
    init = init_event(events)
    known = set(init.get("tools") or []) if init else None
    signatures = [s.to_dict() for s in detect_signatures(events, known_tools=known)]
    report = {
        "source": label,
        "imported": is_imported(events),
        "summary": summary,
        "calls": [c.short() for c in calls_from_events(events)],
        "synthetic_calls": [e.tool for e in tool_calls(events, include_synthetic=True) if e.synthetic],
        "signatures": signatures,
        "divergence": None,
        "final_text": final_text(events)[:400],
    }
    result = result_event(events)
    if result is not None:
        report["terminal"] = {"subtype": result.get("subtype"), "terminal_reason": result.get("terminal_reason"),
                              "num_turns": result.get("num_turns"), "api_error_status": result.get("api_error_status")}
        report["cost"] = cost_label(result.get("total_cost_usd"), result.get("cost_basis"))
        limit = usage_limit_from_result(result)
        if limit:
            report["usage_limit"] = limit
    else:
        report["terminal"] = None
        report["cost"] = "no result event: imported session or crashed run; cost and terminal fields unknown"
    report["rate_limit"] = rate_limit_summary(events)

    if case_dir is not None:
        grader = trajectory_grader(case_dir)
        if grader:
            expected = expected_from_grader(grader)
            comparison = diff(calls_from_events(events), expected,
                              grader.get("match", "IN_ORDER"), grader.get("args_match", "subset"))
            report["divergence"] = comparison.to_dict()
            report["divergence"]["grader"] = grader["path"]
            suspect = cascade_suspect(comparison)
            if suspect:
                report["signatures"].append(suspect.to_dict())
        else:
            report["divergence"] = {"note": f"no trajectory grader under {case_dir}/graders; "
                                            "generate one from a reviewed trace with eval-create's trace_to_case.py"}
    return report


def render(report: dict) -> str:
    lines = [f"# analyze_trace: {report['source']}", ""]
    if report["imported"]:
        lines.append("- evidence: imported session (no cost or terminal fields)")
    lines.append(f"- calls: {' -> '.join(report['calls']) or '(none)'}")
    if report["synthetic_calls"]:
        lines.append(f"- synthetic calls excluded: {', '.join(report['synthetic_calls'])}")
    if report.get("terminal"):
        t = report["terminal"]
        lines.append(f"- ended: {t.get('terminal_reason') or '?'} ({t.get('subtype') or '?'}), turns {t.get('num_turns')}")
    lines.append(f"- cost: {report['cost']}")
    if report.get("rate_limit"):
        rl = report["rate_limit"]
        lines.append(f"- rate limit: {rl.get('status')} (windows {rl.get('windows')})")
    if report.get("usage_limit"):
        lines.append(f"- usage limit: {report['usage_limit']}")
    lines.append("")
    if report["signatures"]:
        lines.append("## Signatures")
        lines.append("")
        for sig in report["signatures"]:
            lines.append(f"- **{sig['kind']}** ({sig['layer']}): {sig['detail']}")
            if sig.get("fix"):
                lines.append(f"  - Fix: {sig['fix']}")
            for ev in sig.get("evidence", [])[:3]:
                lines.append(f"  - {ev}")
        lines.append("")
    else:
        lines.append("no failure signature in this trace\n")
    div = report.get("divergence")
    if div:
        lines.append("## Divergence")
        lines.append("")
        if "note" in div:
            lines.append(f"- {div['note']}")
        else:
            lines.append(f"- {div['explanation']} (score {div['score']})")
            if div.get("missing"):
                lines.append(f"- missing: {', '.join(div['missing'])}")
            if div.get("extra"):
                lines.append(f"- extra: {', '.join(div['extra'])}")
            if div.get("forbidden"):
                lines.append(f"- forbidden: {', '.join(div['forbidden'])}")
        lines.append("")
    if report["final_text"]:
        lines.append("## Final text")
        lines.append("")
        lines.append(report["final_text"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--trace", help="a runner trace (*.trace.jsonl)")
    source.add_argument("--session", help="a Claude Code session file (*.jsonl)")
    source.add_argument("--results", help="a results directory: every trace in it")
    parser.add_argument("--case-dir", help="the case whose trajectory grader defines the expected path")
    parser.add_argument("--case", help="with --results: only this case's traces")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports: list[dict] = []
    case_dir = Path(args.case_dir).expanduser() if args.case_dir else None
    try:
        if args.trace:
            path = Path(args.trace).expanduser()
            reports.append(analyze(load_trace(path), case_dir=case_dir, label=str(path)))
        elif args.session:
            path = Path(args.session).expanduser()
            reports.append(analyze(load_session(path), case_dir=case_dir, label=str(path)))
        else:
            directory = Path(args.results).expanduser()
            if not directory.is_dir():
                print(f"error: {directory} is not a directory", file=sys.stderr)
                return EXIT_USAGE
            for trace in sorted(directory.glob("*.trace.jsonl")):
                if args.case and not trace.name.startswith(args.case + "."):
                    continue
                inferred = case_dir
                if inferred is None:
                    evals_dir = directory.parent.parent
                    candidate = evals_dir / trace.name.split(".")[0]
                    inferred = candidate if (candidate / "prompt.md").is_file() else None
                reports.append(analyze(load_trace(trace), case_dir=inferred, label=str(trace)))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not reports:
        print("error: nothing readable", file=sys.stderr)
        return EXIT_USAGE

    found = any(r["signatures"] or (r.get("divergence") and r["divergence"].get("match") is False) for r in reports)
    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    else:
        print("\n\n".join(render(r) for r in reports))
    return EXIT_FINDINGS if found else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
