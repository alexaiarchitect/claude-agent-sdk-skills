# Hooks: all ten Python events, and what each one may return

The Python SDK's `HookEvent` literal has exactly **ten** values. The TypeScript
SDK has about thirty. A `hooks={"SessionStart": ...}` key in Python is not an
error — it is simply never called (`HOK020`).

| Event | When it fires | Distinctive input fields | `hookSpecificOutput` |
|---|---|---|---|
| `PreToolUse` | a tool call is requested, before it runs | `tool_name`, `tool_input`, `agent_id`/`agent_type` inside a subagent | `permissionDecision` (`allow`/`deny`/`ask`/`defer`), `permissionDecisionReason`, `updatedInput`, `additionalContext` |
| `PostToolUse` | the tool returned | `tool_name`, `tool_input`, the result | `additionalContext`, `updatedToolOutput` (any tool), `updatedMCPToolOutput` (MCP only, deprecated) |
| `PostToolUseFailure` | the tool raised or errored | as above plus the failure | `additionalContext` |
| `UserPromptSubmit` | a user turn is submitted | the prompt | `additionalContext` |
| `Notification` | the agent emits a status message | `message` | `additionalContext` |
| `SubagentStart` | a subagent begins | `agent_id`, `agent_type` (required here) | `additionalContext` |
| `SubagentStop` | a subagent finishes | `agent_id`, `agent_type` | **none** |
| `Stop` | the agent is about to stop | — | **none** |
| `PreCompact` | compaction is about to run | — | **none** |
| `PermissionRequest` | a call needs a permission decision | `tool_name`, `tool_input` | `decision` (a dict) |

`Stop`, `SubagentStop` and `PreCompact` have no `hookSpecificOutput` **type at
all**. They use the common fields only: `decision: "block"` with `reason` sends
the agent back to work; `continue_: False` with `stopReason` ends the turn;
`systemMessage` shows the user a line. A generator or a check that demands
`hookSpecificOutput` on those three is wrong.

## The callback contract

```python
async def cb(input_data, tool_use_id, context) -> dict: ...
```

- **`async def`, always.** The SDK awaits it; a plain `def` raises when the
  event fires (`HOK001`).
- **Three parameters, always.** `input_data` (a TypedDict per event, sharing
  `session_id`, `cwd`, `hook_event_name`), `tool_use_id` (`str | None`, which
  correlates `PreToolUse` with `PostToolUse` for the same call), and `context`
  — in Python a `HookContext` with one key, `signal`, documented as "reserved
  for future abort signal support. Currently always None."
- **`return {}` means allow, unchanged.** It is the safest return there is.
- **The common top-level fields are accepted on every event**, with or without
  `hookSpecificOutput`: `continue_`, `stopReason`, `decision`, `reason`,
  `systemMessage`, `suppressOutput`. `{"continue_": False, "stopReason": "..."}`
  is how a hook halts a turn, and it is correct on `PostToolUse` as much as on
  `Stop`. A checker that demands `hookSpecificOutput` from every non-empty
  return is wrong about this.
- **Return `{"async_": True, "asyncTimeout": 30000}`** to let the agent proceed
  without waiting. Note the trailing underscore: Python cannot use `async` as a
  key name, and the SDK converts it on the wire (the same applies to
  `continue_`). An async output cannot block, modify or inject anything — the
  agent has already moved on — so it is for logging and metrics only.

## Registering them

```python
options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[gate, audit])]},
    include_hook_events=True,
)
```

`HookMatcher` is a dataclass with three fields: `matcher: str | None`,
`hooks: list[HookCallback]`, `timeout: float | None`. **There is no
`probability` field** — anything probabilistic goes inside the callback, with a
seeded RNG if a run has to be reproducible.

The matcher is compared against a different value per event: the tool name for
tool events, the notification type for `Notification`. It follows the same rules
as matchers in settings files (exact string or regular expression), so an
invalid pattern is a real error (`HOK003`). Omitting it fires on every
occurrence of the event, which is what an audit hook wants.

**Matchers on one event are dispatched concurrently**, not in sequence. A
callback must not assume another has already run.

## Concurrency, precedence and timeouts

- When several hooks or rules apply: **deny beats defer beats ask beats
  allow.** One deny blocks the operation regardless of the others.
- A `PreToolUse` hook that returns `allow` does **not** skip the deny and ask
  rules that follow it in the evaluation order. It also cannot approve an `rm`
  or `rmdir` targeting a critical path.
- Default timeout: **600 seconds** for most events, **30** for
  `UserPromptSubmit`. Set `timeout=` on the `HookMatcher` to change it.
- What a timeout does depends on the event. On `PreToolUse`, an Agent SDK
  callback that exceeds its timeout **blocks the tool call** and Claude gets an
  error result naming the timeout. On `PostToolUse` the result is kept and the
  turn continues. On `Stop`/`SubagentStop` the timed-out callback counts as no
  decision, and the agent stops as if it had allowed.

## The one thing hooks are uniquely good for

`can_use_tool` fires **only** when the CLI's rules evaluate to "ask". It is not
called for a tool already allowed by `allowed_tools`, by `acceptEdits` or
`bypassPermissions`, or by a `permissions.allow` setting — and the SDK emits a
`CanUseToolShadowedWarning` when you set both. So **to observe or gate every
tool call, use a `PreToolUse` hook.** That is also what this plugin's eval
runner captures trace events from.

Measured caveat: `include_hook_events=True` on its own emits nothing. A hook has
to be registered as well, or the message stream carries no `HookEventMessage`.

## Hooks in `.claude/settings.json`

Command hooks configured in a settings file are a different mechanism with the
same event names. They load only when `setting_sources` includes `project` (or
`user`/`local` for those tiers). An eval with `setting_sources=[]` will not run
them — usually correct, since a run that depends on the developer's settings
file is not reproducible. `HOK030` reports the situation rather than judging it.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/hooks>
(available hooks, matchers, callback inputs and outputs, asynchronous output,
hook timeout), <https://code.claude.com/docs/en/hooks> (matcher patterns,
JSON output, per-event sections),
<https://code.claude.com/docs/en/agent-sdk/permissions#how-permissions-are-evaluated>;
`claude-agent-sdk` 0.2.162 `types.py:284-297` (`HookEvent`, ten literals),
`:299-435` (hook input types), `:437-500` (`hookSpecificOutput` per event),
`:507-581` (`HookJSONOutput`), `:584` (`HookContext`), `:594`
(`HookCallback`), `:606` (`HookMatcher`), `:2176-2187` (concurrent dispatch),
`:2199` (`include_hook_events`), `:1835-1924`
(`CanUseToolShadowedWarning`). The "emits nothing without a registered hook"
observation was measured by this plugin on 2026-09-30.
