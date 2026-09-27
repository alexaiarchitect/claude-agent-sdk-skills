"""Library reservations agent that talks to external MCP servers only.

What this demonstrates: stdio and HTTP `mcp_servers` entries instead of
in-process `@tool` functions, and MCP001 — `allowed_tools` pre-approves
`mcp__audit__record_loan`, but no server named `audit` is configured, so that
name can never match a tool and the rule is dead.

Also demonstrates MCP002 (the `catalogd` stdio command is not a real binary,
so it will not be on PATH), OPT001 (`allowed_tools` without `disallowed_tools`
while the built-ins are still in context), OPT010/OPT011 (no `max_turns`, no
`max_budget_usd`) and AGT004 (`health_check()` calls `query()` with no options
at all, so that session runs on SDK defaults).

Do not fix this file. Every one of those is deliberate.
"""

from __future__ import annotations

import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, query

DESK_PROMPT = """You are the reservations desk of a county library system.

Rules:
1. Look a title up in the catalogue before you reserve it.
2. Record every loan you make, and say which record id you got back.
3. Refuse a second copy of a title a member already holds.
"""


def build_options() -> ClaudeAgentOptions:
    """Options pointing at the two servers this deployment runs beside it."""
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=DESK_PROMPT,
        mcp_servers={
            "catalogue": {
                "command": "catalogd",
                "args": ["--serve-mcp", "--catalog", "/srv/library/catalog.db"],
            },
            "members": {
                "type": "http",
                "url": "https://members.library.invalid/mcp",
            },
        },
        allowed_tools=[
            "mcp__catalogue__find_title",
            "mcp__catalogue__reserve",
            "mcp__members__lookup",
            "mcp__audit__record_loan",
        ],
        permission_mode="dontAsk",
    )


async def health_check() -> None:
    """Ask for one word to prove the CLI answers. No options: AGT004."""
    async for message in query(prompt="Reply with exactly: ready"):
        print(message)


async def run(prompt: str) -> None:
    async with ClaudeSDKClient(options=build_options()) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            print(message)


if __name__ == "__main__":
    asyncio.run(run("Reserve 'Dune' for member-42."))
