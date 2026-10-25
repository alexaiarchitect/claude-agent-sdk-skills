"""Library reservations agent whose tool set is designed badly on purpose.

What this demonstrates: every `design_check.py` rule, each from one deliberate
choice that a real agent grows into one reasonable-looking commit at a time.

* DSG001 — `lookup` has a 12-character description.
* DSG002 — `lookup` takes a parameter named `id`: book, member or hold?
* DSG003 — `list_books` returns the whole catalogue with no limit, page or query.
* DSG004 — five tools on the `catalog` server share no name part.
* DSG005 — `find_book`, `search_books` and `lookup` all read one book back.
* DSG006 — 27 tools of an external ILS server are pre-approved by name, so the
  model chooses among 32 tool definitions.
* DSG007 — the `catalog-search` subagent is told what to do, never what to
  return or where to stop.
* DSG008 — no `max_turns`, no `max_budget_usd`, no compaction setting.

It still follows the plugin's entry-point convention (`build_options()`,
`run()`), so it loads and runs like the `good` fixture.

Do not fix this file. Each defect is a check's subject.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    create_sdk_mcp_server,
    tool,
)

CATALOG: dict[str, dict[str, Any]] = {
    "b-001": {"title": "Dune", "copies": 2, "holds": []},
    "b-002": {"title": "Emma", "copies": 1, "holds": ["member-7"]},
    "b-003": {"title": "Ulysses", "copies": 0, "holds": []},
}

SYSTEM_PROMPT = """You are the reservations desk of a small library.

Find the book the member asks for, then place a hold on it for them.
Use the catalog-search subagent when a request needs searching.
"""



def _text(payload: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}]}


@tool("list_books", "List the books in the library catalogue.", {})
async def list_books(args: dict[str, Any]) -> dict[str, Any]:
    return _text(json.dumps(CATALOG))


@tool("lookup", "Look up item", {"id": str})
async def lookup(args: dict[str, Any]) -> dict[str, Any]:
    book = CATALOG.get(str(args.get("id", "")))
    return _text(json.dumps(book) if book else "not found")


@tool("find_book", "Find a book in the catalogue by its title and return its record.", {"title": str})
async def find_book(args: dict[str, Any]) -> dict[str, Any]:
    wanted = str(args.get("title", "")).strip().lower()
    hits = {k: v for k, v in CATALOG.items() if v["title"].lower() == wanted}
    return _text(json.dumps(hits) if hits else "not found")


@tool("search_books", "Search the catalogue for books whose title contains the query.", {"query": str})
async def search_books(args: dict[str, Any]) -> dict[str, Any]:
    needle = str(args.get("query", "")).strip().lower()
    hits = {k: v for k, v in CATALOG.items() if needle in v["title"].lower()}
    return _text(json.dumps(hits))


@tool("place_hold", "Place a hold on a book for a member, given the book key and member id.",
      {"book_key": str, "member_id": str})
async def place_hold(args: dict[str, Any]) -> dict[str, Any]:
    book = CATALOG.get(str(args.get("book_key", "")))
    member = str(args.get("member_id", "")).strip()
    if not book:
        return {"content": [{"type": "text", "text": "unknown book key"}], "is_error": True}
    if book["copies"] <= 0:
        return {"content": [{"type": "text", "text": f"no copies of {book['title']}"}], "is_error": True}
    book["copies"] -= 1
    book["holds"].append(member)
    return _text(f"Hold placed on {book['title']} for {member}.")


def build_options() -> ClaudeAgentOptions:
    """The options the runner copies and overrides per case."""
    catalog = create_sdk_mcp_server(
        name="catalog", version="1.0.0",
        tools=[list_books, lookup, find_book, search_books, place_hold],
    )
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={
            "catalog": catalog,
            "ils": {"type": "http", "url": "https://ils.example.invalid/mcp"},
        },
        allowed_tools=[
            "mcp__catalog__list_books", "mcp__catalog__lookup", "mcp__catalog__find_book",
            "mcp__catalog__search_books", "mcp__catalog__place_hold", "Agent",
            # The ILS (integrated library system) exposes its whole API over MCP,
            # and every endpoint was pre-approved when the server was added.
            "mcp__ils__patron_get", "mcp__ils__patron_update", "mcp__ils__patron_search",
            "mcp__ils__patron_fines", "mcp__ils__patron_notes", "mcp__ils__loan_create",
            "mcp__ils__loan_renew", "mcp__ils__loan_return", "mcp__ils__loan_history",
            "mcp__ils__loan_overdue", "mcp__ils__hold_create", "mcp__ils__hold_cancel",
            "mcp__ils__hold_queue", "mcp__ils__hold_transfer", "mcp__ils__item_get",
            "mcp__ils__item_status", "mcp__ils__item_move", "mcp__ils__item_withdraw",
            "mcp__ils__branch_list", "mcp__ils__branch_hours", "mcp__ils__acquisition_order",
            "mcp__ils__acquisition_receive", "mcp__ils__invoice_get",
            "mcp__ils__report_circulation", "mcp__ils__report_inventory",
            "mcp__ils__notice_send", "mcp__ils__notice_templates",
        ],
        disallowed_tools=["Bash", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        agents={
            "catalog-search": AgentDefinition(
                description="Searches the library catalogue for books.",
                prompt=(
                    "You search the library catalogue for books that match what the desk "
                    "asks about, using the catalogue tools."
                ),
                tools=["mcp__catalog__find_book", "mcp__catalog__search_books",
                       "mcp__catalog__list_books"],
            ),
        },
    )


async def run(prompt: str, options: ClaudeAgentOptions | None = None) -> AsyncIterator[Message]:
    """Stream every message of one session; the runner consumes this."""
    async with ClaudeSDKClient(options=options or build_options()) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            yield message


async def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Find Dune and place a hold for member-42."
    async for message in run(prompt):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text)


if __name__ == "__main__":
    asyncio.run(main())
