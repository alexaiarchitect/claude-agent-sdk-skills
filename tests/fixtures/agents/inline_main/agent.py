"""Library reservations agent whose options exist only inside `main()`.

What this demonstrates: AGT003. The options are correct — a pinned model from
the environment, an allow list, a deny list, turn and budget ceilings — but
they are constructed inside `main()`, so nothing outside this process can
obtain them. An eval runner cannot import a builder, apply a per-case
override and run the same agent; every experiment would be a source edit.

Also demonstrates OPT020: the project ships a `CLAUDE.md`, and
`setting_sources` is never passed, so the developer's own user, project and
local settings load into every run.

Do not fix this file. The inline construction is the defect under test.
"""

from __future__ import annotations

import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, query

BRANCHES = {"riverside": "09:00-18:00", "hilltop": "10:00-16:00"}

DESK_PROMPT = """You are the reservations desk of a small library.

Rules:
1. Quote opening hours only for a branch in the list you were given.
2. Never promise a reservation you have not confirmed.
3. Answer in one short paragraph.
"""


async def main() -> None:
    options = ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=DESK_PROMPT + f"\nBranches: {sorted(BRANCHES)}",
        allowed_tools=["Read"],
        disallowed_tools=["Bash", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        max_turns=4,
        max_budget_usd=0.25,
    )
    async for message in query(prompt="When does the riverside branch close?", options=options):
        print(message)


if __name__ == "__main__":
    asyncio.run(main())
