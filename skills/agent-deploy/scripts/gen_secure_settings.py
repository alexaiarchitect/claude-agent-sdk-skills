#!/usr/bin/env python3
"""Write a locked-down settings file and the deployment environment beside it.

Two artefacts, because the isolation a hosted agent needs is split across two
places and neither one is enough alone:

* **`agent_settings.json`** — a settings document you pass as the `settings`
  option (a path or inline JSON). Whatever you pass here overrides user,
  project and local filesystem settings; only managed policy ranks higher. So
  it is how you supply one known configuration rather than inherit the host's.
* **`.env.deploy.example`** — the environment variables that cover what the
  options object cannot reach: auto memory, the config directory, the
  credential, telemetry.

The Python snippet it prints ties them together with the three options that do
the rest: `setting_sources=[]`, `strict_mcp_config=True`, and a per-session
`cwd`.

One thing none of this controls: **egress**. `setting_sources` and permission
rules govern what tools the agent may call, not where the process may connect.
A container with a shell and network access can reach anything its network
policy allows. Put an egress proxy with a domain allowlist in front of it, and
let that proxy — not the container — hold the credentials.

    gen_secure_settings.py [<project>] [--allow TOOL ...] [--deny TOOL ...]
                           [--out path] [--dry-run] [--force] [--json]

Exit codes: 0 written (or planned, under --dry-run), 1 nothing to write,
2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import DEFAULT_MODEL  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan, dumps_json  # noqa: E402

DEFAULT_DENY = ["Bash", "WebFetch", "WebSearch", "Write", "Edit", "NotebookEdit"]

ENV_TEMPLATE = """# Deployment environment for a hosted Claude Agent SDK agent.
# Copy to the orchestrator's secret store; never bake any of it into an image.

# --- credential -------------------------------------------------------------
# A hosted or multi-tenant agent must not use a claude.ai subscription
# credential: Anthropic does not allow third-party developers to offer
# claude.ai login or rate limits for their products, including agents built on
# the Agent SDK, unless previously approved.
#
# Pick exactly one:
#   1. an API key, supplied at run time from a secret manager
# ANTHROPIC_API_KEY=
#   2. a gateway that injects the key outside the container (preferred: the
#      agent never sees the credential, and the proxy can allowlist and log)
# ANTHROPIC_BASE_URL=http://claude-gateway.internal:8080
#   3. a cloud provider, with that cloud's own credentials
# CLAUDE_CODE_USE_BEDROCK=1

# --- model ------------------------------------------------------------------
# With none set, a session starts on Claude Code's default, which can change
# under you and is not the cheapest one.
CLAUDE_MODEL={model}

# --- isolation the options object cannot reach ------------------------------
# Auto memory loads into the system prompt regardless of setting_sources.
CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
# ~/.claude.json is read regardless too; give each tenant its own directory.
CLAUDE_CONFIG_DIR=/work/.claude

# --- subagent ceilings ------------------------------------------------------
# Defaults are 3 layers of nesting and 20 concurrent subagents.
CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1
CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=5

# --- telemetry --------------------------------------------------------------
# Off until CLAUDE_CODE_ENABLE_TELEMETRY=1; exporters alone do nothing.
# CLAUDE_CODE_ENABLE_TELEMETRY=1
# CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
# OTEL_TRACES_EXPORTER=otlp
# OTEL_METRICS_EXPORTER=otlp
# OTEL_LOGS_EXPORTER=otlp
# OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
# OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.internal:4318
# OTEL_SERVICE_NAME=reservations-agent
# Content flags stay unset unless the pipeline is approved to store what this
# agent reads: OTEL_LOG_USER_PROMPTS, OTEL_LOG_TOOL_DETAILS,
# OTEL_LOG_TOOL_CONTENT, OTEL_LOG_RAW_API_BODIES.
"""

SNIPPET = '''# The options side of the same configuration.
#
#     options = ClaudeAgentOptions(
#         settings="agent_settings.json",   # overrides user/project/local settings
#         setting_sources=[],               # and loads none of them
#         strict_mcp_config=True,           # no ambient MCP servers or connectors
#         tools=[],                         # only your own MCP tools
#         allowed_tools={allowed},
#         disallowed_tools={denied},
#         permission_mode="dontAsk",        # deny rather than wait for a prompt
#         cwd=session_directory(session_id),
#         max_turns=8,
#         max_budget_usd=1.00,
#         env={{"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}},
#     )
#
# setting_sources=[] is not full isolation: builtin plugins and their skills
# still load, and managed policy settings are read from the host. What it covers
# is user, project and local settings and CLAUDE.md.
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="where to write")
    parser.add_argument("--allow", nargs="*", default=[],
                        help="tools to pre-approve, e.g. mcp__library__*")
    parser.add_argument("--deny", nargs="*", default=DEFAULT_DENY,
                        help=f"tools to deny (default: {' '.join(DEFAULT_DENY)})")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", help="settings path (default: <project>/agent_settings.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the write plan and the files; write nothing")
    parser.add_argument("--force", action="store_true", help="replace existing files")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args(argv)

    root = Path(args.project).expanduser()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    settings = {
        "$comment": (
            "Passed as ClaudeAgentOptions(settings=...). This overrides user, project "
            "and local filesystem settings; only managed policy ranks higher. It does "
            "not control egress: use a proxy with a domain allowlist for that."
        ),
        "model": args.model,
        "permissions": {
            "defaultMode": "dontAsk",
            "allow": list(args.allow),
            "deny": list(args.deny),
        },
        "env": {
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        },
        "includeCoAuthoredBy": False,
        "cleanupPeriodDays": 1,
    }
    settings_out = Path(args.out) if args.out else root / "agent_settings.json"

    plan = WritePlan()
    plan.add(settings_out, dumps_json(settings), force=args.force,
             reason="one known configuration, instead of the host's")
    plan.add(root / ".env.deploy.example", ENV_TEMPLATE.format(model=args.model),
             force=args.force,
             reason="the isolation, credential and telemetry variables the options "
                    "object cannot reach")

    snippet = SNIPPET.format(allowed=list(args.allow), denied=list(args.deny))
    payload = {
        "settings": str(settings_out), "allow": list(args.allow), "deny": list(args.deny),
        "dry_run": args.dry_run, "plan": plan.to_dict(), "snippet": snippet,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(plan.to_md())
        print()
        print(snippet)
        if args.dry_run:
            print("--- agent_settings.json (not written) ---")
            print(dumps_json(settings))
    if args.dry_run:
        return EXIT_OK

    written = plan.apply()
    if not written:
        if not args.json:
            print("nothing written; pass --force to replace existing files")
        return EXIT_FINDINGS
    if not args.json:
        for path in written:
            print(f"wrote {path}")
        print("Egress is still unrestricted: put a proxy with a domain allowlist in "
              "front of the container, and let it hold the credentials.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
