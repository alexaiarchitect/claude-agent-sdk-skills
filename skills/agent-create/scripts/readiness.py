#!/usr/bin/env python3
"""Is this project ready to be evaluated — and if not, what is missing?

`/agent-sdk:agent-create` never writes the agent itself. It makes an agent
*evaluable*, and that is a short, checkable list:

* an entry point a runner can obtain — `build_options()` in a module, or a
  `module:function` named in the config. Options built inside `main()` exist
  only for that process, so no eval can override the model, the tools or the
  budget (AGT003); several agent modules and no convention is the same problem
  under a different name (AGT002); a `claude_code_sdk` import is the retired
  package and will not run at all (AGT030).
* `.env.example`, so the next person knows which variables matter without
  reading the source, and `.gitignore` covering `.env` and `evals/results/`.
* an `evals/` directory with a config and at least one case.
* a runner copy under `evals/runner/`, at this plugin's version (DEP001-004).
* a pytest gate, if the project runs pytest — the cheapest way to make the
  suite part of CI.

It also reports whether the official `agent-sdk-dev` plugin is installed
(DEP010). That plugin writes the bare app this one wraps; when it is present,
`/agent-sdk-dev:new-sdk-app` is the right answer to "I have no agent yet".

    readiness.py <project> [--json] [--no-cli] [--no-probe]

Exit codes: 0 ready, 1 findings to act on, 2 no agent found here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import RUNNER_VERSION  # noqa: E402
from agent_sdk_skills.discover import discover  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, Finding, GapReport, Option,
)
from agent_sdk_skills.runner_version import findings_for, inspect_runner_copy  # noqa: E402

#: Findings from the shared discovery pass that decide eval-readiness. The rest
#: of what `discover` reports (model policy, credentials, CI) belongs to other
#: skills; repeating it here would bury the three things this skill can fix.
READINESS_IDS = ("AGT002", "AGT003", "AGT030", "AGT021", "ENV020", "ENV021")

DEV_PLUGIN = "agent-sdk-dev"
_SRC = "this plugin's eval-ready checklist (skills/agent-create/references/eval-ready-architecture.md)"


def _gitignore_lines(project: Path) -> list[str]:
    path = project / ".gitignore"
    if not path.is_file():
        return []
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []


def _ignored(lines: list[str], name: str) -> bool:
    """Does any .gitignore line cover `name`? Deliberately literal: a pattern
    this misses is reported as missing, which is the safe direction."""
    bare = name.rstrip("/")
    wanted = {name, bare, f"/{name}", f"/{bare}", f"{bare}/", f"**/{bare}", f"**/{name}",
              f"{bare}*", f"{bare}.*"}
    return any(line in wanted for line in lines)


def _dev_plugin_installed(*, ask_cli: bool = True) -> dict:
    """Is the official `agent-sdk-dev` plugin installed? Read-only.

    Two sources, because either alone is wrong: the plugins directory shows a
    marketplace checkout that may not be enabled, and `claude plugin list`
    knows what is enabled but needs the CLI on PATH.
    """
    found: list[str] = []
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    plugins = home / "plugins"
    if plugins.is_dir():
        for path in plugins.rglob(DEV_PLUGIN):
            if path.is_dir():
                found.append(str(path))
                if len(found) >= 3:
                    break
    cli_says = None
    if ask_cli and shutil.which("claude"):
        try:
            proc = subprocess.run(["claude", "plugin", "list", "--json"],
                                  capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and DEV_PLUGIN in proc.stdout:
                cli_says = True
            elif proc.returncode == 0:
                cli_says = False
        except (OSError, subprocess.SubprocessError):
            cli_says = None
    return {"installed": bool(found) or bool(cli_says), "paths": found, "cli_reports": cli_says}


def build_report(project: Path, *, ask_cli: bool = True, probe: bool = True) -> tuple[GapReport, bool]:
    layout = detect_layout(project)
    root = Path(layout.project_root or project)
    report = GapReport(subject=str(root), skill="agent-create")

    shared = discover(root, focus=("layout", "env", "evals", "runner"),
                      probe_runner=probe, ask_cli=ask_cli, skill="agent-create")
    report.extend([f for f in shared.findings if f.id in READINESS_IDS])

    copy = inspect_runner_copy(root / "evals" / "runner")
    report.extend(findings_for(copy, path=str(root / "evals" / "runner")))

    evals = layout.evals
    cases = evals.case_count if evals else 0
    has_config = bool(evals and evals.config)
    ignore_lines = _gitignore_lines(root)
    env_ignored = _ignored(ignore_lines, ".env")
    results_ignored = _ignored(ignore_lines, "evals/results/") or _ignored(ignore_lines, "results/")
    dev = _dev_plugin_installed(ask_cli=ask_cli)

    report.discovered = {
        "entry_point": layout.entry_spec or "(none)",
        "style": layout.style,
        "agent_modules": len(layout.agent_modules),
        "env_example": [Path(p).name for p in layout.example_files] or "(none)",
        "evals": {"cases": cases, "config": bool(has_config),
                  "mock_servers": len(evals.mocks) if evals else 0},
        "runner_copy": copy.status if copy.present else "missing",
        "pytest_gate": layout.pytest_gate or "(none)",
        "gitignore": {".env": env_ignored, "evals/results/": results_ignored},
        "agent_sdk_dev_plugin": "installed" if dev["installed"] else "not installed",
    }

    if not layout.is_agent:
        report.add(
            "AGT001", "error", "agent",
            "no module builds ClaudeAgentOptions or calls query()/ClaudeSDKClient here",
            path=str(root),
            fix="this skill wraps an existing agent; it does not write one. "
                + (f"Run `/{DEV_PLUGIN}:new-sdk-app` to scaffold the app, then come back."
                   if dev["installed"]
                   else "Write a minimal `agent.py` with `build_options()`, or install the "
                        f"official `{DEV_PLUGIN}` plugin and run `/{DEV_PLUGIN}:new-sdk-app`."),
            source=_SRC)

    if not layout.example_files:
        report.add("AGT021", "warn", "environment", "no `.env.example`", path=str(root),
                   fix="write one naming CLAUDE_MODEL and the credential variables, with the "
                       "secrets commented out: the SDK does not read `.env` by itself, so the "
                       "file is documentation the next person needs and a checklist CI can read",
                   source=_SRC)
    if root.joinpath(".env").is_file() and not env_ignored:
        report.add("ENV020", "error", "environment", ".env is not covered by .gitignore",
                   path=str(root / ".gitignore"), fix="add `.env`", source=_SRC)
    if not results_ignored and cases:
        report.add("EVC070", "warn", "evals", "`evals/results/` is not gitignored",
                   path=str(root / ".gitignore"),
                   fix="add `evals/results/`; every run writes traces and result JSON there, "
                       "and traces can carry prompt and tool-result text",
                   source=_SRC)
    if not layout.pytest_gate:
        report.add_gap("pytest-gate", "no tests/test_evals.py",
                       "a project that already runs pytest can gate on the suite for free; "
                       "without it the evals only run when someone remembers",
                       "eval_scaffold.py writes one from the eval-ci template")
    if not dev["installed"]:
        report.findings.append(Finding(
            id="DEP010", severity="info", area="plugins",
            message=f"the official `{DEV_PLUGIN}` plugin is not installed",
            path=str(root),
            fix=f"optional. `/{DEV_PLUGIN}:new-sdk-app` writes the bare app this skill wraps; "
                "this plugin does not depend on it and never writes the app itself",
            source="code.claude.com/docs/en/claude-code/plugins"))

    # -- gaps ----------------------------------------------------------
    if not has_config:
        report.add_gap("eval-config", "no evals/eval_config.json",
                       "the config pins the model, the isolation defaults and the tier "
                       "thresholds; without it every run inherits whatever the CLI defaults to",
                       "eval_scaffold.py writes the default config")
    if cases == 0:
        report.add_gap("cases", "no eval cases",
                       "nothing can be replayed, so every claim about the agent is a memory "
                       "of one conversation",
                       "eval_scaffold.py writes a starter case; `/agent-sdk:eval-create` "
                       "writes the rest")
    if not copy.present:
        report.add_gap("runner", "no runner copy under evals/runner/",
                       "the runner lives in the project so CI needs nothing from this plugin",
                       f"install_runner.py copies version {RUNNER_VERSION}")

    # -- options -------------------------------------------------------
    if not copy.present:
        report.add_option(Option(
            key="1", label="install the eval runner", cost="free", recommended=True,
            detail=f"copies agent_sdk_evals {RUNNER_VERSION} into evals/runner/ with a manifest",
            writes=["evals/runner/agent_sdk_evals/"]))
    elif copy.status == "older":
        report.add_option(Option(
            key="1", label="upgrade the runner copy", cost="free", recommended=True,
            detail=f"{copy.version} -> {RUNNER_VERSION}; install_runner.py --upgrade shows the "
                   "diff first", writes=["evals/runner/agent_sdk_evals/"]))
    if not has_config or cases == 0:
        report.add_option(Option(
            key="2", label="scaffold the eval suite", cost="free",
            recommended=copy.present,
            detail="eval_config.json, a starter case with two free graders, mocks/README.md, "
                   ".env.example, tests/test_evals.py and the .gitignore lines",
            writes=["evals/eval_config.json", "evals/smoke/", ".env.example",
                    "tests/test_evals.py", ".gitignore"]))
    if not layout.is_agent and dev["installed"]:
        report.add_option(Option(
            key="3", label=f"hand off to /{DEV_PLUGIN}:new-sdk-app", cost="free",
            detail="that plugin writes the bare app; return here to make it evaluable",
            writes=["(that plugin's own files)"]))

    return report, layout.is_agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-cli", action="store_true",
                        help="do not run `claude plugin list` to detect agent-sdk-dev")
    parser.add_argument("--no-probe", action="store_true",
                        help="skip the interpreter probe (faster; SDK version unreported)")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    report, is_agent = build_report(project, ask_cli=not args.no_cli, probe=not args.no_probe)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_md())

    if not is_agent:
        return EXIT_USAGE
    if report.findings or report.gaps:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
