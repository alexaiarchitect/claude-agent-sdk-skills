"""A convention-shaped agent with no evals directory yet."""

from __future__ import annotations

import os

from claude_agent_sdk import ClaudeAgentOptions


def build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt="You answer questions about library opening hours in one sentence.",
        allowed_tools=[],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        max_turns=2,
        max_budget_usd=0.10,
    )
