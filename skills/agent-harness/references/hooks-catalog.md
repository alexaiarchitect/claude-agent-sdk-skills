# Hooks: all ten Python events, and what each one may return

The Python SDK's `HookEvent` literal has exactly **ten** values. The TypeScript
SDK has about thirty. A `hooks={"SessionStart": ...}` key in Python is not an
error — it is simply never called (`HOK020`).

| Event | When it fires | Distinctive input fields | `hookSpecificOutput` |
|---|---|---|---|
| `PreToolUse` | a tool call is requested, before it runs | `tool_name`, `tool_input`, `agent_id`/`agent_type` inside a subagent | `permissionDecision` (`allow`/`deny`/`ask`/`defer`), `permissionDecisionReason`, `updatedInput`, `additionalContext` |
| `PostToolUse` | the tool returned | `tool_name`, `tool_input`, the result | `additionalContext`, `updatedToolOutput` (any tool), `updatedMCPToolOutput` (**MCP tools only — not deprecated**; prefer `updatedToolOutput`, which works for all tools) |
| `PostToolUseFailure` | the tool raised or errored | as above plus the failure | `additionalContext` |
| `UserPromptSubmit` | a user turn is submitted — **and a turn Claude Code starts on its own**: a scheduled task or `/loop` iteration firing, a background subagent reporting back to its parent, a cross-session message arriving in the main conversation | the prompt | `additionalContext` |
| `Notification` | the agent emits a status message | `message` | `additionalContext` |
| `SubagentStart` | a subagent begins | `agent_id`, `agent_type` (required here) | `additionalContext` |
| `SubagentStop` | a subagent finishes | `agent_id`, `agent_type`, `stop_hook_active` | `additionalContext` (typed from 0.2.166) |
| `Stop` | the agent is about to stop | `stop_hook_active` | `additionalContext` (typed from 0.2.166) |
| `PreCompact` | compaction is about to run | — | **none** |
| `PermissionRequest` | a call needs a permission decision | `tool_name`, `tool_input` | `decision` (a dict) |

`PreCompact` is the only Python event with no `hookSpecificOutput` **type at all**. `Stop` and
`SubagentStop` gained one in 0.2.166 (`hookEventName` plus `additionalContext`; the dict shape
works on older SDKs too). **Blocking a stop is still a common field**: `decision: "block"` with
`reason` sends the agent back to work; `continue_: False` with `stopReason` ends the turn. A
check that demands `hookSpecificOutput` on `PreCompact`, or rejects it on `Stop`, is wrong.

`updatedToolOutput` must match the tool's own output shape, or the original is kept.

`permissionDecision: "defer"` is not a quieter deny; it "requires
non-interactive mode with the `-p` flag" and a single tool call. It ends the turn
with **`stop_reason: "tool_deferred"`** and `deferred_tool_use` populated. If the
tool is gone on resume, the first result has `stop_reason:
"tool_deferred_unavailable"`, `is_error: true`, `subtype: "success"`, and the
hook does not fire. Branch on `stop_reason` before `is_error`.

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
- **`return {}` means allow, unchanged.** Returning nothing (`None`) is a
  *failure*, not an allow (see `on_failure` below).
- **The common top-level fields are accepted on every event**: `continue_`,
  `stopReason`, `decision`, `reason`, `systemMessage`, `suppressOutput`;
  `{"continue_": False, "stopReason": "..."}` halts a turn on any event.
- **Return `{"async_": True, "asyncTimeout": 30000}`** to let the agent proceed
  without waiting (trailing underscore: the SDK converts `async_`/`continue_` on
  the wire). An async output cannot block, modify or inject: logging only.

## Registering them

```python
options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[gate, audit])]},
    include_hook_events=True,
)
```

`HookMatcher` is a dataclass with four fields: `matcher: str | None`, `hooks:
list[HookCallback]`, `timeout: float | None` and, from **0.2.177**, `on_failure:
Literal["continue", "block"] | None` (next section; below 0.2.177 passing it is a `TypeError`).
**There is no `probability` field**: randomness goes inside the callback, with a seeded RNG.

