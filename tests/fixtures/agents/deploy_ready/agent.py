"""Library reservations agent shaped for a container, not a laptop.

What this demonstrates: a hosted agent that passes the deployment checks. The
credential never enters the image — `ANTHROPIC_BASE_URL` points at a gateway
that injects the key outside the container — the ambient configuration of
whatever host it lands on is switched off with `setting_sources=[]` and
`strict_mcp_config=True`, every session gets its own working directory, and
both a turn ceiling and a spend ceiling bound a run.

Nothing here is a defect. The fixture exists so the deployment checks have a
project that comes back clean, and so a test can plant a single problem (a
subscription token in `.env`, say) and watch exactly one finding appear.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server, tool

SHELF: dict[str, int] = {"dune": 2, "emma": 1, "ulysses": 0}

DESK_PROMPT = """You are the reservations desk of a library, serving one member at a time.

Rules:
1. Check the shelf before promising a copy.
2. Never reveal another member's name.
3. Answer in one short paragraph.
"""


@tool("shelf_count", "Report how many copies of a title are free", {"title": str})
async def shelf_count(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip().lower()
    if title not in SHELF:
        return {"content": [{"type": "text", "text": f"{title!r} is not stocked"}],
                "is_error": True}
    return {"content": [{"type": "text", "text": f"{title}: {SHELF[title]} free"}]}


@tool("hold_copy", "Place a hold on one copy for the current member", {"title": str})
async def hold_copy(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip().lower()
    if SHELF.get(title, 0) <= 0:
        return {"content": [{"type": "text", "text": f"no copies of {title} free"}],
                "is_error": True}
    SHELF[title] -= 1
    return {"content": [{"type": "text", "text": f"held one copy of {title}"}]}


def session_dir(session_id: str) -> Path:
    """One working directory per session, under the container's scratch mount."""
    root = Path(os.getenv("AGENT_WORK_ROOT", "/work"))
    path = root / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_options(session_id: str = "local") -> ClaudeAgentOptions:
    """Options for one hosted session."""
    desk = create_sdk_mcp_server(name="desk", version="1.0.0",
                                tools=[shelf_count, hold_copy])
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=DESK_PROMPT,
        mcp_servers={"desk": desk},
        allowed_tools=["mcp__desk__shelf_count", "mcp__desk__hold_copy"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
        tools=[],
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        cwd=str(session_dir(session_id)),
        max_turns=6,
        max_budget_usd=0.50,
        env={
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
        },
    )


async def run(prompt: str, session_id: str = "local") -> None:
    async with ClaudeSDKClient(options=build_options(session_id)) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            print(message)


if __name__ == "__main__":
    asyncio.run(run(os.environ.get("TASK_PROMPT", "Is Dune available?")))
