#!/usr/bin/env python3
"""Turn a Claude Code session file into a trace the analyzers can read.

A production run nobody instrumented still left evidence: the CLI wrote the
session as JSONL under `~/.claude/projects/<encoded cwd>/<session-id>.jsonl`.
This resolves a session id to that file using the same directory encoding the
SDK uses, converts it to the trace event model (ordering through the uuid
graph, bookkeeping lines kept as `system` events) and writes
`<session-id>.trace.jsonl`. The session file is never modified. The result has
no cost or terminal fields, so budget and terminal graders will report
NOT_EVALUATED on it; everything about the path the agent took is preserved.

    import_session.py <session-id | path> [--cwd DIR] [--out DIR] [--json]

Exit codes: 0 written, 1 the file could not be converted, 2 not found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.trace import load_session, session_dir_for, to_summary, write_trace  # noqa: E402


def resolve(spec: str, cwd: str | None) -> Path | None:
    candidate = Path(spec).expanduser()
    if candidate.is_file():
        return candidate
    directory = session_dir_for(cwd or str(Path.cwd()))
    for name in (f"{spec}.jsonl", spec):
        path = directory / name
        if path.is_file():
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", help="a session id, or a path to the .jsonl file")
    parser.add_argument("--cwd", help="the working directory the session ran in (default: here)")
    parser.add_argument("--out", default="evals/results/imported", help="directory for the trace")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    path = resolve(args.session, args.cwd)
    if path is None:
        looked = session_dir_for(args.cwd or str(Path.cwd()))
        print(f"error: no session {args.session!r}; looked in {looked}", file=sys.stderr)
        return EXIT_USAGE
    try:
        events = load_session(path)
    except (OSError, ValueError) as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        return EXIT_FINDINGS
    if not events:
        print(f"error: {path} holds no readable events", file=sys.stderr)
        return EXIT_FINDINGS
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{path.stem}.trace.jsonl"
    write_trace(target, events)
    summary = to_summary(events)
    payload = {"session": str(path), "trace": str(target), "events": len(events), "summary": summary,
               "note": "imported: no cost or terminal fields; budget and terminal graders will be NOT_EVALUATED"}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# import_session: {path.name}\n")
        print(f"- trace: {target}")
        print(f"- events: {len(events)}")
        for key in ("cli_version", "tool_calls", "tool_errors", "turns"):
            if key in summary:
                print(f"- {key}: {summary[key]}")
        print(f"- {payload['note']}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
