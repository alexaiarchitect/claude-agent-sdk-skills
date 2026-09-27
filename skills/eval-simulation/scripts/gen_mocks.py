#!/usr/bin/env python3
"""Derive `evals/mocks/<server>/<tool>.md` from the agent's own tool contracts.

A mock is only worth having if it advertises the same input schema the real tool
does. Hand-written ones drift the moment a `@tool` gains a field: the schema the
in-process server advertises is what the model is shown *and* what the runner
validates input against before the handler runs, so a stale schema makes every
call an error result the mock never sees. So this reads the schemas out of the
agent's source with the AST reader — never by importing it — and writes one file
per tool.

    gen_mocks.py <project> [--server NAME] [--tool NAME] [--from-agent]
                 [--out evals/mocks] [--force] [--dry-run] [--json]

What it writes, per in-process `@tool`:

* `description:` the tool's own description, so the model reads the same words;
* `schema:` the declared input keys and their types;
* a body that substitutes `{{input.<key>}}` for every declared key, which is the
  only templating the runner supports (`{{input.x}}`, `{{input.x|fallback}}`,
  `{{file:…}}`), plus a note saying what to replace it with.

An external `mcp_servers` entry (stdio, http, sse) has no schema in the source,
so it gets one stub per server with a TODO schema and a pointer at
`python -m agent_sdk_evals list-tools --probe`, which asks the live server.

Nothing is overwritten without `--force`, and `--dry-run` writes nothing at all.

Exit codes: 0 written (or planned), 1 nothing to generate, 2 usage — no such
project, or no agent module to read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import frontmatter  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.options_ast import ToolDef, extract_project  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan  # noqa: E402

#: External server kinds that cannot be read statically.
EXTERNAL_KINDS = ("stdio", "http", "sse", "dynamic", "unknown")

STUB_TOOL = "replace_me"

BODY_NOTE = (
    "Replace the line above with what the real tool returns. Only `text` and\n"
    "`image` content survives the SDK intact — a `resource_link`, a text\n"
    "`resource` or anything binary is flattened or dropped with a warning — so\n"
    "keep this prose. Inside double braces the runner expands `input.x`,\n"
    "`input.x|fallback` and `file:fixtures/…` — and only those three."
)

STUB_BODY = (
    "TODO: the canned result this tool should return.\n\n"
    "`{server}` is an external MCP server, so its tool names and input schemas\n"
    "are not in the agent's source. Ask the live server for them:\n\n"
    "    python -m agent_sdk_evals list-tools <evals-dir> --probe\n\n"
    "then rename this file to the tool name, replace the schema, and delete this\n"
    "note. A mock file's stem *is* the tool name and its directory *is* the\n"
    "server name; the model sees `mcp__{server}__<stem>`."
)


def tools_by_server(facts: Any, fallback_server: str | None) -> tuple[dict[str, list[ToolDef]], list[str]]:
    """`{server: [ToolDef]}` for the in-process servers, plus notes."""
    by_func = {tool.func_name: tool for tool in facts.tools}
    grouped: dict[str, list[ToolDef]] = {}
    claimed: set[str] = set()
    notes: list[str] = []
    for server in facts.sdk_servers:
        if not server.name:
            notes.append(f"a create_sdk_mcp_server(...) call at line {server.lineno} has no literal "
                         "name; its tools cannot be placed")
            continue
        for ref in server.tool_refs:
            tool = by_func.get(ref)
            if tool is None or not tool.tool_name:
                continue
            grouped.setdefault(server.name, []).append(tool)
            claimed.add(ref)
    loose = [t for t in facts.tools if t.func_name not in claimed and t.tool_name]
    if loose:
        target = fallback_server or (list(grouped)[0] if len(grouped) == 1 else None)
        if target:
            grouped.setdefault(target, []).extend(loose)
        else:
            notes.append(
                f"{len(loose)} @tool function(s) are not passed to any create_sdk_mcp_server(...) "
                "call this reader could resolve; pass --server NAME to place them"
            )
    return grouped, notes


def external_servers(facts: Any, known: set[str]) -> list[str]:
    """Servers mounted from outside the process, which have no source schema."""
    out: list[str] = []
    for ref in facts.mcp_servers:
        if ref.key in known or ref.key in out:
            continue
        if ref.kind in EXTERNAL_KINDS:
            out.append(ref.key)
    return sorted(out)


def schema_for(tool: ToolDef) -> tuple[dict[str, str], str | None]:
    """The schema mapping to write, and a note when it had to be invented."""
    if tool.schema_keys:
        return ({key: tool.schema_types.get(key) or "str" for key in tool.schema_keys}, None)
    return (
        {"TODO_input": "str"},
        f"the schema of `{tool.tool_name}` is {tool.schema_kind}: it could not be read "
        "statically, so the mock advertises a placeholder. Input is validated against "
        "this schema before the handler runs, so fix it before the mock is used.",
    )


def body_for(tool: ToolDef, server: str, keys: list[str], invented: bool) -> str:
    """A canned result that uses every declared input, and says so."""
    if invented:
        first = f"TODO: what `{tool.tool_name}` returns."
    elif keys:
        shown = ", ".join(f"{key}={{{{input.{key}|(unset)}}}}" for key in keys)
        first = f"`{tool.tool_name}` on the {server} mock: {shown}. TODO: the real result."
    else:
        first = f"`{tool.tool_name}` on the {server} mock returned. TODO: the real result."
    return f"{first}\n\n{BODY_NOTE}"


def mock_file(tool: ToolDef, server: str) -> str:
    schema, note = schema_for(tool)
    meta: dict[str, Any] = {
        "type": "canned",
        "description": tool.description or f"mock {tool.tool_name} for {server}",
        "schema": schema,
    }
    body = body_for(tool, server, list(schema) if note is None else [], note is not None)
    if note:
        body = f"{body}\n\nNote: {note}"
    return frontmatter.dump(meta, body)


def stub_file(server: str) -> str:
    meta: dict[str, Any] = {
        "type": "canned",
        "description": f"TODO: what this {server} tool does, in the words the model reads",
        "schema": {"TODO_input": "str"},
    }
    return frontmatter.dump(meta, STUB_BODY.format(server=server))


def build(project: Path, out_dir: Path, *, only_server: str | None, only_tool: str | None,
          force: bool) -> tuple[WritePlan, dict[str, Any]]:
    facts = extract_project(project)
    grouped, notes = tools_by_server(facts, only_server)
    stubs = external_servers(facts, set(grouped))

    plan = WritePlan()
    generated: list[dict[str, str]] = []
    for server in sorted(grouped):
        if only_server and server != only_server:
            continue
        for tool in sorted(grouped[server], key=lambda t: t.tool_name or ""):
            if only_tool and tool.tool_name != only_tool:
                continue
            target = out_dir / server / f"{tool.tool_name}.md"
            plan.add(target, mock_file(tool, server), force=force,
                     reason=f"mcp__{server}__{tool.tool_name}, schema from {tool.path}:{tool.lineno}")
            generated.append({"server": server, "tool": tool.tool_name or "",
                              "qualified": f"mcp__{server}__{tool.tool_name}",
                              "schema_kind": tool.schema_kind})
    for server in stubs:
        if only_server and server != only_server:
            continue
        if only_tool:
            continue
        target = out_dir / server / f"{STUB_TOOL}.md"
        plan.add(target, stub_file(server), force=force,
                 reason=f"external server {server!r}: stub with a TODO schema")
        generated.append({"server": server, "tool": STUB_TOOL,
                          "qualified": f"mcp__{server}__{STUB_TOOL}", "schema_kind": "stub"})

    discovered = {
        "agent_modules": facts.scanned,
        "in_process_servers": sorted(grouped),
        "external_servers": stubs,
        "tools": generated,
        "notes": notes + list(facts.notes),
    }
    return plan, discovered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", help="the agent project (or a single module) to read")
    parser.add_argument("--server", help="only this MCP server")
    parser.add_argument("--tool", help="only this tool name (unqualified)")
    parser.add_argument("--from-agent", action="store_true",
                        help="read the schemas from the agent's source; this is the only "
                             "mode, and the flag states it explicitly")
    parser.add_argument("--out", help="mock root (default: <evals>/mocks)")
    parser.add_argument("--force", action="store_true", help="replace files that already exist")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.exists():
        print(f"no such project: {project}", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(project)
    evals_dir = Path(layout.evals.dir) if layout.evals else project / "evals"
    out_dir = Path(args.out).expanduser() if args.out else evals_dir / "mocks"

    plan, discovered = build(project, out_dir, only_server=args.server,
                             only_tool=args.tool, force=args.force)

    if not plan.items:
        message = "no in-process @tool functions and no external mcp_servers to mock"
        if args.json:
            print(json.dumps({"out": str(out_dir), "discovered": discovered,
                              "plan": plan.to_dict(), "written": [], "reason": message}, indent=2))
        else:
            print(message)
            for note in discovered["notes"]:
                print(f"- {note}")
        return EXIT_FINDINGS

    written: list[str] = []
    if not args.dry_run:
        written = plan.apply()

    if args.json:
        print(json.dumps({"out": str(out_dir), "discovered": discovered,
                          "plan": plan.to_dict(), "dry_run": args.dry_run,
                          "written": written}, indent=2))
        return EXIT_OK

    print(plan.to_md())
    for note in discovered["notes"]:
        print(f"\nNote: {note}")
    if args.dry_run:
        print("\n(--dry-run: nothing was written)")
    else:
        for path in written:
            print(f"wrote {path}")
        skipped = [i for i in plan.items if i.action == "skip"]
        if skipped:
            print(f"{len(skipped)} file(s) already existed; pass --force to replace them")
        print("\nNext: python3 ${CLAUDE_SKILL_DIR}/scripts/validate_sim.py " + str(project))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
