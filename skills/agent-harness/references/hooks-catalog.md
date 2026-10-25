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

`PreCompact` is the only Python event with no `hookSpecificOutput` **type at
all**. `Stop` and `SubagentStop` gained one in 0.2.166 (`hookEventName` plus
`additionalContext`; the dict shape works on older SDKs too). **Blocking a stop
is still a common field**: `decision: "block"` with `reason` sends the agent
back to work; `continue_: False` with `stopReason` ends the turn. A check that
demands `hookSpecificOutput` on `PreCompact`, or rejects it on `Stop`, is wrong.

`updatedToolOutput` has to match the tool's own output shape; a mismatch is
rejected and the original output is kept.

`permissionDecision: "defer"` is not a quieter deny, and it "requires
non-interactive mode with the `-p` flag" (an interactive session ignores it, as
does a turn with several tool calls). It ends the turn with **`stop_reason:
"tool_deferred"`** and `deferred_tool_use` populated — assert on those, not the
text. If the tool is gone on resume (its MCP server not connected), the first
result has `stop_reason: "tool_deferred_unavailable"`, `is_error: true`,
`subtype: "success"`, and the hook does not fire; a prompt sent with the resume
is answered without the tool's result. Branch on `stop_reason` before `is_error`.

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

`HookMatcher` is a dataclass with three fields: `matcher: str | None`,
`hooks: list[HookCallback]`, `timeout: float | None`. **There is no
`probability` field** — anything probabilistic goes inside the callback, with a
seeded RNG if a run has to be reproducible.

The matcher is compared against a different value per event: the tool name for
tool events, the notification type for `Notification` (`permission_prompt`,
`idle_prompt`, …, and `plugin_notification` when a mod calls `$.ui.notify`). It follows the same rules
as matchers in settings files (exact string or regular expression), so an
invalid pattern is a real error (`HOK003`). Omitting it fires on every
occurrence of the event, which is what an audit hook wants.

**Matchers on one event are dispatched concurrently**: a callback must not
assume another has already run.

## Concurrency, precedence and timeouts

- When several hooks or rules apply: **deny beats defer beats ask beats
  allow.** One deny blocks the operation regardless of the others.
- A `PreToolUse` hook that returns `allow` does **not** skip the deny and ask
  rules that follow it in the evaluation order. It also cannot approve an `rm`
  or `rmdir` targeting a critical path, and it does not skip the prompt for a
  read from a **network path**, which has its own check.
- Default timeout: **600 seconds** for most events, **30** for
  `UserPromptSubmit`. Set `timeout=` on the `HookMatcher` to change it.
- What a timeout does depends on the event. On `PreToolUse`, an Agent SDK
  callback that exceeds its timeout **blocks the tool call**: if every other
  hook returned nothing or `allow`, the tool result tells Claude the hook did not
  respond in time and the turn continues; another hook's deny still reaches
  Claude with its reason. Before 2.1.210 the timeout was reported as a user
  rejection, which left unattended sessions waiting for input. On `PostToolUse`
  the result is kept. On `Stop`/`SubagentStop` the timed-out callback counts as
  no decision, and the agent stops as if it had allowed.

## `PreToolUse` `"ask"` in auto mode, and `SubagentHandback`

