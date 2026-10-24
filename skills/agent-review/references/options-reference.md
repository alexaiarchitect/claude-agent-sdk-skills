# `ClaudeAgentOptions`: all 49 fields

Read from the installed dataclass, `claude-agent-sdk` 0.2.174
(`types.py:2326-2786`). It is a plain `@dataclass`, so an unknown or misspelled
keyword raises `TypeError` at construction, and `dataclasses.replace()` works
for per-case overrides.

**O** = a case may override it (JSON-expressible, not runner-owned). **R** =
runner-owned: a case that sets it breaks isolation or is not serialisable.

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
| `sandbox` | `SandboxSettings \| None` | `None` | O | `ignoreViolations` is `dict[str, list[str]]` from 0.2.166; `failIfUnavailable`, `filesystem` (`denyWrite`) and `allowNestedUserNamespaces` (2.1.305) are forwarded though undeclared |
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
| `env` | `dict[str, str]` | `{}` | O | **merged** into the inherited environment in Python (replaced, in TypeScript). Cannot remove an inherited variable. `API_TIMEOUT_MS` here is "how long each request attempt can wait for response headers" (default `600000`, `0` = no limit on 2.1.305+), not a cap on a streaming response |
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
applies, otherwise the built-in default. A session that fetches feature flags
starts in `default`; on Claude Code **2.1.285–2.1.301** one that fetches none (a
third-party provider or gateway, telemetry off) could start in **`auto`**, where
a classifier reviews each shell command and network request and a broad allow
rule such as a bare `Bash` is dropped. The docs now say "In Claude Code v2.1.302
or later, `claude -p` and Agent SDK runs with no permission mode set start in
Manual mode" (`default`). A session in `auto` that `set_model()`s to a model
without auto support drops to `default` with a `system`/`status` message
(2.1.299+); from 2.1.307 `set_model()` waits up to 15 s for the API to confirm
the model (it was refused after 5 s). Pass `"default"` or
`"dontAsk"` explicitly — `lint_agent.py` reports the omission as `OPT013`, and
this plugin's runner supplies `"dontAsk"` itself when the agent leaves it unset.

**Network paths are outside the allow system** (2.1.292+): a read of a UNC or
`/net` automount path has its own check that no allow rule, `PreToolUse`
`"allow"` or classifier bypasses, and `dontAsk` **denies** it (details in
`agent-harness/references/permission-model.md`).

## Reading the result: `stop_reason` before `is_error`

`ResultMessage.is_error` is always `True` on the `error_*` subtypes. "On
`subtype="success"` it is `True` in three cases. Check `stop_reason` to tell them
apart": **`"refusal"`** (the model declined; the text is in `result`, or in the
preceding `AssistantMessage` when `result` is empty), **`"tool_deferred_unavailable"`**
(a deferred tool was gone on resume; see `hooks-catalog.md`), and any other value
— an error reported in place of a model response (read `terminal_reason`,
`result`, `api_error_status`). So check `stop_reason`, then `terminal_reason`,
then `subtype`: a refusal's `terminal_reason` "can read `"completed"` or
`"api_error"`". A single-shot `query()` then raises `ResultError` (its `.data` is
the raw result); the docs branch `if e.data.get("stop_reason") == "refusal":`
before `elif e.terminal_reason == "api_error":`. A declined run has no
`structured_output`. No lint rule checks this; review it by hand.

## Not fields: two functions and one result key

- `fork_session(session_id, directory=None, up_to_message_id=None, title=None)
  -> ForkSessionResult` copies a transcript into a new session; `ValueError` for
  a malformed UUID, an empty session or an unknown `up_to_message_id`,
  `FileNotFoundError` for a missing session. A fork carries **no file
  checkpoints from before it**, so `rewind_files()` cannot reach back past it.
  Distinct from the `fork_session: bool` option, which forks on resume.
