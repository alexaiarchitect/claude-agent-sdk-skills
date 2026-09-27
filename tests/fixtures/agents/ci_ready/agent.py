"""Library book reservations, the convention layout: `build_options()`."""

import os

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool


@tool("lookup_book", "Find a book by title", {"title": str})
async def lookup_book(args):
    return {"content": [{"type": "text", "text": f"available: {args['title']}"}]}


@tool("reserve_book", "Reserve a copy for a member", {"title": str, "member": str})
async def reserve_book(args):
    return {"content": [{"type": "text", "text": f"reserved {args['title']}"}]}


def build_options() -> ClaudeAgentOptions:
    library = create_sdk_mcp_server(name="library", version="1.0.0",
                                    tools=[lookup_book, reserve_book])
    return ClaudeAgentOptions(
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        mcp_servers={"library": library},
        allowed_tools=["mcp__library__lookup_book", "mcp__library__reserve_book"],
        disallowed_tools=["Bash", "Write"],
        setting_sources=[],
        strict_mcp_config=True,
        max_turns=6,
        max_budget_usd=0.5,
    )
