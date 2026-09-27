"""Library reservations agent whose hooks are wired four different wrong ways.

What this demonstrates, one defect per hook:

* HOK001 — `audit_tool_use` is a plain `def`. A hook callback must be
  `async def`; the SDK awaits it and a synchronous function raises.
* HOK002 — `gate_reservation` returns a dict of its own invention. It has no
  `hookSpecificOutput`, and `deny`/`message` are not among the common top-level
  fields the SDK reads, so nothing in it reaches the decision and the call goes
  ahead. (A return made only of common fields — `continue_`, `stopReason`,
  `decision`, `reason`, `systemMessage` — is well formed and is not flagged.)
* HOK010 — `refuse_second_copy` denies with the right shape but no
  `permissionDecisionReason`, so the model is told "no" with nothing to
  correct from.
* HOK020 — `SessionStart` is registered. The Python SDK's `HookEvent` literal
  has ten values and `SessionStart` is not one of them, so the key is ignored.
* HOK003 — the `PostToolUse` matcher `mcp__loans__(reserve` is not a valid
  regular expression.

Do not fix this file. Every hook here exists to be caught.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher

DESK_PROMPT = """You are the reservations desk of a small library.

Rules:
1. Never reserve a title for a member who already holds it.
2. Say which record you relied on.
"""

TRAIL: list[dict[str, Any]] = []


def audit_tool_use(input_data, tool_use_id, context):
    """Append every tool call to an in-memory trail. Not async: HOK001."""
    TRAIL.append({"tool": input_data.get("tool_name"), "id": tool_use_id})
    return {}


async def gate_reservation(input_data, tool_use_id, context):
    """Block a second copy. Invented return shape: HOK002."""
    arguments = input_data.get("tool_input") or {}
    if arguments.get("member_id") in TRAIL:
        return {"deny": True, "message": "member already holds this title"}
    return {}


async def refuse_second_copy(input_data, tool_use_id, context):
    """Right shape, no reason: HOK010."""
    arguments = input_data.get("tool_input") or {}
    if arguments.get("copies", 0) > 1:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
            }
        }
    return {}


async def note_session(input_data, tool_use_id, context):
    """Add context at session start — an event the Python SDK does not have."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"Desk opened at {os.getenv('OPENING_TIME', '09:00')}.",
        }
    }


async def record_result(input_data, tool_use_id, context):
    """Well-formed PostToolUse hook; only its matcher is broken (HOK003)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "Reservation recorded in the day book.",
        }
    }


def build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        system_prompt=DESK_PROMPT,
        allowed_tools=["Read"],
        disallowed_tools=["Bash", "Write", "Edit", "WebFetch", "WebSearch"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=6,
        max_budget_usd=0.30,
        include_hook_events=True,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Read", hooks=[audit_tool_use]),
                HookMatcher(matcher="mcp__loans__reserve", hooks=[gate_reservation]),
                HookMatcher(matcher="mcp__loans__.*", hooks=[refuse_second_copy]),
            ],
            "PostToolUse": [HookMatcher(matcher="mcp__loans__(reserve", hooks=[record_result])],
            "SessionStart": [HookMatcher(hooks=[note_session])],
        },
    )


async def run(prompt: str) -> None:
    async with ClaudeSDKClient(options=build_options()) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            print(message)


if __name__ == "__main__":
    asyncio.run(run("Reserve Dune for member-42."))