- `ClaudeSDKClient.get_context_usage() -> ContextUsageResponse` includes the
  data `/context` shows: `categories`, `totalTokens`, `maxTokens`,
  `rawMaxTokens`, `percentage`, `model`, `isAutoCompactEnabled`, `memoryFiles`,
  `mcpTools`, `agents`, `gridRows`, plus optional `autoCompactThreshold`,
  `deferredBuiltinTools`, `systemTools`, `systemPromptSections`, `slashCommands`,
  `skills`, `messageBreakdown`, `apiUsage` — an **unbilled** off-stream request.
- `ModelUsage` rows in `ResultMessage.model_usage` carry `costBasis`
  (`list` | `managed` | `unknown`, Claude Code 2.1.246+) and `thinkingTokens`
  on the wire, and **neither is on the 0.2.174 TypedDict** — read both with
  `.get()`. Measured 2026-10-11: `costBasis == "list"` on an API key, and the
  dict held two models (the agent's and the CLI's background Haiku 5.5).

## Built-in tool output: the shapes moved

A `PostToolUse` `updatedToolOutput` must match the tool's own shape or it is
rejected and the original kept. **Edit** returns `filePath`, `oldString`,
`newString`, `originalFile`, `structuredPatch`, `userModified`, `replaceAll`,
`gitDiff` (no `message`, `replacements`, `file_path`). **Write**: `type:
"create"|"update"` plus `structuredPatch`/`gitDiff`; **Read** branches on `type`
(`text`/`image`/`notebook`/`pdf`/`parts`/`file_unchanged`) under `file`;
**Glob** adds `durationMs`, `numFiles`, `filenames`, `truncated`, `totalMatches`,
`countIsComplete` (2.1.191+); **Grep**: `mode`, `numFiles`, `filenames`,
`content`, `numLines`, `numMatches`, `totalFiles` (2.1.208+), `totalLines`
(2.1.210+), `appliedLimit`, `appliedOffset`; **TodoWrite**: `oldTodos`/`newTodos`;
**ExitPlanMode** adds `isAgent`, `planWasEdited`, `awaitingLeaderApproval`, `requestId`.

## Literals worth memorising

- `PermissionMode`: `default`, `acceptEdits`, `plan`, `bypassPermissions`,
  `dontAsk`, `auto` — six.
- `SettingSource`: `user`, `project`, `local` — three. `EffortLevel`: `low`,
  `medium`, `high`, `xhigh`, `max` — five.
- `HookEvent` (Python): `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
  `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `Notification`,
  `SubagentStart`, `PermissionRequest` — ten. **Not** `SessionStart`/`SessionEnd`.
  Only `PreCompact` lacks a `hookSpecificOutput` type (0.2.166+).
- `SdkBeta`: `context-1m-2025-08-07` — one. `SessionStoreFlushMode`: `batched`, `eager`.
- Result `subtype`: `success`, `error_max_turns`, `error_during_execution`,
  `error_max_budget_usd`. `terminal_reason`: `completed`, `max_turns`,
  `aborted_streaming`, `aborted_tools`, `api_error`. `stop_reason` (on
  `success`): `end_turn`, `tool_use`, `tool_deferred`, `refusal`,
  `tool_deferred_unavailable`, …

## Deprecated (still accepted), and what is not there

Deprecated: `max_thinking_tokens` (use `thinking`), `debug_stderr` (the
`stderr` callback), `"Skill"` in `allowed_tools` (the `skills` option).
`temperature`, `top_p` and `max_tokens` are not options in either language; set
`effort` or a spend cap, or call the Messages API. There is no state store:
nothing among the 49 fields or the seven message types carries agent state, so
assert state through files, `structured_output` or mock call records.

## Released in 0.2.166 (gate as "0.2.166+")

