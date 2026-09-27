"""The smallest eval-ready agent: one in-process MCP server, two tools.

`build_options()` is the convention the runner loads; `run()` is the streaming
entry point a human can use from the command line. The catalog is in memory and
deterministic, so a case asserting on tool results asserts on the agent, not on
a database.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
    tool,
)

CATALOG: dict[str, dict[str, Any]] = {
    "dune": {"title": "Dune", "copies": 2},
    "emma": {"title": "Emma", "copies": 0},
}

SYSTEM_PROMPT = """You are a library catalogue desk.

Rules:
1. Look a title up with lookup_book before saying anything about its availability.
2. Never reserve a title with zero copies; say so plainly instead.
3. Answer in one short sentence.
"""


def _text(payload: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}]}


@tool("lookup_book", "Report how many copies of a title are available", {"title": str})
async def lookup_book(args: dict[str, Any]) -> dict[str, Any]:
    book = CATALOG.get(str(args.get("title", "")).strip().lower())
    if not book:
        return _text(f"No title {args.get('title')!r} in the catalogue.")
    return _text(f"{book['title']}: {book['copies']} copies available.")


@tool("reserve_book", "Reserve one copy of a title", {"title": str, "member_id": str})
async def reserve_book(args: dict[str, Any]) -> dict[str, Any]:
    book = CATALOG.get(str(args.get("title", "")).strip().lower())
    if not book:
        return {"content": [{"type": "text", "text": "unknown title"}], "is_error": True}
    if book["copies"] <= 0:
        return {"content": [{"type": "text", "text": f"no copies of {book['title']}"}],
                "is_error": True}
    book["copies"] -= 1
    return _text(f"Reserved {book['title']}; {book['copies']} left.")


def build_options() -> ClaudeAgentOptions:
    library = create_sdk_mcp_server(name="library", version="1.0.0",
                                   tools=[lookup_book, reserve_book])
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"library": library},
        allowed_tools=["mcp__library__lookup_book", "mcp__library__reserve_book"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        max_turns=4,
        max_budget_usd=0.25,
    )


async def run(prompt: str, options: ClaudeAgentOptions | None = None) -> AsyncIterator[Any]:
    async with ClaudeSDKClient(options=options or build_options()) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            yield message


async def _main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Is Dune available?"
    async for message in run(prompt):
        for block in getattr(message, "content", []) or []:
            if getattr(block, "text", None):
                print(block.text)


if __name__ == "__main__":
    asyncio.run(_main())
