#!/usr/bin/env python3
"""Compare the project's runner copy with the plugin, and with what it reports.

The runner package is copied into each project so CI needs nothing from the
plugin. The price is drift: this checks the copy's `VERSION` and manifest
against what this plugin ships (DEP001 older, DEP002 newer, DEP003 missing,
DEP004 locally modified) and, when an interpreter is available, asks the copy
itself for `version` so a copy that does not even import is caught before a run.

    check_runner.py <project> [--json] [--no-probe]

Exit codes: 0 up to date, 1 findings (older or modified), 2 missing, newer than
the plugin, or the copy fails to import.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import RUNNER_VERSION  # noqa: E402
from agent_sdk_skills.env import resolve_runner  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.runner_version import findings_for, inspect_runner_copy  # noqa: E402
from agent_sdk_skills.sdk_subprocess import run_project_runner  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-probe", action="store_true", help="do not run the copy's `version` command")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    copy = inspect_runner_copy(project / "evals" / "runner")
    findings = findings_for(copy, path=str(project / "evals" / "runner"))
    reported = None
    probe_error = None
    if copy.present and not args.no_probe:
        runner = resolve_runner(project, probe=True)
        if runner.available:
            outcome = run_project_runner(project, ["version"], runner=runner, timeout=120)
            reported = outcome.last_json()
            if outcome.returncode != 0 or not reported:
                probe_error = outcome.tail(5) or "no output"
        else:
            probe_error = runner.note

    payload = {"copy": copy.to_dict(), "plugin_version": RUNNER_VERSION,
               "findings": [f.to_dict() for f in findings], "reported": reported, "probe_error": probe_error}
    if any(f.id in ("DEP002", "DEP003") for f in findings) or (reported is None and probe_error and copy.present
                                                                and "No interpreter" not in probe_error):
        code = EXIT_USAGE
    elif findings:
        code = EXIT_FINDINGS
    else:
        code = EXIT_OK
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# check_runner: {project}\n")
        print(f"- copy: {'present' if copy.present else 'missing'} version={copy.version} status={copy.status}")
        print(f"- plugin ships: {RUNNER_VERSION}")
        if reported:
            print(f"- copy reports: runner {reported.get('runner_version')} on sdk {reported.get('sdk_version')}")
        if probe_error:
            print(f"- probe: {probe_error}")
        for finding in findings:
            print(f"- {finding.one_line()}\n  - Fix: {finding.fix}")
        print("\nup to date" if code == EXIT_OK else f"\nexit {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
