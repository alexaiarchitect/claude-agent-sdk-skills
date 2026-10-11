# `ClaudeAgentOptions`: all 49 fields

Read from the installed dataclass, `claude-agent-sdk` 0.2.165
(`types.py:1971-2430`). It is a plain `@dataclass`, so an unknown or misspelled
keyword raises `TypeError` at construction, and `dataclasses.replace()` works
for per-case overrides.

**O** = a case may override it (JSON-expressible and not owned by the runner).
**R** = runner-owned: a case that sets it breaks isolation or is not
serialisable.

## What the model is and how hard it thinks

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `model` | `str \| None` | `None` | O | unset means Claude Code's default for the account |
| `fallback_model` | `str \| None` | `None` | O | one id or a comma-separated chain |
| `effort` | `EffortLevel \| None` | `None` | O | `low` `medium` `high` `xhigh` `max` |
| `thinking` | `ThinkingConfig \| None` | `None` | O | `{"type":"adaptive"}`, `{"type":"enabled","budget_tokens":N}`, `{"type":"disabled"}`, optional `display` |
| `max_thinking_tokens` | `int \| None` | `None` | O | **deprecated**, use `thinking` |
| `betas` | `list[SdkBeta]` | `[]` | O | only `"context-1m-2025-08-07"` |

## What it may call

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `tools` | `list[str] \| ToolsPreset \| None` | `None` | O | **availability**. `[]` removes every built-in; `{"type":"preset","preset":"claude_code"}` restores the CLI set. MCP tools unaffected |
| `allowed_tools` | `list[str]` | `[]` | O | **permission only**. Pre-approves; never restricts. Globs allowed after a literal `mcp__<server>__` prefix. Never approves a read from a **network path** — see below |
| `disallowed_tools` | `list[str]` | `[]` | O | **both**. A bare name removes the tool from context; a scoped rule (`Bash(rm *)`) denies matching calls in every mode |
| `skills` | `list[str] \| "all" \| None` | `None` | O | exact names only; rejects wildcards with `ValueError` since 0.2.129. Adds the Skill tool to `allowed_tools` automatically |
| `mcp_servers` | `dict \| str \| Path` | `{}` | R | the runner substitutes mocks here |
| `strict_mcp_config` | `bool` | `False` | O | ignore `.mcp.json`, user settings, plugin servers and claude.ai connectors |
| `permission_prompt_tool_name` | `str \| None` | `None` | R | |
| `can_use_tool` | `CanUseTool \| None` | `None` | R | a callable; fires only when the rules evaluate to "ask" |

## How it behaves

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `system_prompt` | `str \| preset \| custom \| file \| None` | `None` | O | unset = the SDK's minimal prompt, not the `claude_code` preset |
| `permission_mode` | `PermissionMode \| None` | `None` | O | `default` `acceptEdits` `plan` `bypassPermissions` `dontAsk` `auto`. `None` is **not** the same as `"default"` — see below |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | O | programmatic subagents; take precedence over `.claude/agents/*.md` of the same name |
| `hooks` | `dict[HookEvent, list[HookMatcher]] \| None` | `None` | R | callables; the runner adds its capture and fault hooks here |
| `output_format` | `dict \| None` | `None` | O | only `{"type":"json_schema","schema":{...}}` is acted on |
| `verbatim_prompts` | `bool` | `False` | O | needs CLI 2.1.248+ |
| `sandbox` | `SandboxSettings \| None` | `None` | O | |
| `plugins` | `list[SdkPluginConfig]` | `[]` | O | |

## Ceilings

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `max_turns` | `int \| None` | `None` | O | not a hard stop on assistant turns: measured `max_turns=1` → `num_turns=2` |
| `max_budget_usd` | `float \| None` | `None` | O | client-side estimate; counts subagent spend; ends the query with `error_max_budget_usd`. A **soft** cap: the estimate can pass the value, so leave headroom |
| `task_budget` | `TaskBudget \| None` | `None` | O | |
| `load_timeout_ms` | `int` | `60000` | O | |
| `max_buffer_size` | `int \| None` | `None` | O | |

