"""Library reservations agent: the eval-ready convention this plugin scaffolds.

An in-process MCP server exposes three deterministic tools over an in-memory
catalog, `build_options()` returns the options the runner copies and overrides,
and `run()` is the streaming entry point the runner and `main()` share.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    create_sdk_mcp_server,
    tool,
)

CATALOG: dict[str, dict[str, Any]] = {
    "dune": {"title": "Dune", "copies": 2, "reserved_by": []},
    "emma": {"title": "Emma", "copies": 1, "reserved_by": ["member-7"]},
    "ulysses": {"title": "Ulysses", "copies": 0, "reserved_by": []},
}

SYSTEM_PROMPT = """You are the reservations desk of a small library.

Rules:
1. Look a book up before reserving it; never reserve a title you have not looked up.
2. A member may hold at most one copy of a title. If the member already holds it,
   refuse politely and do not call reserve_book.
3. If no copy is available, offer to cancel a reservation only when the member asks.
4. Answer in one short paragraph and name the tool results you relied on.
"""


def _text(payload: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}]}


@tool("lookup_book", "Find a book by title and report copies and holders", {"title": str})
async def lookup_book(args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("title", "")).strip().lower()
    book = CATALOG.get(key)
    if not book:
        return _text(f"No book titled {args.get('title')!r} in the catalog.")
    return _text(
        f"{book['title']}: {book['copies']} copies available; reserved by {book['reserved_by'] or 'nobody'}."
    )


@tool("reserve_book", "Reserve one copy of a title for a member", {"title": str, "member_id": str})
async def reserve_book(args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("title", "")).strip().lower()
    member = str(args.get("member_id", "")).strip()
    book = CATALOG.get(key)
    if not book:
        return {"content": [{"type": "text", "text": "unknown title"}], "is_error": True}
    if member in book["reserved_by"]:
        return {"content": [{"type": "text", "text": f"{member} already holds {book['title']}"}], "is_error": True}
    if book["copies"] <= 0:
        return {"content": [{"type": "text", "text": f"no copies of {book['title']} available"}], "is_error": True}
    book["copies"] -= 1
    book["reserved_by"].append(member)
    return _text(f"Reserved {book['title']} for {member}; {book['copies']} copies left.")


@tool("cancel_reservation", "Cancel a member's reservation of a title", {"title": str, "member_id": str})
async def cancel_reservation(args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("title", "")).strip().lower()
    member = str(args.get("member_id", "")).strip()
    book = CATALOG.get(key)
    if not book or member not in book["reserved_by"]:
        return {"content": [{"type": "text", "text": "no such reservation"}], "is_error": True}
    book["reserved_by"].remove(member)
    book["copies"] += 1
    return _text(f"Cancelled {book['title']} for {member}; {book['copies']} copies available.")


def build_options() -> ClaudeAgentOptions:
    """The options the runner copies and overrides per case."""
    library = create_sdk_mcp_server(
        name="library", version="1.0.0", tools=[lookup_book, reserve_book, cancel_reservation]
    )
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"library": library},
        allowed_tools=["mcp__library__lookup_book", "mcp__library__reserve_book",
                       "mcp__library__cancel_reservation"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        max_turns=6,
        max_budget_usd=0.50,
    )


async def run(prompt: str, options: ClaudeAgentOptions | None = None) -> AsyncIterator[Message]:
    """Stream every message of one session; the runner consumes this."""
    async with ClaudeSDKClient(options=options or build_options()) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            yield message


async def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Reserve Dune for member-42."
    async for message in run(prompt):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text)
                elif hasattr(block, "name"):
                    print(f"[tool] {block.name} {getattr(block, 'input', '')}")
        elif hasattr(message, "total_cost_usd"):
            print(f"[done] {message.subtype} est. ${message.total_cost_usd or 0:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
