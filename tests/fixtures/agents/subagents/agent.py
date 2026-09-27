"""Library reservations agent that delegates to two programmatic subagents.

What this demonstrates: the `agents` option with `AgentDefinition`s, the
subagent tool named in `allowed_tools` (the CLI reports it as `Task`, the docs
and SDK call it `Agent`, so a check has to accept both), and three subagent
design findings:

* SUB001 — `shelf-auditor` omits `tools`, so it inherits every tool available
  to subagents rather than the read-only set its prompt describes.
* SUB003 — `shelf-auditor` sets no `maxTurns`, so nothing bounds its loop.
* SUB002 — `overdue-chaser` pins `claude-haiku-4-5-20251001`, a retiring id.

`.claude/agents/` also holds a filesystem-defined subagent, which does not load
because `setting_sources=[]` (SUB010).

Do not fix this file. Each gap is a check's subject.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
    tool,
)

LOANS: dict[str, list[str]] = {"dune": ["member-7"], "emma": []}

DESK_PROMPT = """You coordinate a county library's reservations desk.

Rules:
1. Delegate a shelf count to the shelf-auditor subagent; do not guess counts.
2. Delegate overdue chasing to the overdue-chaser subagent.
3. Summarise what the subagents reported; never invent a figure they did not give.
"""


@tool("loan_record", "Report who currently holds a title", {"title": str})
async def loan_record(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip().lower()
    holders = LOANS.get(title)
    if holders is None:
        return {"content": [{"type": "text", "text": f"{title!r} is not stocked"}],
                "is_error": True}
    return {"content": [{"type": "text", "text": f"{title}: held by {holders or 'nobody'}"}]}


def build_options() -> ClaudeAgentOptions:
    """Options with two subagents and the subagent tool pre-approved."""
    loans = create_sdk_mcp_server(name="loans", version="1.0.0", tools=[loan_record])
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=DESK_PROMPT,
        mcp_servers={"loans": loans},
        allowed_tools=["mcp__loans__loan_record", "Task", "Read", "Grep"],
        disallowed_tools=["Bash", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        max_turns=8,
        max_budget_usd=1.00,
        agents={
            "shelf-auditor": AgentDefinition(
                description="Counts copies on the shelf. Use before promising a reservation.",
                prompt=(
                    "You audit shelf counts. Read the loan record, report the number of "
                    "free copies, and say nothing else."
                ),
            ),
            "overdue-chaser": AgentDefinition(
                description="Drafts a reminder for an overdue loan.",
                prompt="You draft one polite sentence reminding a member a title is overdue.",
                tools=["mcp__loans__loan_record"],
                model="claude-haiku-4-5-20251001",
                maxTurns=3,
            ),
        },
    )


async def run(prompt: str) -> None:
    async with ClaudeSDKClient(options=build_options()) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            print(message)


if __name__ == "__main__":
    asyncio.run(run("How many copies of Dune are free, and chase anything overdue."))
