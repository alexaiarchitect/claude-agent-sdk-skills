#!/usr/bin/env python3
"""Write a correct hook callback and the `HookMatcher` line that registers it.

Hooks are the part of the SDK it is easiest to write and get silently wrong.
Three facts decide whether one works, and none of them raises when broken:

* the callback must be `async def cb(input_data, tool_use_id, context)`;
* what it returns must carry `hookSpecificOutput` with a `hookEventName` equal
  to the event it is registered on — except to block a stop (`Stop`,
  `SubagentStop`), which uses the top-level `decision`/`reason`, and on
  `PreCompact`, the one event with no `hookSpecificOutput` type at all;
  `Stop` and `SubagentStop` take `additionalContext` there (typed from
  claude-agent-sdk 0.2.166, `types.py:616`, `:627`);
* `HookMatcher` has no `probability` field, so anything probabilistic (fault
  injection, sampling) belongs *inside* the callback.

So this generates the shape rather than describing it. Four purposes:

  audit     observe and record; returns {} so nothing is changed
  deny      refuse a call, with a reason the model can act on
  inject    add context the model reads on its next turn
  latency   delay a call, to see what the agent does when a tool is slow

    gen_hook.py --event PreToolUse --purpose deny [--tool Bash]
                [--probability 0.25] [--out path] [--dry-run] [--force] [--json]

A guard fails open by default: a deny callback that raises, returns `None` or
returns a value the CLI rejects counts as "no decision", and the call it was
written to stop goes ahead. So a `deny` hook on PreToolUse or PermissionRequest
is registered with `HookMatcher(..., on_failure="block")` (claude-agent-sdk
0.2.177+, Claude Code 2.1.317+; an older SDK rejects the keyword), which turns
any of those failures into a refusal; the generated callback returns `{}` on
every path where it has no opinion. Observers (audit, inject, latency, every
PostToolUse hook) and Stop/SubagentStop blockers keep the default: an observer
that crashes should not stop the agent, and Stop, SubagentStop, TaskCompleted
and TeammateIdle ignore `on_failure` anyway. `--json` reports the value.

Exit codes: 0 written (or planned, under --dry-run), 1 nothing to write,
2 the event and purpose do not go together.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import (  # noqa: E402
    HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT, PYTHON_HOOK_EVENTS,
)
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan  # noqa: E402

#: Events whose `hookSpecificOutput` accepts `additionalContext`.
CONTEXT_EVENTS = (
    "PostToolUse", "PostToolUseFailure", "UserPromptSubmit", "Notification",
    "SubagentStart", "Stop", "SubagentStop",
)
#: Events that can decide a tool call.
DECIDING_EVENTS = ("PreToolUse", "PermissionRequest")
#: Events whose "deny" is a top-level `decision: "block"` that refuses the stop.
STOP_EVENTS = ("Stop", "SubagentStop")

PURPOSES = ("audit", "deny", "inject", "latency")

HEADER = '''"""{title}

