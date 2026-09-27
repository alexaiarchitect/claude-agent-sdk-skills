"""Library reservations agent behind a custom entry point, not the convention.

What this demonstrates: an agent that does not expose `build_options()` and
does not live in `agent.py`. The builder is `svc/agent.py:make`, named in
`.env.example` as `AGENT_ENTRY=svc.agent:make`, which is how the runner finds
a project that already had a layout before this plugin arrived.

Nothing here is a defect: the options are injectable (a module-level function
returns them), the model comes from the environment, and the isolation the
plugin recommends is set explicitly. What it exercises is entry-point
resolution, plus OPT004 (`Skill` in `allowed_tools`, which is deprecated in
favour of the `skills` option) and OPT003 (`tools` is unset, so the built-ins
are still in context even though the agent lists only MCP tools).

Do not fix the `Skill` entry in `allowed_tools`; it is the defect under test.
"""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

SHELVES: dict[str, int] = {"dune": 2, "emma": 1, "ulysses": 0}

DESK_PROMPT = """You staff the reservations desk of a branch library.

Rules:
1. Check the shelf count before you promise anything.
2. Offer the waiting list when the count is zero; never invent a due date.
3. One short paragraph, and name the tool result you used.
"""


@tool("shelf_count", "Report how many copies of a title are on the shelf", {"title": str})
async def shelf_count(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip().lower()
    if title not in SHELVES:
        return {"content": [{"type": "text", "text": f"{title!r} is not in this branch"}],
                "is_error": True}
    return {"content": [{"type": "text", "text": f"{title}: {SHELVES[title]} on the shelf"}]}


@tool("join_waiting_list", "Add a member to the waiting list for a title",
      {"title": str, "member_id": str})
async def join_waiting_list(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip().lower()
    member = str(args.get("member_id", "")).strip()
    return {"content": [{"type": "text", "text": f"{member} is on the list for {title}"}]}


def make() -> ClaudeAgentOptions:
    """Build the desk options. Named by `AGENT_ENTRY=svc.agent:make`."""
    desk = create_sdk_mcp_server(name="desk", version="2.0.0",
                                tools=[shelf_count, join_waiting_list])
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=DESK_PROMPT,
        mcp_servers={"desk": desk},
        allowed_tools=["mcp__desk__shelf_count", "mcp__desk__join_waiting_list", "Skill"],
        disallowed_tools=["Bash", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        max_turns=5,
        max_budget_usd=0.40,
    )