## Where it runs and what it loads

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `cwd` | `str \| Path \| None` | `None` | R | the runner forces a fresh directory per run |
| `cli_path` | `str \| Path \| None` | `None` | R | the **only** way to use the PATH `claude` instead of the bundled binary |
| `settings` | `str \| None` | `None` | O | a path or inline JSON; outranks user/project/local settings |
| `setting_sources` | `list[SettingSource] \| None` | `None` | O | `user` `project` `local`. Unset behaves like the CLI: everything loads. `[]` disables those three |
| `add_dirs` | `list[str \| Path]` | `[]` | O | |
| `env` | `dict[str, str]` | `{}` | O | **merged** into the inherited environment in Python (replaced, in TypeScript). Cannot remove an inherited variable |
| `extra_args` | `dict[str, str \| None]` | `{}` | O | raw CLI flags |
| `user` | `str \| None` | `None` | O | |

## Sessions

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `continue_conversation` | `bool` | `False` | R | |
| `resume` | `str \| None` | `None` | R | |
| `resume_session_at` | `str \| None` | `None` | R | |
| `resume_drops_turn` | `str \| None` | `None` | R | |
| `fork_session` | `bool` | `False` | R | |
| `session_id` | `str \| None` | `None` | R | |
| `session_store` | `SessionStore \| None` | `None` | R | an object; mirrors transcripts, not `CLAUDE.md` |
| `session_store_flush` | `SessionStoreFlushMode` | `"batched"` | O | or `"eager"` |
| `enable_file_checkpointing` | `bool` | `False` | R | required by `rewind_files()` |

## What you see of the run

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `include_partial_messages` | `bool` | `False` | O | |
| `include_hook_events` | `bool` | `False` | O | emits nothing unless a hook is actually registered |
| `forward_subagent_text` | `bool` | `False` | O | |
| `stderr` | `Callable[[str], None] \| None` | `None` | R | a callable |
| `debug_stderr` | `Any` | `sys.stderr` | R | **deprecated and no longer read by the transport** |

## Two carve-outs the tables cannot hold

**`permission_mode=None` does not mean `"default"`.** With the mode unset the
CLI resolves it: `permissions.defaultMode` from a settings file where one
applies, otherwise the built-in default — and from Claude Code **2.1.285** the
built-in default for a session that does not fetch the interactive feature flags
(a third-party provider, telemetry off, a gateway token) is **`auto`**, where a
classifier reviews each shell command and network request and a broad allow rule
such as a bare `Bash` is dropped. Before TypeScript Agent SDK v0.3.286 omitting
the mode did equal `default`; it no longer does. Pass `"default"` or
`"dontAsk"` explicitly — `lint_agent.py` reports the omission as `OPT013`, and
this plugin's runner supplies `"dontAsk"` itself when the agent leaves it unset.

**Network paths are outside the allow system** (Claude Code 2.1.292+). A read of
a Windows UNC path (`\\server\share\file`) or a macOS/Linux `/net` automount
path gets its own permission check that an allow rule, `allowed_tools`, a
`PreToolUse` `"allow"` return and the auto-mode classifier all fail to bypass.
`dontAsk` **denies** such a read rather than prompting; only `bypassPermissions`
and the plan-mode bypass skip the check. Map a drive letter and `--add-dir`, or
mount locally, if the agent genuinely needs the data.

## Not fields: two functions and one result key

- `fork_session(session_id, directory=None, up_to_message_id=None, title=None)
  -> ForkSessionResult` copies a transcript into a new session. It raises
  `ValueError` for a malformed UUID, a session with no messages, or an
  `up_to_message_id` that is not in the transcript, and `FileNotFoundError` when
  the session does not exist. A fork carries **no file checkpoints from before
  the fork**, so `rewind_files()` cannot reach back past it. Distinct from the
  `fork_session: bool` option above, which forks on resume.
- `ClaudeSDKClient.get_context_usage() -> ContextUsageResponse` returns what
  `/context` shows: `categories`, `totalTokens`, `maxTokens`, `rawMaxTokens`,
  `percentage`, `model`, `isAutoCompactEnabled`, `memoryFiles`, `mcpTools`,
  `agents`, `gridRows`, plus optional `autoCompactThreshold`,
  `deferredBuiltinTools`, `systemTools`, `systemPromptSections`, `slashCommands`,
  `skills`, `messageBreakdown`, `apiUsage`. The reply is an **unbilled
  off-stream token-counting request**, so polling it costs nothing.
- `ModelUsage` rows in `ResultMessage.model_usage` carry `costBasis`
  (`list` | `managed` | `unknown`, Claude Code 2.1.246+) and `thinkingTokens`
  on the wire, and **neither is on the 0.2.165 TypedDict** — read both with
  `.get()`. Measured 2026-10-11: `costBasis == "list"` on an API key, and the
  dict held two models (the agent's and the CLI's background Haiku 5.5).