Registered with:

    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    options = ClaudeAgentOptions(
        hooks={{"{event}": {registration}}},
        include_hook_events=True,   # so the hook shows up in the message stream
    )
{on_failure_note}
Matchers on one event are dispatched concurrently by the CLI, so this callback
must not depend on another one having run first. The default timeout is 600
seconds for most events (30 for UserPromptSubmit); set `timeout=` on the
HookMatcher to change it.
"""

from __future__ import annotations
{imports}

'''

AUDIT_BODY = '''
TRAIL: list[dict[str, Any]] = []


async def {func}(input_data, tool_use_id, context):
    """Record one {event} and change nothing.

    `input_data` always carries `session_id`, `cwd` and `hook_event_name`; a
    tool event adds `tool_name` and `tool_input`. Returning an empty dict means
    "allow, unchanged" — the one return value that is always safe.
    """
    TRAIL.append({{
        "event": input_data.get("hook_event_name"),
        "tool": input_data.get("tool_name"),
        "tool_use_id": tool_use_id,
        "session": input_data.get("session_id"),
        "at": time.time(),
    }})
    return {{}}
'''

DENY_BODY = '''
async def {func}(input_data, tool_use_id, context):
    """Refuse a {tool} call that does not meet the rule.

    The reason is the only thing the model reads. Without it the agent is told
    "no" and has nothing to correct from, which usually shows up as the same
    call being retried until the turn limit. Let an error in the rule raise:
    with `on_failure="block"` that refuses the call, whereas catching it and
    returning `{{}}` would let the call through.
    """
    arguments = input_data.get("tool_input") or {{}}
    if not _is_allowed(arguments):
        return {{
{deny_output}
        }}
    return {{}}   # no opinion: with on_failure="block" a path with no return blocks


def _is_allowed(arguments: dict[str, Any]) -> bool:
    """Replace with the real rule. Deny beats defer beats ask beats allow, and a
    hook that allows does not skip the deny and ask rules below it — nor the
    separate check on a read from a network path, which no allow can bypass.

    "defer" is not a quieter deny: it ends the turn, and the `ResultMessage`
    then carries `stop_reason: "tool_deferred"`, so assert on that rather than
    on the text. A `command` or `http` hook written in settings instead of here
    has the same switch, `onFailure: "block"` (Claude Code 2.1.295+).
    """
    return "/etc/" not in str(arguments.get("file_path", ""))
'''

INJECT_BODY = '''
async def {func}(input_data, tool_use_id, context):
    """Add context the model reads on its next turn.

    `additionalContext` is appended, not substituted: it does not replace the
    tool result or the prompt. Keep it short — it is charged as input tokens on
    every following turn of the session.
    """
    return {{
        "hookSpecificOutput": {{
            "hookEventName": "{event}",
            "additionalContext": (
                "House rule: cite the record id you relied on in every answer."
            ),
        }}
    }}
'''

LATENCY_BODY = '''
#: Seeded so a run is reproducible: the same seed injects the same delays.
_RNG = random.Random({seed})
#: `HookMatcher` has no probability field, so the draw happens here.
PROBABILITY = {probability}
DELAY_SECONDS = 2.0


async def {func}(input_data, tool_use_id, context):
    """Delay a {tool} call, some of the time, to see what the agent does.

    This is fault injection, not a feature: use it in an eval to find out
    whether the agent waits, retries, or gives up. The delay counts against the
    hook's own timeout, so keep it well under it.
    """
    if _RNG.random() < PROBABILITY:
        await asyncio.sleep(DELAY_SECONDS)
    return {{}}
'''

BLOCKING_BODY = '''
async def {func}(input_data, tool_use_id, context):
    """Decide whether the agent may stop.

    Blocking uses the common fields, not `hookSpecificOutput`:
    `{{"decision": "block", "reason": ...}}` sends the agent back to work with
    that reason; an empty dict lets it stop. (`hookSpecificOutput` on {event}
    carries `additionalContext` only, where the event has the type at all.)
    """
    if not _work_is_finished(input_data):
        return {{
            "decision": "block",
            "reason": "The day book has no entry for this reservation yet.",
        }}
    return {{}}


def _work_is_finished(input_data: dict[str, Any]) -> bool:
    """Replace with the real check."""
    return True
'''


PRE_TOOL_USE_DENY = '''            "hookSpecificOutput": {{
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "refused by policy: {tool} may not touch that path. "
                    "Use the project directory instead."
                ),
            }}'''

#: PermissionRequest decides with `decision.behavior`, not `permissionDecision`.
PERMISSION_REQUEST_DENY = '''            "hookSpecificOutput": {{
                "hookEventName": "PermissionRequest",
                "decision": {{
                    "behavior": "deny",
                    "message": (
                        "refused by policy: {tool} may not touch that path. "
                        "Use the project directory instead."
                    ),
                }},
            }}'''

ON_FAILURE_NOTE = '''
`on_failure="block"` makes this guard fail closed: if the callback raises,
returns None or returns a value the CLI rejects, the call is refused instead of
going ahead. It needs claude-agent-sdk 0.2.177+ and Claude Code 2.1.317+ (an
older CLI makes connecting raise CLIConnectionError). On PermissionRequest a
block counts only if it lands before can_use_tool answers.
'''


def on_failure_for(event: str, purpose: str) -> str | None:
    """`"block"` for a guard (a deny hook that decides a tool call), else None."""
    return "block" if purpose == "deny" and event in DECIDING_EVENTS else None


def registration_line(event: str, purpose: str, matcher: str | None, func: str) -> str:
    """The `HookMatcher(...)` expression, with `on_failure` on a guard."""
    if on_failure_for(event, purpose) == "block":
        return f'HookMatcher(matcher={matcher!r}, hooks=[{func}], on_failure="block")'
    return f"HookMatcher(matcher={matcher!r}, hooks=[{func}])"


ON_FAILURE_COMMENT = "# a guard fails closed: a callback that crashes refuses the call"


def _registration_in_header(event: str, purpose: str, matcher: str | None, func: str) -> str:
    line = registration_line(event, purpose, matcher, func)
    if on_failure_for(event, purpose) != "block":
        return f"[{line}]"
    return f"[\n            {ON_FAILURE_COMMENT}\n            {line},\n        ]"


def build(event: str, purpose: str, tool: str | None, probability: float,
          seed: int) -> tuple[str, str, str]:
    """Return `(function_name, matcher, source)`."""
    func = f"{purpose}_{_snake(event)}"
    matcher = tool or None
    imports = ["", "from typing import Any"]
    if purpose == "audit":
        imports.insert(1, "import time")
        body = AUDIT_BODY
        title = f"{event} hook: record every event and change nothing."
    elif purpose == "deny":
        body = DENY_BODY
        title = f"{event} hook: refuse a call that breaks a rule, with a reason."
    elif purpose == "inject":
        body = INJECT_BODY
        title = f"{event} hook: add context to the model's next turn."
    else:
        imports = ["", "import asyncio", "import random"]
        body = LATENCY_BODY
        title = f"{event} hook: inject latency, some of the time."
    blocks_a_stop = event in STOP_EVENTS and purpose == "deny"
    if blocks_a_stop or (event in HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT
                         and purpose in ("deny", "inject")):
        body = BLOCKING_BODY
        imports = ["", "from typing import Any"]
        title = f"{event} hook: decide whether the agent may stop."
    guard = on_failure_for(event, purpose) == "block"
    tool_text = tool or "the matched tool"
    deny_output = (PERMISSION_REQUEST_DENY if event == "PermissionRequest"
                   else PRE_TOOL_USE_DENY).format(tool=tool_text)
    source = HEADER.format(
        title=title, event=event,
        registration=_registration_in_header(event, purpose, matcher, func),
        on_failure_note=ON_FAILURE_NOTE if guard else "",
        imports="\n".join(imports),
    ) + body.format(
        func=func, event=event, tool=tool_text,
        probability=probability, seed=seed, deny_output=deny_output,
    )
    return func, matcher or "(every occurrence)", source.rstrip() + "\n"


def _snake(event: str) -> str:
    out: list[str] = []
    for index, char in enumerate(event):
        if char.isupper() and index:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--event", required=True, help="one of the ten Python hook events")
    parser.add_argument("--purpose", required=True, choices=PURPOSES)
    parser.add_argument("--tool", help="matcher: a tool name, or a regular expression. "
                                      "Omit to fire on every occurrence of the event")
    parser.add_argument("--probability", type=float, default=0.25,
                        help="for --purpose latency: the chance of a delay (0-1)")
    parser.add_argument("--seed", type=int, default=1729,
                        help="RNG seed, so an injected fault is reproducible")
    parser.add_argument("--out", help="where to write (default: hooks/<event>_<purpose>.py)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the write plan and the snippet; write nothing")
    parser.add_argument("--force", action="store_true", help="replace an existing file")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args(argv)

    if args.event not in PYTHON_HOOK_EVENTS:
        print(f"error: {args.event} is not a hook event the Python SDK has. One of: "
              + ", ".join(PYTHON_HOOK_EVENTS)
              + ".\nSessionStart and SessionEnd are TypeScript-only; do that work before "
                "query() instead.", file=sys.stderr)
        return EXIT_USAGE
    if not 0.0 <= args.probability <= 1.0:
        print("error: --probability must be between 0 and 1", file=sys.stderr)
        return EXIT_USAGE
    blocking = STOP_EVENTS + HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT
    if args.purpose == "deny" and args.event not in DECIDING_EVENTS + blocking:
        print(f"error: {args.event} cannot deny a call. Only "
              + ", ".join(DECIDING_EVENTS)
              + " carry a permission decision; "
              + ", ".join(blocking)
              + " can block with a top-level decision.", file=sys.stderr)
        return EXIT_USAGE
    if args.purpose == "inject" and args.event not in CONTEXT_EVENTS + ("PreToolUse",) + HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT:
        print(f"error: {args.event} has no additionalContext field. One of: "
              + ", ".join(CONTEXT_EVENTS) + ", PreToolUse.", file=sys.stderr)
        return EXIT_USAGE

    func, matcher, source = build(args.event, args.purpose, args.tool,
                                  args.probability, args.seed)
    out = Path(args.out) if args.out else Path("hooks") / f"{_snake(args.event)}_{args.purpose}.py"

    plan = WritePlan()
    plan.add(out, source, force=args.force,
             reason=f"{args.purpose} hook for {args.event}, matcher {matcher}")

    payload = {
        "event": args.event, "purpose": args.purpose, "callback": func,
        "matcher": args.tool, "on_failure": on_failure_for(args.event, args.purpose),
        "registration": registration_line(args.event, args.purpose, args.tool, func),
        "out": str(out), "dry_run": args.dry_run,
        "plan": plan.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(plan.to_md())
        print()
        if args.dry_run:
            print("--- snippet (not written) ---")
            print(source)
    if args.dry_run:
        return EXIT_OK

    written = plan.apply()
    if not written:
        if not args.json:
            print("nothing written; pass --force to replace an existing file")
        return EXIT_FINDINGS
    if not args.json:
        for path in written:
            print(f"wrote {path}")
        registration = registration_line(args.event, args.purpose, args.tool, func)
        comment = (f"  {ON_FAILURE_COMMENT}"
                   if on_failure_for(args.event, args.purpose) else "")
        print(f"Register it: hooks={{\"{args.event}\": [{registration}]}}{comment}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
