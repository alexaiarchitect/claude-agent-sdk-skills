#!/usr/bin/env python3
"""Validate every case and the config, before a run pays to find the problems.

This is the free gate. It parses each `prompt.md` and each grader file, checks
the frontmatter against the case contract, checks every grader against its
type's required fields, cross-checks the tool names the graders use against the
tools the agent actually exposes, and validates `eval_config.json` against the
runner copy that is installed.

Every finding is one a run would otherwise discover expensively — an
`overrides` typo that silently does nothing (`EVC003`), a grader whose required
field is missing so the case cannot be scored (`EVC011`), a `no_tool` grader
naming a tool the agent does not have, which passes trivially and forever
(`EVC020`), a restraint case with nothing reading the trace (`EVC041`).

The agent's tool list comes from an AST read of the project, never from
importing it: a review has to work on a project whose imports are the problem.
When no tool list can be determined, the cross-check is **skipped rather than
guessed** — an empty set would mean "the agent exposes nothing" and would bury
the real findings under a wall of false ones.

    validate_cases.py <project|evals-dir> [--agent-dir D] [--strict] [--json]

Exit codes: 0 clean, 1 findings (errors always; warnings under `--strict`),
2 there is nothing to validate — no evals directory, or no cases in it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import RUNNER_VERSION  # noqa: E402
from agent_sdk_skills.eval_config import CONFIG_NAME, load_config, validate_config  # noqa: E402
from agent_sdk_skills.evalcase import iter_cases, suite_summary, validate_suite  # noqa: E402
from agent_sdk_skills.evalcase import PROMPT_NAME  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.mocks import mock_tool_names, validate_mocks  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, Finding, GapReport,
)
from agent_sdk_skills.runner_version import inspect_runner_copy  # noqa: E402

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



def agent_tools_for(agent_dir: Path) -> tuple[set[str] | None, str]:
    """The tools the agent exposes, and where the answer came from.

    `None` means undetermined. The two sources, in order: an AST read of every
    module that imports the SDK (in-process `@tool` names plus whatever
    `allowed_tools` declares), and — when that finds nothing — the mock
    directory, which at least names the servers the suite believes in.
    """
    try:
        from agent_sdk_skills.options_ast import extract_project
    except ImportError:                      # pragma: no cover - ships with the plugin
        return None, "options_ast unavailable"

    facts = extract_project(agent_dir)
    if not facts.modules:
        return None, "no module imports claude_agent_sdk"
    names = set(facts.tool_names())
    primary = facts.primary
    if primary is not None:
        names.update(primary.str_list("allowed_tools"))
    if not names:
        return None, ("the agent's tools could not be read statically (options built at "
                      "runtime, or no allowed_tools declared)")
    return names, f"AST read of {len(facts.modules)} module(s)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", default=".",
                        help="the project root, or the evals/ directory")
    parser.add_argument("--agent-dir", help="where the agent modules live, if not the project root")
    parser.add_argument("--strict", action="store_true",
                        help="warnings count towards the exit code")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    evals = Path(layout.evals.dir) if layout.evals else project / "evals"
    if not evals.is_dir():
        # A directory of case directories with no config is still a suite worth
        # validating — a fixture set, or a suite mid-scaffold.
        if any((child / PROMPT_NAME).is_file() for child in target.iterdir() if child.is_dir()):
            evals = target
        else:
            print(f"error: no evals/ directory at {evals}, and no case directories in "
                  f"{target}", file=sys.stderr)
            return EXIT_USAGE

    agent_dir = Path(args.agent_dir).expanduser() if args.agent_dir else project
    agent_tools, tools_source = agent_tools_for(agent_dir)
    agent_servers = None
    if agent_tools is not None:
        # `mcp__<server>__<tool>` -> `<server>`, so MCP020 ("a mock for a server
        # the agent no longer has") can fire without a second AST pass.
        agent_servers = {
            name.split("__")[1] for name in agent_tools
            if name.startswith("mcp__") and len(name.split("__")) > 2
        }
    mock_tools = mock_tool_names(evals)

    config_path = evals / CONFIG_NAME
    config = load_config(config_path)
    copy = inspect_runner_copy(project / "evals" / "runner")

    report = GapReport(subject=str(evals), skill="eval-review")
    report.extend(validate_suite(evals, agent_tools=agent_tools,
                                 mock_tools=mock_tools or None, config=config))
    report.extend(validate_mocks(evals, agent_servers=agent_servers))
    config_findings = validate_config(config, runner_copy_version=copy.version)
    config_findings.extend(stale_against_plugin(config, copy, config_findings))
    report.extend(config_findings)

    summary = suite_summary(evals)
    report.discovered = {
        "cases": summary["cases"],
        "by_category": summary["by_category"],
        "by_grader_type": summary["by_grader_type"],
        "by_tier": summary["by_tier"],
        "cases_without_graders": summary["without_graders"],
        "agent_tools": sorted(agent_tools) if agent_tools is not None else "(undetermined)",
        "agent_tools_source": tools_source,
        "mock_tools": sorted(mock_tools),
        "config": str(config_path) if config.exists else "(missing)",
        "runner_copy": f"{copy.version} ({copy.status})" if copy.present else "not installed",
    }
    if agent_tools is None:
        report.add_gap(
            "tool-crosscheck", "the agent's tool list could not be determined",
            f"{tools_source}; the grader/tool cross-check (EVC020) was skipped rather than "
            "guessed, so a grader naming a tool nothing provides would not be reported here",
            "run `/agent-sdk:agent-review` (load_agent.py) to read the tools from a live "
            "import, or pass --agent-dir if the modules are elsewhere")

    if args.json:
        print(json.dumps({**report.to_dict(), "strict": args.strict}, indent=2))
    else:
        print(report.to_md())

    if summary["cases"] == 0:
        print(f"\nnothing to validate: no case directories under {evals}", file=sys.stderr)
        return EXIT_USAGE
    if report.has_errors():
        return EXIT_FINDINGS
    if args.strict and report.count("warn"):
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