## Built-in tool output: the shapes moved

A `PostToolUse` hook returning `updatedToolOutput` has to match the tool's own
shape or the replacement is rejected and the original kept, so the shape matters.
**Edit** now returns `filePath`, `oldString`, `newString`, `originalFile`,
`structuredPatch`, `userModified`, `replaceAll`, `gitDiff` — the old `message`,
`replacements` and `file_path` keys are gone. **Write** returns
`type: "create"|"update"` plus `structuredPatch`/`gitDiff`; **Read** branches
on `type` (`text`/`image`/`notebook`/`pdf`/`parts`/`file_unchanged`) under a
`file` key; **Glob** adds `durationMs`, `numFiles`, `filenames`, `truncated`,
`totalMatches`, `countIsComplete` (2.1.191+); **Grep** is unified into `mode`,
`numFiles`, `filenames`, `content`, `numLines`, `numMatches`, `totalFiles`
(2.1.208+), `totalLines` (2.1.210+), `appliedLimit`, `appliedOffset`;
**TodoWrite** returns `oldTodos`/`newTodos`; **ExitPlanMode** adds `isAgent`,
`planWasEdited`, `awaitingLeaderApproval`, `requestId`.

## Literals worth memorising

- `PermissionMode`: `default`, `acceptEdits`, `plan`, `bypassPermissions`,
  `dontAsk`, `auto` — six.
- `SettingSource`: `user`, `project`, `local` — three.
- `EffortLevel`: `low`, `medium`, `high`, `xhigh`, `max` — five.
- `HookEvent` (Python): `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
  `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `Notification`,
  `SubagentStart`, `PermissionRequest` — ten. **Not** `SessionStart`/`SessionEnd`.
- `SdkBeta`: `context-1m-2025-08-07` — one.
- `SessionStoreFlushMode`: `batched`, `eager`.
- Result `subtype`: `success`, `error_max_turns`, `error_during_execution`,
  `error_max_budget_usd`.
- `terminal_reason`: `completed`, `max_turns`, `aborted_streaming`,
  `aborted_tools`, `api_error`.

## Deprecated, all three still accepted

| What | Use instead |
|---|---|
| `max_thinking_tokens` | `thinking` |
| `debug_stderr` | the `stderr` callback |
| `"Skill"` in `allowed_tools` | the `skills` option |

## Two things that are not fields

`temperature`, `top_p` and `max_tokens` do not exist on the options object in
either language. Set `effort` or a spend cap, or call the Messages API when you
need them.

There is no state store: nothing among the 49 fields or the seven message types
carries agent state. Assert state through files, `structured_output` or mock
call records instead.

## 0.2.166+ (not reachable from the pinned release)

The SDK's `main` branch adds richer hook inputs (`prompt_id`, `effort`,
`duration_ms`, `last_assistant_message`, `background_tasks`, `session_crons`),
17 more `*HookSpecificOutput` types and a documented `SystemInitData` shape with
a `capabilities` list for feature detection. **None of it exists in 0.2.165**:
`ClaudeAgentOptions` is still exactly these 49 fields on `main` too, and the six
permission modes, five effort levels and ten hook events are unchanged. Guard
any use of those names on the installed version.

---

Sources: `claude-agent-sdk` 0.2.165, installed at
`site-packages/claude_agent_sdk/types.py:1971-2430` (the 49 fields in
declaration order), `:25` `PermissionMode`, `:30` `SdkBeta`, `:33`
`SettingSource`, `:37` `EffortLevel`, `:284` `HookEvent`, `:1340`
`ResultMessage`, `:1817` `ThinkingConfig`;
<https://code.claude.com/docs/en/agent-sdk/python#claudeagentoptions>,
<https://code.claude.com/docs/en/agent-sdk/custom-tools#control-tool-access>,
<https://code.claude.com/docs/en/agent-sdk/permissions#allow-and-deny-rules>,
<https://code.claude.com/docs/en/agent-sdk/configuration#load-settings-files>,
<https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget>,
<https://code.claude.com/docs/en/agent-sdk/session-storage>,
<https://code.claude.com/docs/en/permission-modes>,
<https://code.claude.com/docs/en/permissions#network-paths>. The
`max_turns=1 -> num_turns=2` result was measured by this plugin on 2026-09-30;
`costBasis`, `thinkingTokens` and the two-model `model_usage` were measured
2026-10-11 on SDK 0.2.165 with bundled CLI 2.1.294. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs: `types.py` is byte-identical
to 0.2.162, so every line number above is unchanged.