The matcher is compared against the tool name for tool events and the notification type for
`Notification` (`permission_prompt`, `idle_prompt`, …, `plugin_notification` when a mod calls
`$.ui.notify`); it is an exact string or a regular expression, so an invalid pattern is a real
error (`HOK003`). Omitting it fires on every occurrence. **Matchers on one event are dispatched
concurrently**: a callback must not assume another has already run.

## Concurrency, precedence and timeouts

- When several hooks or rules apply: **deny beats defer beats ask beats
  allow.** One deny blocks the operation regardless of the others.
- A `PreToolUse` hook that returns `allow` does **not** skip the deny and ask
  rules that follow it in the evaluation order. It also cannot approve an `rm`
  or `rmdir` targeting a critical path, and it does not skip the prompt for a
  read from a **network path**, which has its own check.
- Default timeout: **600 seconds** for most events, **30** for
  `UserPromptSubmit`. Set `timeout=` on the `HookMatcher` to change it.
- On `PreToolUse` an SDK callback that times out **blocks the tool call**: the
  tool result tells Claude the hook did not respond in time and the turn
  continues (before 2.1.210 it was reported as a user rejection, which left
  unattended sessions waiting). On `PostToolUse` the result is kept; on
  `Stop`/`SubagentStop` a timeout counts as no decision. With
  `on_failure="block"` a timeout also blocks `PreCompact`, `Elicitation` and
  `WorktreeCreate`.

## When a callback fails: `on_failure` (SDK 0.2.177+, CLI 2.1.317+)

A callback **fails** when it raises, returns `None` (a path with no `return`), or returns a
value the CLI rejects. By default (unset or `"continue"`) that is no decision: the action goes
ahead and the app gets a `SystemMessage` (`subtype="informational"`, `data["tag"] ==
"hook_callback_failed"`, "…Its answer was treated as empty."). So **a crashing `PreToolUse`
guard fails open** (measured on 2.1.318: the guarded `ls` ran).

`HookMatcher(matcher="Bash", hooks=[guard], on_failure="block")` blocks the action instead.
Measured on 0.2.178 / 2.1.318, the same informational message arrives, ending "onFailure is
"block", so this failure counts as a block." (the docs describe it only for the default path),
then an `is_error` tool result `PreToolUse:Bash hook error: [callback]: failed; blocking
because onFailure is "block"` without the guard's error text; the call lands in
`permission_denials`, Claude may retry it, and the result is still `subtype: "success"`.

- **`return {}` when the callback has no opinion**; with `"block"` a path with
  no `return` blocks. A guard that catches its own error and returns `{}` is not
  failing, so let the error propagate from a guard.
- `Stop`, `SubagentStop`, `TaskCompleted` and `TeammateIdle` ignore it; a
  `PermissionRequest` block counts only if it lands before `can_use_tool`
  answers; on `PostToolUse` the tool already ran, so Claude gets the failure as
  feedback.
- With `"block"` the session fails at startup with `CLIConnectionError` and no
  prompt sent: `does not honor` (CLI older than 2.1.317: update it) or `did not
  register your hooks` (an already-running session: start a new one). The SDK
  does not validate the value; the CLI reads an unknown one as `"block"`.

Set `"block"` on guards (callbacks that deny, ask or gate), not on observers.
`HOK011` flags a `PreToolUse`/`PermissionRequest` guard without it (silent below
a 0.2.177 pin); `gen_hook.py --purpose deny` emits it on those two events.

## `PreToolUse` `"ask"` in auto mode, and `SubagentHandback`

