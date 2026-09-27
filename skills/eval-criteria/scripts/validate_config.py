#!/usr/bin/env python3
"""Check one `eval_config.json` before it costs anything.

Every finding here is one a run would otherwise discover expensively: a judge
model that has been retired (the call fails), a `pr` tier that lists judge
graders (every pull request pays for a judge), a `pass_k` larger than the tier's
`runs` (a threshold that can never be met), `concurrency` above 1 on a
subscription (parallel runs race each other into one person's usage window and
the rate limit looks like a flaky agent), or a `runner_version` that disagrees
with the copy actually installed (CFG050 — the file and the code that reads it
are not the same generation).

The check is offline and free. It reads the config, the runner copy's `VERSION`
and, unless you pass `--no-cli`, which credential this machine would use — the
credential is what turns the concurrency warning on.

    validate_config.py <project|config.json> [--strict] [--no-cli] [--json]

`--strict` promotes warnings to the exit code, for a CI step that should refuse
to run a suite whose config is merely questionable.

Exit codes: 0 valid, 1 findings (errors always; warnings under `--strict`),
2 the file is missing or is not JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import RUNNER_VERSION  # noqa: E402
from agent_sdk_skills.env import detect_credential  # noqa: E402
from agent_sdk_skills.eval_config import (  # noqa: E402
    CONFIG_NAME, config_summary, load_config, validate_config,
)
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, Finding, GapReport,
)
from agent_sdk_skills.runner_version import findings_for, inspect_runner_copy  # noqa: E402

#: `eval_config.validate_config` compares the config's `runner_version` against
#: the *installed copy* when there is one, which is the comparison that decides
#: whether a run will work. It cannot see the third case: the config and the
#: copy agree with each other and both are behind the plugin. That is a real
#: CFG050 — the config declares a runner this plugin does not ship — so the
#: scripts add it here rather than editing the shared validator.
def stale_against_plugin(config, copy, findings) -> list:
    declared = config.runner_version if config.ok else None
    if declared is None or any(f.id == "CFG050" for f in findings):
        return []
    if str(declared) == str(RUNNER_VERSION):
        return []
    return [Finding(
        id="CFG050", severity="warn", area="config",
        message=f"`runner_version` is {declared!r}, which this plugin does not ship "
                f"(it ships {RUNNER_VERSION})",
        path=config.path, locator="runner_version",
        fix="the config and the installed copy agree with each other and both are behind. "
            "Run `install_runner.py --upgrade` (it shows a diff first), then set this field "
            "to the new version.",
        source="this plugin's runner_version.py",
    )]



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", default=".",
                        help="a project directory, an evals/ directory, or the config file")
    parser.add_argument("--strict", action="store_true",
                        help="warnings count towards the exit code")
    parser.add_argument("--no-cli", action="store_true",
                        help="do not run `claude auth status` to detect the credential")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser()
    if target.is_file():
        config_path = target
        project = target.parent.parent
    else:
        if not target.is_dir():
            print(f"error: {target} does not exist", file=sys.stderr)
            return EXIT_USAGE
        layout = detect_layout(target)
        project = Path(layout.project_root or target)
        config_path = project / "evals" / CONFIG_NAME

    config = load_config(config_path)
    copy = inspect_runner_copy(project / "evals" / "runner")
    credential = None
    if not args.no_cli:
        try:
            credential = detect_credential(project, ask_cli=True)
        except (OSError, ValueError):            # pragma: no cover - defensive
            credential = None

    findings = validate_config(
        config,
        runner_copy_version=copy.version,
        credential_kind=credential.kind if credential else None,
    )

    findings.extend(stale_against_plugin(config, copy, findings))
    if copy.present:
        findings.extend(findings_for(copy, path=str(project / "evals" / "runner")))

    report = GapReport(subject=str(config_path), skill="eval-criteria")
    report.extend(findings)
    report.discovered = {
        "exists": config.exists,
        "runner_copy": f"{copy.version} ({copy.status})" if copy.present else "not installed",
        "credential": credential.describe() if credential else "(not checked)",
    }
    if config.ok:
        report.discovered["config"] = config_summary(config)

    if args.json:
        print(json.dumps({**report.to_dict(), "strict": args.strict}, indent=2))
    else:
        print(report.to_md())

    if not config.exists or config.errors:
        return EXIT_USAGE
    if report.has_errors():
        return EXIT_FINDINGS
    if args.strict and report.count("warn"):
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
