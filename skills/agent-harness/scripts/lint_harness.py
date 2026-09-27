#!/usr/bin/env python3
"""Check an agent's harness: hooks, permissions, MCP servers and subagents.

The harness is the part of an Agent SDK program that is wired rather than
written: a dict of hook events, an allow list, a server config, a set of
subagent definitions. It fails quietly. A hook that returns the wrong shape
raises nothing — the decision simply never arrives. An `mcp__` prefix for a
server that does not exist is a rule that can never match. A subagent with no
`maxTurns` runs until it stops wanting to.

So this reads the same syntax tree `lint_agent.py` reads and reports only the
wiring: `HOK` hooks, `MCP` servers and tools, the permission subset of `OPT`,
and `SUB` subagent design. For entry points, model policy and credentials, run
`../agent-review/scripts/lint_agent.py` instead; the two overlap on purpose so
either one alone is a complete answer to its own question.

Report only. It never edits.

    lint_harness.py <project> [--format json|md] [--json] [--no-path-check]

Exit codes: 0 no errors, 1 errors, 2 nothing to check.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
# The finding rules are shared with the review skill's linter, which owns them.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-review" / "scripts"))

from _checks import (  # noqa: E402
    hook_findings, mcp_findings, permission_findings, setting_sources_of,
    subagent_findings,
)
from agent_sdk_skills import PYTHON_HOOK_EVENTS  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.options_ast import extract_project  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport, Option,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="project root or agent module")
    parser.add_argument("--format", choices=("json", "md"), default="md")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        help="print the gap report as JSON instead of markdown")
    parser.add_argument("--no-path-check", action="store_true",
                        help="skip looking for stdio MCP commands on this machine's PATH")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(target)
    root = Path(layout.project_root or target)
    # One named module is reviewed alone: reading its whole directory would
    # report a sibling's hooks, servers and subagents against it.
    facts = extract_project(target if target.is_file() else root)
    if not facts.modules:
        print(f"error: no Claude Agent SDK usage under {target}", file=sys.stderr)
        return EXIT_USAGE

    report = GapReport(subject=str(root), skill="agent-harness")
    claude = layout.claude
    primary = facts.primary

    report.extend(hook_findings(facts, claude))
    report.extend(mcp_findings(facts, check_path=not args.no_path_check))
    report.extend(permission_findings(facts))
    report.extend(subagent_findings(facts, claude))

    if primary is not None and facts.hooks and not primary.has("include_hook_events"):
        report.add("HOK031", "info", "hooks",
                   "hooks are registered but include_hook_events is not set, so the "
                   "message stream carries no record that they fired",
                   path=primary.path, locator=f"line {primary.lineno}",
                   fix="set include_hook_events=True when you want hook activity in the "
                       "trace. On its own it emits nothing: a hook has to be registered "
                       "as well, which it is here.",
                   source="claude-agent-sdk 0.2.162 types.py:2199")

    # Gaps: things absent rather than wrong.
    if not facts.hooks:
        report.add_gap("GAP-HOOKS", "No hooks",
                       "nothing observes or gates a tool call, so a run leaves no audit "
                       "trail and a dangerous call has only the permission rules between "
                       "it and the filesystem",
                       "a PreToolUse hook is also the only way to see every tool call: "
                       "can_use_tool fires only when the rules evaluate to \"ask\". "
                       "Generate one with scripts/gen_hook.py.")
    if not facts.server_names:
        report.add_gap("GAP-MCP", "No MCP servers",
                       "the agent has only built-in tools, so nothing it does is specific "
                       "to this domain and nothing can be mocked in an eval",
                       "in-process tools with @tool and create_sdk_mcp_server are the "
                       "cheapest way to give it a real contract; scripts/gen_mcp_config.py "
                       "writes the wiring for an external server.")
    if not facts.agents and claude and not claude.agents:
        report.add_gap("GAP-SUBAGENTS", "No subagents",
                       "every step shares one context window, so a long exploration "
                       "accumulates in the main conversation",
                       "delegate the parts whose intermediate results the parent does not "
                       "need; scripts/gen_subagent.py writes an AgentDefinition.")

    explicit, sources = setting_sources_of(facts)
    report.discovered = {
        "hooks": {
            "events": sorted({h.event for h in facts.hooks}),
            "matchers": [
                {"event": h.event, "matcher": h.matcher, "callbacks": h.callbacks,
                 "timeout": h.timeout}
                for h in facts.hooks
            ],
            "unsupported_events": sorted(
                {h.event for h in facts.hooks if h.event not in PYTHON_HOOK_EVENTS}
            ),
            "in_settings_json": bool(claude and claude.hooks_in_settings),
        },
        "permissions": {
            "permission_mode": (primary.get("permission_mode").as_str() if primary and primary.has("permission_mode") else None),
            "tools": (primary.get("tools").value if primary and primary.has("tools") else None),
            "allowed_tools": primary.str_list("allowed_tools") if primary else [],
            "disallowed_tools": primary.str_list("disallowed_tools") if primary else [],
            "can_use_tool": bool(primary and primary.has("can_use_tool")),
        },
        "mcp": {
            "servers": [
                {"name": s.key, "kind": s.kind, "command": s.command, "url": s.url}
                for s in facts.mcp_servers
            ],
            "in_process_tools": facts.tool_names(),
            "strict_mcp_config": (primary.get("strict_mcp_config").value if primary and primary.has("strict_mcp_config") else False),
            "mcp_json": claude.mcp_json if claude else None,
        },
        "subagents": {
            "programmatic": [
                {"name": a.name, "tools": a.tools.as_str_list() if a.tools else None,
                 "model": a.model.as_str() if a.model else None,
                 "max_turns": a.max_turns.value if a.max_turns else None}
                for a in facts.agents
            ],
            "files": claude.agents if claude else [],
        },
        "context": {
            "setting_sources": sources if explicit else "not set (the CLI default: user, project, local)",
            "claude_md": claude.claude_md if claude else [],
            "settings_files": claude.settings if claude else [],
        },
    }

    if report.count("error"):
        report.add_option(Option(
            key="1", label="Fix the wiring errors", recommended=True,
            detail="each one fails silently today: nothing raises, the effect simply does "
                   "not happen",
        ))
    else:
        report.add_option(Option(
            key="1", label="Generate what is missing", recommended=bool(report.gaps),
            detail="gen_hook.py for an audit, deny, inject or latency hook; "
                   "gen_mcp_config.py for a server; gen_subagent.py for an AgentDefinition. "
                   "All three show a write plan first and honour --dry-run.",
            writes=["a snippet file, or .claude/agents/<name>.md, on approval"],
        ))
    report.add_option(Option(
        key=str(len(report.options) + 1), label="Review the rest of the agent",
        detail="entry point, model policy, credentials and ceilings: /agent-sdk:agent-review",
    ))

    print(report.render(args.format))
    return EXIT_FINDINGS if report.count("error") else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
