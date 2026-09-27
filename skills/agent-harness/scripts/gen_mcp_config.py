#!/usr/bin/env python3
"""Write the wiring for one MCP server: a `.mcp.json` entry or an `mcp_servers=` snippet.

An MCP server reaches the model as tools named `mcp__<server>__<tool>`, where
`<server>` is the key you choose here. Getting that key right is most of the
work: an `allowed_tools` entry with a prefix no server matches is a rule that
can never fire, which is the single most common MCP mistake (`MCP001`).

Three transports, two places to put them:

| Transport | Given | Where it can live |
|---|---|---|
| stdio | a command to run | `.mcp.json` or `mcp_servers=` |
| http / sse | a URL | `.mcp.json` or `mcp_servers=` |
| in-process | `@tool` functions in your own code | `mcp_servers=` only |

`--as mcp-json` writes a `.mcp.json`-compatible file, which the CLI and the SDK
both read — but **only when `strict_mcp_config` is False**, which is the default.
`--as python` writes a snippet for the options object, which is what an eval
wants: it is explicit, it travels with the code, and it survives
`strict_mcp_config=True`.

    gen_mcp_config.py --server github --command npx --arg=-y --arg=@modelcontextprotocol/server-github
    gen_mcp_config.py --server members --url https://members.example.com/mcp [--transport sse]
        [--as mcp-json|python] [--env KEY=VALUE ...] [--out path] [--dry-run] [--force] [--json]

Exit codes: 0 written (or planned, under --dry-run), 1 nothing to write,
2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan, dumps_json  # noqa: E402

#: The server key becomes part of every tool name, so it has to be a plain
#: identifier-ish token. A glob here is refused by the CLI with a startup warning.
SERVER_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")

PYTHON_TEMPLATE = '''"""MCP server wiring for "{server}".

Add this to the options your builder returns. The tools arrive as
`mcp__{server}__<tool>`, and each one still needs permission: name them in
`allowed_tools` (a glob is allowed after the literal `mcp__{server}__` prefix)
or they fall through to `permission_mode`.

`strict_mcp_config=True` is recommended alongside this: without it the session
also loads `.mcp.json`, user settings, plugin-provided servers and claude.ai
connectors, so what the agent can call depends on the machine it runs on.
"""

from __future__ import annotations

MCP_SERVERS = {servers}

#: Everything this server publishes, pre-approved. Replace the glob with the
#: exact tool names once you know them: `list-tools` on the runner prints them.
ALLOWED_TOOLS = ["mcp__{server}__*"]

# In your builder:
#
#     return ClaudeAgentOptions(
#         mcp_servers=MCP_SERVERS,
#         allowed_tools=ALLOWED_TOOLS,
#         strict_mcp_config=True,
#     )
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--server", required=True,
                        help="the key, which becomes the mcp__<server>__ prefix")
    parser.add_argument("--command", help="stdio: the executable to run")
    parser.add_argument("--args", nargs="*", default=[],
                        help="stdio: arguments that do not start with a dash")
    parser.add_argument("--arg", action="append", default=[],
                        help="stdio: one argument, repeatable. Use this form for anything "
                             "starting with a dash: --arg=-y --arg=@scope/package")
    parser.add_argument("--url", help="http/sse: the server URL")
    parser.add_argument("--transport", choices=("http", "sse"), default="http",
                        help="for --url (default: http; the SDK type declares only 'http', "
                             "while .mcp.json also accepts 'streamable-http')")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                        help="environment for a stdio server; use ${VAR} so no secret is "
                             "written into the file")
    parser.add_argument("--as", dest="kind", choices=("mcp-json", "python"), default="python")
    parser.add_argument("--out", help="where to write (default: .mcp.json or "
                                     "mcp_servers_<server>.py)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the write plan and the snippet; write nothing")
    parser.add_argument("--force", action="store_true", help="replace an existing file")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args(argv)

    if not SERVER_KEY.match(args.server):
        print(f"error: {args.server!r} is not usable as a server key: it becomes part of "
              "every tool name (mcp__<server>__<tool>), so use letters, digits, "
              "underscore, dot or hyphen.", file=sys.stderr)
        return EXIT_USAGE
    if bool(args.command) == bool(args.url):
        print("error: give exactly one of --command (stdio) or --url (http/sse). "
              "In-process tools need no config: build them with @tool and "
              "create_sdk_mcp_server, then put the returned object in mcp_servers.",
              file=sys.stderr)
        return EXIT_USAGE

    environment: dict[str, str] = {}
    for pair in args.env:
        key, _, value = pair.partition("=")
        if not key or not _:
            print(f"error: --env expects KEY=VALUE, got {pair!r}", file=sys.stderr)
            return EXIT_USAGE
        environment[key] = value

    arguments = [*args.args, *args.arg]
    if args.command:
        entry: dict[str, object] = {"command": args.command}
        if arguments:
            entry["args"] = arguments
        if environment:
            entry["env"] = environment
    else:
        entry = {"type": args.transport, "url": args.url}
        if environment:
            entry["headers"] = {"Authorization": "Bearer ${MCP_TOKEN}"}

    servers = {args.server: entry}
    if args.kind == "mcp-json":
        out = Path(args.out) if args.out else Path(".mcp.json")
        content = dumps_json({"mcpServers": servers})
    else:
        out = Path(args.out) if args.out else Path(f"mcp_servers_{args.server}.py")
        rendered = json.dumps(servers, indent=4).replace(": true", ": True").replace(
            ": false", ": False").replace(": null", ": None")
        content = PYTHON_TEMPLATE.format(server=args.server, servers=rendered)

    plan = WritePlan()
    plan.add(out, content, force=args.force,
             reason=f"{'stdio' if args.command else args.transport} server "
                    f"\"{args.server}\" -> tools named mcp__{args.server}__*")

    payload = {
        "server": args.server,
        "transport": "stdio" if args.command else args.transport,
        "tool_prefix": f"mcp__{args.server}__",
        "kind": args.kind, "out": str(out), "dry_run": args.dry_run,
        "plan": plan.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(plan.to_md())
        print()
        if args.dry_run:
            print("--- snippet (not written) ---")
            print(content)
    if args.dry_run:
        return EXIT_OK

    written = plan.apply()
    if not written:
        if not args.json:
            print("nothing written; pass --force to replace an existing file")
        return EXIT_FINDINGS
    if not args.json:
        for path in written:
            print(f"wrote {path}")
        print(f"Tools will be named mcp__{args.server}__<tool>; pre-approve them in "
              "allowed_tools or they fall through to permission_mode.")
        if args.kind == "mcp-json":
            print("Note: .mcp.json is ignored when strict_mcp_config=True, and loading it "
                  "at all depends on the machine. An eval should use the python form.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