In `auto` mode a hook's `"ask"` normally sends the call to the permission
prompt, and the classifier does not decide it. Two kinds of call take another
path: calls Claude Code's own checks flag too (writes to protected paths,
commands asking to run outside the sandbox) can be **denied by the classifier
before any prompt**; and **`SubagentHandback`** (the tool that delivers a
subagent's report) gets no prompt and runs even if the classifier objects. To
stop a handback, return `"deny"`: Claude Code tells the subagent, up to three
times, that its report was not delivered; if you keep denying, the subagent ends
without delivering it and the waiting conversation gets a note saying so.

## Command and `http` hooks: three outcomes, not two

A hook written in a settings file or a plugin manifest is a process or a request,
not a callback, so it reports through its exit code and its stdout. The contract
is three outcomes:

| Outcome | How | Effect |
|---|---|---|
| Success | exit **0** | stdout is read for field-setting JSON; the action proceeds |
| Blocking error | exit **2** | the action is blocked and stderr goes back to the model |
| Non-blocking error | any other exit code, or failing to start or to parse | the hook is ignored and the action proceeds — it **fails open** |

Stdout parses as JSON only when the **entire** output is one JSON object (from
**2.1.295** it may be pretty-printed); JSON-per-line output is plain text.

`onFailure` (**2.1.295+**) is the answer to the fail-open row: set it to
`"block"` on a `command` or `http` hook and a failure — cannot start, an exit
code other than 0 or 2, an HTTP error, a timeout, invalid or unparseable output
— fails the action the way exit 2 would (`PermissionRequest` is denied instead).
It defaults to `"continue"`, and it has **no effect at all** on `Stop`,
`SubagentStop`, `TaskCompleted`, `TeammateIdle` or background
(`async`/`asyncRewake`) command hooks, so do not promise it there.

## Released in 0.2.166 (gate as "0.2.166+")

The pinned 0.2.174 has all of this; code that must run on 0.2.140–0.2.165 reads
these fields with `.get()` and imports the new names behind a version check.

- Richer hook inputs: `prompt_id` (the UUID of the prompt being processed,
  matching the OpenTelemetry `prompt.id` attribute, absent until the first user
  input) and `effort` (a `HookEffort`, `{level: str}`: the effort setting when
  the hook runs, a skill's, subagent's or `ultrathink` level included, or the
  level that ran if the model lacks yours; `$CLAUDE_EFFORT` holds the same in
  command hooks) on tool-context inputs; `duration_ms` on `PostToolUse`
  and `PostToolUseFailure` (tool execution time, excluding permission-prompt and
  hook time); `last_assistant_message`, `background_tasks`
  (`BackgroundTaskSummary`: shell, subagent, monitor or workflow) and
  `session_crons` (`SessionCronSummary`: a cron expression and a prompt) on
  `Stop` and `SubagentStop`. `agent_id`/`agent_type` move onto the four
  tool-lifecycle inputs.
- **21 `*HookSpecificOutput` types, all exported** (8 existed in 0.2.165, only 4
  of them exported; 13 are new). **12 are for events that are still not
  registrable from Python** — `UserPromptExpansion`, `SessionStart`,
  `PostToolBatch`, `PermissionDenied` (`retry: bool`), `PreModelSwitch`,
  `PostModelSwitch`, `Elicitation`, `ElicitationResult`, `CwdChanged`,
  `FileChanged`, `WorktreeCreate`, `MessageDisplay` — so the type existing is
  not the event existing, and `HOK020` still fires on all of them.
- `SystemInitData` (`system`/`init` data with a `capabilities` list; see
  `options-reference.md`).

The ten `HookEvent` literals are **unchanged**, so nothing above widens what you
may register. From 0.2.169 `SessionStart` and `Setup` hook events are emitted
regardless of `include_hook_events`: `False` does not suppress them.

## Claude Code changes that reach hook authors (2.1.299–2.1.312)

- **`updatedInput` is validated like Claude's own input (2.1.300)** for
  `PreToolUse` and `PermissionRequest`: unknown keys are dropped, and input the
  tool rejects **denies the call**.
- **`UserPromptSubmit` runs before a skill or slash command expands (2.1.299)**:
  it sees the typed `/skill …` line; blocking it also stops the skill's shell.
- **A hook that cannot answer now refuses (2.1.299)**: an action a plugin hook
  can block is refused when the hook cannot be handed it or cannot answer.
- **Hooks that start a background process**: print the decision first and
  redirect the background process's output, or the call is blocked with
  `refusing to honor the suspect capture`.
- **Windows and PowerShell fail closed (2.1.299, 2.1.309, 2.1.310)**: a failing
  shell-form `PreToolUse`/`PermissionRequest` hook blocks the call, also without
  Git for Windows; for a PowerShell guard set `"onFailure": "block"`.
- **Prompt and agent hooks run at most 24 at a time per session, sub-agents
  included, plus at most 12 that have waited longer than their event's timeout;
  a `timeout` under 1 second counts as 1 second** (changelog 2.1.312; from
  2.1.302 the cap was 12 per event). The hooks page read 2026-10-29 still says
  "If more than 12 of them are prompt or agent hooks, 12 of those run at once"
  per event: the docs lag the changelog. Waiting hooks queue, and each one's
  `timeout` starts when it starts. Agent hooks honour their `model` (2.1.300).
- **`SubagentStop` fires once per subagent (2.1.311)**: before, it ran about
  twice a minute for each running subagent. On older CLIs dedupe on `agent_id`.
- **Skill hooks are capped per source (2.1.304+)**: the skills of one source
  (project, personal folder, each plugin) register at most 1,024 hooks and
  16,384 matcher characters per session; past it the debug log says
  `registers none of its hooks`.
- **`@` mentions bypass `PreToolUse`** (no tool call); a `Read` deny rule still
  blocks the path, and `CLAUDE_CODE_DISABLE_FILE_MENTIONS=1` (2.1.299+) makes
  Claude read it with its tools so the hooks run.

## The one thing hooks are uniquely good for

`can_use_tool` fires **only** when the CLI's rules evaluate to "ask". It is not
called for a tool already allowed by `allowed_tools`, by `acceptEdits` or
`bypassPermissions`, or by a `permissions.allow` setting — and the SDK emits a
`CanUseToolShadowedWarning` when you set both. So **to observe or gate every
tool call, use a `PreToolUse` hook.** That is also what this plugin's eval
runner captures trace events from.

Measured: `include_hook_events=True` alone emits no `HookEventMessage`.

## Hooks in `.claude/settings.json`

Command hooks configured in a settings file are a different mechanism with the
same event names. They load only when `setting_sources` includes `project` (or
`user`/`local` for those tiers). An eval with `setting_sources=[]` will not run
them — usually correct, since a run that depends on the developer's settings
file is not reproducible. `HOK030` reports the situation rather than judging it.
Frontmatter hooks in a **project subagent** file run only after the workspace
trust dialog was accepted for the folder the file came from, and "a `-p`
session doesn't count as accepting it" — do not rely on them in a headless run.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/hooks>
(available hooks, matchers, callback inputs and outputs, asynchronous output,
hook timeout), <https://code.claude.com/docs/en/hooks> (matcher patterns,
JSON output, per-event sections),
<https://code.claude.com/docs/en/agent-sdk/permissions#how-permissions-are-evaluated>,
<https://code.claude.com/docs/en/hooks#hooks-that-start-a-background-process>,
<https://code.claude.com/docs/en/hooks#failed-hooks-on-windows-without-git-bash>,
<https://code.claude.com/docs/en/hooks#pretooluse> (`@` mentions, `"defer"`,
`ask` in auto mode, `SubagentHandback`, `effort`, frontmatter-hook trust),
<https://code.claude.com/docs/en/env-vars>,
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.299,
2.1.300, 2.1.302, 2.1.304, 2.1.309, 2.1.310, 2.1.311 `SubagentStop`, 2.1.312
hook cap entries), the SDK `CHANGELOG.md`
(0.2.169); `claude-agent-sdk` 0.2.174 `types.py:284-297` (`HookEvent`, ten literals),
`:299-509` (hook input types), `:511-725` (`hookSpecificOutput` per event),
`:728-815` (`HookJSONOutput`), `:818` (`HookContext`), `:828`
(`HookCallback`), `:840` (`HookMatcher`), `:2531-2542` (concurrent dispatch),
`:2554-2560` (`include_hook_events`), `:2190-2279`
(`CanUseToolShadowedWarning`), `:614` (`StopHookSpecificOutput`), `:625`
(`SubagentStopHookSpecificOutput`), `:299` (`HookEffort`). The "emits nothing
without a registered hook" observation was measured by this plugin on
2026-09-30. The 0.2.166+ list was first read from the SDK repository at
`b6e9d12f` on 2026-10-11 and checked against the 0.2.174 wheel on 2026-10-24.
Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296
docs; re-read 2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs.
Re-read 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
