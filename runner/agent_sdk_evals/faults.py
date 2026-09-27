"""Fault injection through hooks, and the capture hook the trace depends on.

Two measured constraints shape this module.

* **`HookMatcher` has no `probability` field** — only `matcher`, `hooks` and
  `timeout`. Per-tool probability therefore lives *inside* the callback, driven
  by a per-run seeded RNG so a flaky-looking failure can be reproduced exactly.
* **Matchers on the same event fire concurrently**, not in sequence, so no fault
  may depend on another fault having run first.

The capture hook is here too, because it is the same mechanism: a `PreToolUse`
hook that returns *allow* sees every tool call, whereas `can_use_tool` fires only
when the CLI's rules evaluate to "ask" — which, under `allowed_tools` or
`dontAsk`, is never. It is also the only way a `hook_event` grader gets any
evidence at all: `include_hook_events=True` on its own emits nothing.

A faults file:

    {"seed": 7,
     "faults": [{"id": "deny-writes", "event": "PreToolUse", "tool": "Write",
                 "action": "deny", "probability": 1.0, "reason": "disk full"},
                {"id": "slow-lookup", "event": "PreToolUse", "tool": "mcp__library__.*",
                 "action": "latency", "latency_ms": 1500},
                {"id": "garbled", "event": "PostToolUse", "tool": "Read",
                 "action": "error_output", "updated_tool_output": "<unreadable>"}]}

`action` is one of `deny`, `updated_input`, `error_output`, `latency`, `allow`.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import EvalError, PYTHON_HOOK_EVENTS

ACTIONS = ("deny", "updated_input", "error_output", "latency", "allow")

#: Events the capture hook installs itself on. `Stop` and `SubagentStop` have no
#: `hookSpecificOutput` type at all, so their callbacks return only the common
#: fields; `PermissionRequest` is left out because answering it changes the run.
CAPTURE_EVENTS = (
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit",
    "Stop", "SubagentStop", "SubagentStart", "PreCompact", "Notification",
)


@dataclass
class Fault:
    id: str
    event: str = "PreToolUse"
    tool: str = ".*"
    action: str = "deny"
    probability: float = 1.0
    reason: str = "injected by the eval runner"
    updated_input: dict[str, Any] | None = None
    updated_tool_output: Any = None
    latency_ms: int = 0

    def matches_tool(self, name: str) -> bool:
        try:
            return re.fullmatch(self.tool, name or "") is not None
        except re.error:
            return self.tool == name


@dataclass
class FaultPlan:
    seed: int = 0
    faults: list[Fault] = field(default_factory=list)

    def for_event(self, event: str) -> list[Fault]:
        return [f for f in self.faults if f.event == event]


def load_plan(data: dict[str, Any], *, run: int = 1) -> FaultPlan:
    """Parse a faults file. The run index is folded into the seed so run 2 of a
    case is a different but still reproducible draw."""
    faults: list[Fault] = []
    for index, raw in enumerate(data.get("faults") or []):
        if not isinstance(raw, dict):
            raise EvalError("each entry of `faults` must be a mapping", code="SIM002")
        event = str(raw.get("event") or "PreToolUse")
        if event not in PYTHON_HOOK_EVENTS:
            raise EvalError(
                f"fault event {event!r} is not one of the Python SDK's hook events "
                f"({', '.join(PYTHON_HOOK_EVENTS)})",
                code="HOK020",
            )
        action = str(raw.get("action") or "deny")
        if action not in ACTIONS:
            raise EvalError(f"fault action {action!r} is not one of {', '.join(ACTIONS)}", code="SIM002")
        probability = float(raw.get("probability", 1.0))
        if not 0.0 <= probability <= 1.0:
            raise EvalError(f"fault probability {probability} is outside [0, 1]", code="SIM002")
        faults.append(Fault(
            id=str(raw.get("id") or f"fault-{index + 1}"),
            event=event, tool=str(raw.get("tool") or ".*"), action=action,
            probability=probability, reason=str(raw.get("reason") or "injected by the eval runner"),
            updated_input=raw.get("updated_input"),
            updated_tool_output=raw.get("updated_tool_output"),
            latency_ms=int(raw.get("latency_ms") or 0),
        ))
    return FaultPlan(seed=int(data.get("seed", 0)) + run, faults=faults)


def read_plan_file(path: Path, *, run: int = 1) -> FaultPlan:
    import json

    try:
        return load_plan(json.loads(Path(path).read_text(encoding="utf-8")), run=run)
    except (OSError, ValueError) as exc:
        raise EvalError(f"{path}: {exc}", code="SIM002") from exc


def _tool_name(input_data: dict[str, Any]) -> str:
    return str(input_data.get("tool_name") or input_data.get("toolName") or "")


def build_hooks(capture: Any, plan: FaultPlan | None, sdk: Any) -> dict[str, list[Any]]:
    """`{event: [HookMatcher]}` combining the capture hook and the fault hooks."""
    rng = random.Random(plan.seed if plan else 0)
    hooks: dict[str, list[Any]] = {}

    def _make_callback(event: str):
        faults = plan.for_event(event) if plan else []

        async def callback(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
            data = input_data if isinstance(input_data, dict) else {}
            tool = _tool_name(data)
            capture.hook(event, "hook_started", matcher=None, tool=tool or None,
                         decision=None, tool_use_id=tool_use_id)
            for fault in faults:
                if not fault.matches_tool(tool):
                    continue
                if fault.probability < 1.0 and rng.random() >= fault.probability:
                    continue
                response = await _apply(fault, event)
                capture.hook(event, "hook_response", matcher=fault.tool, tool=tool or None,
                             decision=_decision_of(response, event), fault_id=fault.id)
                if response:
                    return response
            capture.hook(event, "hook_response", matcher=None, tool=tool or None,
                         decision="allow" if event == "PreToolUse" else None)
            if event == "PreToolUse":
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                               "permissionDecision": "allow"}}
            return {}

        return callback

    events = set(CAPTURE_EVENTS) | ({f.event for f in plan.faults} if plan else set())
    for event in sorted(events):
        hooks[event] = [sdk.HookMatcher(matcher=None, hooks=[_make_callback(event)])]
        capture.hook_events_installed.add(event)
    return hooks


async def _apply(fault: Fault, event: str) -> dict[str, Any]:
    if fault.latency_ms:
        await asyncio.sleep(fault.latency_ms / 1000.0)
    if fault.action == "latency":
        return {}
    if fault.action == "allow":
        return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "allow"}} \
            if event == "PreToolUse" else {}
    if fault.action == "deny":
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": fault.reason,
        }}
    if fault.action == "updated_input":
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": fault.updated_input or {},
        }}
    if fault.action == "error_output":
        # `updatedToolOutput` must match the tool's own output schema or the CLI
        # rejects it and keeps the original — a mismatch is silent, so a case
        # asserting on injected output should also assert the agent noticed it.
        return {"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": fault.updated_tool_output,
            "additionalContext": fault.reason,
        }}
    return {}


def _decision_of(response: dict[str, Any], event: str) -> str | None:
    specific = (response or {}).get("hookSpecificOutput") or {}
    return specific.get("permissionDecision") or (("updated_output" if "updatedToolOutput" in specific else None))