In `auto` mode a hook's `"ask"` normally goes to the permission prompt. Calls
Claude Code's own checks flag too (protected paths, commands asking to run
outside the sandbox) can be **denied by the classifier before any prompt**, and
**`SubagentHandback`** (delivers a subagent's report) gets no prompt and runs
even if the classifier objects. To stop a handback return `"deny"`: Claude Code
tells the subagent, up to three times, that its report was not delivered, then
the subagent ends and the waiting conversation gets a note.

## Command and `http` hooks: three outcomes, not two

A hook in a settings file or a plugin manifest is a process or a request, so it
reports through its exit code and stdout:

| Outcome | How | Effect |
|---|---|---|
| Success | exit **0** | stdout is read for field-setting JSON; the action proceeds |
| Blocking error | exit **2** | the action is blocked and stderr goes back to the model |
| Non-blocking error | any other exit code, or failing to start or to parse | the hook is ignored and the action proceeds — it **fails open** unless `onFailure: "block"` |

Stdout parses as JSON only when the **entire** output is one JSON object (from
**2.1.295** it may be pretty-printed); JSON-per-line output is plain text.

`onFailure: "block"` (**2.1.295+**) on a `command` or `http` hook makes a
failure (cannot start, exit other than 0 or 2, HTTP error, timeout, unparseable
output) fail the action the way exit 2 would. It has **no effect** on `Stop`,
`SubagentStop`, `TaskCompleted`, `TeammateIdle` or background
(`async`/`asyncRewake`) command hooks. SDK callbacks use the matcher's
`on_failure` (above).

## Released in 0.2.166 (gate as "0.2.166+")

The pinned 0.2.178 (bundled CLI 2.1.318) has all of this; code for 0.2.140–0.2.165 reads these
fields with `.get()`. Hook inputs gained `prompt_id` (the OTel `prompt.id`) and `effort` (a
`HookEffort`, `{level: str}`; `$CLAUDE_EFFORT` in command hooks), `duration_ms` on
`PostToolUse`/`PostToolUseFailure`, and `last_assistant_message`, `background_tasks`,
`session_crons` on `Stop`/`SubagentStop`. **21 `*HookSpecificOutput` types are exported, 12 of
them for events still not registrable from Python** (`SessionStart`, `PermissionDenied`,
`Elicitation`, `WorktreeCreate`, …), so `HOK020` still fires on those: the ten `HookEvent`
literals are unchanged. From 0.2.169 `SessionStart` and `Setup` hook events are emitted
regardless of `include_hook_events`.

## Claude Code changes that reach hook authors (2.1.299–2.1.318)

- **2.1.299–2.1.310**: `updatedInput` is validated like Claude's own input;
  `UserPromptSubmit` sees the typed `/skill …` line; failing shell-form guards
  on Windows and PowerShell fail closed (set `"onFailure": "block"`).
- **Prompt and agent hooks run at most 24 at a time per session, sub-agents
  included, plus at most 12 that have waited longer than their event's timeout;
  a `timeout` under 1 second counts as 1 second** (changelog 2.1.312; from
  2.1.302 the cap was 12 per event); the hooks page still says "If more than 12
  of them are prompt or agent hooks, 12 of those run at once" per event.
- **`SubagentStop` fires once per subagent (2.1.311)**. **Skill hooks are capped
  per source (2.1.304+)**: 1,024 hooks and 16,384 matcher characters per session.
- **A `PreCompact` hook's output is cut at 10,000 characters (2.1.314)**; very
  large output used to make compaction fail or repeat.
- **Hooks matching `Bash` also run on the Monitor tool's shell commands
  (2.1.314)**: they can block or ask, not approve or rewrite them; an `if`
  condition such as `Monitor(tail *)` matches them as `Bash(tail *)` matches Bash's.
  Changelog facts; the hooks page read 2026-11-04 doesn't carry the Monitor rule.
- **`updatedInput` in auto mode (docs 2026-11-04)**: when a `PreToolUse` hook
  returns `updatedInput` with no `permissionDecision`, Claude Code can deny the
  changed call (`a hook changed this call's input after auto mode reviewed
  it`), because the server reviewed Claude's input, not the hook's; if Claude
  repeats the call, the hook's `updatedInput` is dropped. A `command` hook in
  settings or a plugin's hooks file may still change Bash, PowerShell, Monitor,
  Edit, Write and NotebookEdit calls.
- **`@` mentions bypass `PreToolUse`** (no tool call); a `Read` deny rule still
  blocks the path, and `CLAUDE_CODE_DISABLE_FILE_MENTIONS=1` (2.1.299+) makes
  Claude read it with its tools so the hooks run.

## The one thing hooks are uniquely good for

`can_use_tool` runs only when the evaluation flow resolves to a prompt. A call that
`allowed_tools`, a `permissions.allow` setting or the mode (`acceptEdits`, `bypassPermissions`)
approves skips it, while `PreToolUse` sees rule- and mode-approved calls too: "To check those
calls, use a `PreToolUse` hook, which runs for them too" (docs 2026-11-05). So **a guard that
must cover them belongs in a `PreToolUse` hook**, as this plugin's runner does; a hook deny
applies even in `bypassPermissions` (the SDK emits a `CanUseToolShadowedWarning` when a bare
allow entry or that mode shadows your callback).

Measured: `include_hook_events=True` alone emits no `HookEventMessage`.

## Hooks in `.claude/settings.json`

Command hooks in a settings file load only when `setting_sources` includes `project` (or
`user`/`local`). An eval with `setting_sources=[]` will not run them, usually correctly;
`HOK030` reports the situation rather than judging it. Frontmatter hooks in a **project
subagent** file run only after the workspace trust dialog was accepted for the folder the file
came from, and "a `-p` session doesn't count as accepting it" — do not rely on them in a
headless run.

**Bare mode runs no hooks.** `claude -p --bare` skips hook discovery, and "Hooks still don't
run in bare mode when you pass them with `--settings`, or in the `hooks/hooks.json` or `hooks`
manifest key of a plugin you load with a flag" (`headless`): don't use bare mode for a run that
needs a hook.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/hooks> (hooks, matchers,
callback inputs and outputs, asynchronous output, hook timeout, "Block the
action when a callback fails"), <https://code.claude.com/docs/en/hooks> (matcher
patterns, JSON output, per-event sections, `updatedInput` in auto mode),
<https://code.claude.com/docs/en/agent-sdk/permissions#how-permissions-are-evaluated>,
<https://code.claude.com/docs/en/headless> (bare mode),
<https://code.claude.com/docs/en/hooks#hooks-that-start-a-background-process>,
<https://code.claude.com/docs/en/hooks#failed-hooks-on-windows-without-git-bash>,
<https://code.claude.com/docs/en/hooks#pretooluse> (`@` mentions, `"defer"`, `ask`
in auto mode, `SubagentHandback`, `effort`, frontmatter-hook trust), <https://code.claude.com/docs/en/env-vars>,
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.299–2.1.311,
2.1.312 hook cap, 2.1.314 `PreCompact` cut and Monitor-tool hooks, 2.1.317 `onFailure`
for SDK callbacks), the SDK `CHANGELOG.md` (0.2.169; 0.2.177 `on_failure`);
`claude-agent-sdk` 0.2.178 `types.py:284-297` (`HookEvent`, ten literals), `:299-509`
(hook input types), `:511-725` (`hookSpecificOutput` per event), `:728-815`
(`HookJSONOutput`), `:818` (`HookContext`), `:828` (`HookCallback`), `:840`
(`HookMatcher`), `:864` (`on_failure`), `:2544-2555` (concurrent dispatch),
`:2567-2573` (`include_hook_events`), `:2201-2290` (`CanUseToolShadowedWarning`),
`:614` (`StopHookSpecificOutput`), `:625` (`SubagentStopHookSpecificOutput`), `:299`
(`HookEffort`). Measured by this plugin: "emits nothing without a registered hook"
(2026-09-30), both `on_failure` paths on 0.2.178 / 2.1.318 (2026-11-04). 0.2.178's
`types.py` adds only `on_failure` (13 lines) to what 0.2.174 had.
Re-read 2026-11-05 against claude-agent-sdk 0.2.178 / Claude Code 2.1.318 docs.