0.2.166 added richer hook inputs (`prompt_id`, `effort`, `duration_ms`,
`last_assistant_message`, `background_tasks`, `session_crons`), 13 more
`*HookSpecificOutput` types (21 in all) and a documented init shape;
`ClaudeAgentOptions` is still exactly these 49 fields. Guard those names on
0.2.140–0.2.165. **`SystemInitData`** types `SystemMessage.data` for
`system`/`init`: `type`, `subtype`, `uuid`, `session_id`, `agents?`,
`apiKeySource`, `betas?`, `claude_code_version`, `cwd`, `tools`, `mcp_servers`
(`name`, `status`, `source?`), `model`, `permissionMode`, `slash_commands`,
`terminal_slash_commands?`, `output_style`, `skills`, `plugins` (`name`, `path`,
`version?`), `plugin_errors?`, `fast_mode_state?` (`off`/`cooldown`/`on`),
`fast_mode_disabled_reason?` (`sdk_opt_in_required` measured; newer CLIs may send
others) and `capabilities?`. Use `capabilities` to **feature-detect instead of
comparing versions**, ignoring unknown strings: CLI 2.1.310 sent 13
(`interrupt_receipt_v1`, `interrupt_cancel_queued_v1`, `interrupt_send_now_v1`,
`interrupt_requeue_taken_v1`, `msg_lifecycle_v1`, `request_marker_lists_v1`,
`lifecycle_wakeup_source_v1`, `sdk_mcp_tools_list_changed`, `sdk_mcp_manifests`,
`mcp_read_resource_v1`, `mcp_tool_ui_meta_v1`, `ui_surface_v1`,
`mcp_call_result_not_for_model_v1`), 2.1.301 sent 11, 2.1.292 sent 9. Read every
key with `.get()`: 2.1.301 and 2.1.310 also sent undeclared keys (`original_cwd`,
`additional_directories`, `memory_paths`, `messaging_socket_path`,
`per_turn_effort_active`, `view_mode`, `analytics_disabled`,
`product_feedback_disabled`) and plugin entries with `source` and no `version`;
2.1.301 sent a `system`/`commands_changed` message after `init`, 2.1.310 did not.
`SandboxSettings.ignoreViolations` is now `dict[str, list[str]]` — a command
pattern (`"*"` for all) to violation-text substrings, affecting reporting only;
the Python docs page still shows the old `{file, network}` shape.

---

Sources: `claude-agent-sdk` 0.2.174, installed at
`site-packages/claude_agent_sdk/types.py:2326-2786` (the 49 fields in
declaration order), `:25` `PermissionMode`, `:30` `SdkBeta`, `:33`
`SettingSource`, `:37` `EffortLevel`, `:284` `HookEvent`, `:1695`
`ResultMessage`, `:2172` `ThinkingConfig`;
<https://code.claude.com/docs/en/agent-sdk/python#claudeagentoptions> (also
`ResultMessage.is_error`, `ResultError`, `API_TIMEOUT_MS`), `_errors.py:56`
(`ResultError`), the Claude Code `CHANGELOG.md` (2.1.305, 2.1.307),
<https://code.claude.com/docs/en/agent-sdk/custom-tools#control-tool-access>,
<https://code.claude.com/docs/en/agent-sdk/permissions#allow-and-deny-rules>,
<https://code.claude.com/docs/en/agent-sdk/configuration#load-settings-files>,
<https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget>,
<https://code.claude.com/docs/en/agent-sdk/session-storage>,
<https://code.claude.com/docs/en/permission-modes>,
<https://code.claude.com/docs/en/permissions#network-paths>,
<https://code.claude.com/docs/en/agent-sdk/permissions> (auto mode and
`set_model()`), <https://code.claude.com/docs/en/headless> (`init.capabilities`),
<https://code.claude.com/docs/en/settings-reference> (`sandbox.filesystem.denyWrite`,
`sandbox.failIfUnavailable`, `sandbox.ignoreViolations`); `types.py:1461`
`SystemInitData`, `:1443` `FastModeState`, `:1447` `FastModeDisabledReason`,
`:1126` `SandboxIgnoreViolations`, `:1141` `SandboxSettings`. The
`max_turns=1 -> num_turns=2` result was measured by this plugin on 2026-09-30;
`costBasis`, `thinkingTokens` and the two-model `model_usage` 2026-10-11 (SDK
0.2.165, CLI 2.1.294); the init keys, capabilities and fast-mode values
2026-10-17 (CLI 2.1.301, 2.1.292) and 2026-10-24 (CLI 2.1.310). Re-read
2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs; re-read
2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs, with
every line number re-pinned to 0.2.174.
