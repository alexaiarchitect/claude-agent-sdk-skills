#!/usr/bin/env python3
"""Do the graders, the agent and the mocks agree on what the tools are called?

Three lists that drift apart silently:

* the tools the **agent** exposes (`@tool` functions in in-process MCP servers,
  plus whatever `allowed_tools` declares);
* the tools the **mocks** provide, under `evals/mocks/<server>/<tool>.md`;
* the tool names the **graders** assert about.

A mismatch does not fail anything. It makes a grader assert nothing, which is
worse: a `no_tool` grader naming a tool that does not exist passes forever, and
a `tool_used` grader naming one fails forever, and neither ever says why.

Four kinds of mismatch, and each has its own remedy:

| Kind | Example | What it means |
|---|---|---|
| unqualified | grader says `reserve_book`, agent exposes `mcp__library__reserve_book` | it matches by suffix, but the trace records the qualified form — write that |
| unknown server | grader says `mcp__billing__charge`, no `billing` anywhere | the grader asserts nothing |
| orphan mock | `evals/mocks/billing/` but the agent has no `billing` server | the mock is dead weight, and a case naming it fails to load (MCP020) |
| untested tool | the agent has `cancel_reservation`, no grader mentions it | it can be removed or broken with no case noticing |

`Task` and `Agent` are the same tool under two names — the CLI reports `Task`,
the docs and the SDK say `Agent` — and `StructuredOutput` / `ToolSearch` are
synthesized by the CLI rather than exposed by the agent. All three are treated
as known everywhere, so they never show up as mismatches.

    crosscheck_tools.py <project> [--agent-dir D] [--json] [--strict]

Exit codes: 0 consistent, 1 mismatches found, 2 nothing to compare (no evals
directory, or the agent's tools could not be read statically).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import SUBAGENT_TOOL_NAMES, SYNTHETIC_TOOLS  # noqa: E402
from agent_sdk_skills.coverage import summarize_cases  # noqa: E402
from agent_sdk_skills.graders import normalize_tool_name  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.mocks import mock_server_names, mock_tool_names  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport,
)

# The sibling script holds the AST tool reader both of these need. No
# bytecode: a stray __pycache__ inside a published skill directory is
# noise in every diff and every package listing.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_cases import agent_tools_for  # noqa: E402

_SRC = "code.claude.com/docs/en/claude-code/mcp (tools reach the model as mcp__<server>__<tool>)"


def _server_of(name: str) -> str | None:
    parts = name.split("__")
    return parts[1] if name.startswith("mcp__") and len(parts) > 2 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--agent-dir", help="where the agent modules live, if not the project root")
    parser.add_argument("--strict", action="store_true",
                        help="an untested tool counts towards the exit code too")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    evals = Path(layout.evals.dir) if layout.evals else project / "evals"
    if not evals.is_dir():
        print(f"error: no evals/ directory at {evals}", file=sys.stderr)
        return EXIT_USAGE

    agent_dir = Path(args.agent_dir).expanduser() if args.agent_dir else project
    agent_tools, tools_source = agent_tools_for(agent_dir)
    mock_tools = {normalize_tool_name(t) for t in mock_tool_names(evals)}
    mock_servers = set(mock_server_names(evals))
    cases = summarize_cases(evals)

    report = GapReport(subject=str(project), skill="eval-review")
    if agent_tools is None:
        report.discovered = {"agent_tools": "(undetermined)", "reason": tools_source}
        report.add_gap(
            "agent-tools", "the agent's tool list could not be read statically", tools_source,
            "run `/agent-sdk:agent-review` (load_agent.py) to read the tools from a live "
            "import, or pass --agent-dir")
        print(report.to_json() if args.json else report.to_md())
        return EXIT_USAGE

    known = {normalize_tool_name(t) for t in agent_tools} | mock_tools
    free_names = set(SYNTHETIC_TOOLS) | {normalize_tool_name(n) for n in SUBAGENT_TOOL_NAMES}
    agent_servers = {s for s in (_server_of(t) for t in agent_tools) if s}

    grader_tools: dict[str, list[str]] = {}
    for case in cases:
        for tool in case["tools"]:
            grader_tools.setdefault(tool, []).append(str(case["name"]))

    for tool, users in sorted(grader_tools.items()):
        if tool in known or tool in free_names:
            continue
        where = ", ".join(sorted(set(users)))
        qualified = sorted(t for t in known if t.endswith(f"__{tool}"))
        if qualified:
            report.add("EVC020", "warn", "grader",
                       f"{tool!r} is an unqualified name; the agent exposes {qualified[0]!r}",
                       path=str(evals), locator=where,
                       fix=f"write `{qualified[0]}`: the model sees the qualified form and the "
                           "trace records it, so the bare name matches only by suffix",
                       source=_SRC)
            continue
        server = _server_of(tool)
        if server and server not in agent_servers and server not in mock_servers:
            report.add("EVC020", "warn", "grader",
                       f"{tool!r} names server {server!r}, which is neither the agent's nor a mock",
                       path=str(evals), locator=where,
                       fix="add the server to the agent, add a mock under "
                           f"mocks/{server}/, or fix the name",
                       source=_SRC)
            continue
        report.add("EVC020", "warn", "grader",
                   f"{tool!r} is neither an agent tool nor a mock",
                   path=str(evals), locator=where,
                   fix="known tools: " + ", ".join(sorted(known)[:8])
                       + ("…" if len(known) > 8 else ""),
                   source=_SRC)

    for server in sorted(mock_servers - agent_servers):
        report.add("MCP020", "warn", "mocks",
                   f"mock server {server!r} is not among the agent's MCP servers",
                   path=str(evals / "mocks" / server),
                   fix="the agent may have renamed or dropped it. A case naming a mock the "
                       "agent does not have cannot load, and one that does not name it runs "
                       "against the real server.",
                   source=_SRC)

    untested = sorted(t for t in {normalize_tool_name(t) for t in agent_tools}
                      if t not in grader_tools and t not in free_names)
    for tool in untested:
        report.add_gap(
            f"untested-{tool}", f"no grader mentions `{tool}`",
            "a tool no case asserts about can be removed, renamed or broken without any case "
            "noticing — and the agent's behaviour around it is unspecified",
            "add a `tool_used` grader to the case that should call it, or a `no_tool` grader "
            "to a case that must not")

    report.discovered = {
        "agent_tools": sorted(normalize_tool_name(t) for t in agent_tools),
        "agent_tools_source": tools_source,
        "agent_servers": sorted(agent_servers),
        "mock_servers": sorted(mock_servers),
        "mock_tools": sorted(mock_tools),
        "grader_tools": sorted(grader_tools),
        "untested_tools": untested,
    }

    if args.json:
        print(json.dumps({**report.to_dict(), "strict": args.strict}, indent=2))
    else:
        print(report.to_md())

    if report.findings:
        return EXIT_FINDINGS
    if args.strict and report.gaps:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
