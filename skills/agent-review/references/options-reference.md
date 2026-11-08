# `ClaudeAgentOptions`: all 50 fields

Read from the installed dataclass, `claude-agent-sdk` 0.2.182
(`ClaudeAgentOptions`, `types.py:2341-2813`; 49 fields from 0.2.174 to 0.2.180, 50 fields since 0.2.181 added `client_app`; 0.2.182's `types.py` is 21 lines longer than 0.2.178-0.2.180's, so every line here moved). It is a plain `@dataclass`, so an unknown or misspelled
keyword raises `TypeError` at construction, and `dataclasses.replace()` works
for per-case overrides.

**O** = a case may override it (JSON-expressible, not runner-owned). **R** =
runner-owned: a case that sets it breaks isolation or is not serialisable.

## What the model is and how hard it thinks

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `model` | `str \| None` | `None` | O | unset means Claude Code's default for the account: Opus 5.5 on every plan and on the API unless a model is saved there (`model-config`, 2026-11-14; measured 2026-11-10 with an API key: `claude-opus-5-5`). From 2.1.311 the `[1m]` suffix is dropped from names where it has no effect (still accepted) |
| `fallback_model` | `str \| None` | `None` | O | one id or a comma-separated chain |
| `effort` | `EffortLevel \| None` | `None` | O | `low` `medium` `high` `xhigh` `max`; the SDK side of Claude Code's `/effort` (passed as `--effort`). Higher levels mostly buy more verification and edge-case checking, not a better approach (`agent-deploy/references/cost-controls.md`, article of 2026-09-25) |
| `thinking` | `ThinkingConfig \| None` | `None` | O | `{"type":"adaptive"}`, `{"type":"enabled","budget_tokens":N}`, `{"type":"disabled"}`, optional `display`. On Amazon Bedrock and Google Cloud's Agent Platform, Claude Code doesn't pass `display` for Opus 4.6, Sonnet 4.6, Haiku 4.5 and earlier models, which use their default (docs 2026-11-06) |
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
| `permission_prompt_tool_name` | `str \| None` | `None` | R | the MCP tool it names must answer with **one text block** holding `{"behavior": "allow"}` or `{"behavior": "deny", "message": …}` and **no `structuredContent`** (`FastMCP(structured_output=False)`), or Claude Code refuses the waiting call with `Permission prompt tool returned an invalid result` (`errors`, read 2026-11-14) |
| `can_use_tool` | `CanUseTool \| None` | `None` | R | a callable the SDK calls when the permission flow resolves to a prompt; skipped for a call an `allowed_tools` entry, a settings allow rule or the mode approves (use a `PreToolUse` hook to check those) |

## How it behaves

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `system_prompt` | `str \| preset \| custom \| file \| None` | `None` | O | unset = the SDK's minimal prompt, not the `claude_code` preset |
| `permission_mode` | `PermissionMode \| None` | `None` | O | `default` `acceptEdits` `plan` (docs: "Claude explores and plans") `bypassPermissions` `dontAsk` `auto`. `None` is **not** the same as `"default"` — see below |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | O | programmatic subagents; take precedence over `.claude/agents/*.md` of the same name |
| `hooks` | `dict[HookEvent, list[HookMatcher]] \| None` | `None` | R | callables; the runner adds its capture and fault hooks here. `HookMatcher` fields: `matcher`, `hooks`, `timeout`, and from 0.2.177 `on_failure` (`"continue"`/`"block"`/`None`; `HOK011`, `hooks-catalog.md`) |
| `output_format` | `dict \| None` | `None` | O | only `{"type":"json_schema","schema":{...}}` is acted on |
| `verbatim_prompts` | `bool` | `False` | O | needs CLI 2.1.248+ |
| `sandbox` | `SandboxSettings \| None` | `None` | O | `ignoreViolations` is `dict[str, list[str]]` from 0.2.166 (`types.py:1139`), as the Python page now documents: each key matches part of a command or `*`, each value lists text to match in a violation line, and "A matching access is still blocked" — it filters the report only; `allowAllUnixSockets` also covers Linux VM sockets (`AF_VSOCK`); `failIfUnavailable`, `filesystem` (`denyWrite`) and `allowNestedUserNamespaces` (2.1.305) are forwarded though undeclared; `autoAllowBashIfSandboxed` defaults to **`False`** from SDK 0.2.182 / Claude Code 2.1.324 (it was `True`): sandboxed Bash goes through the normal permission flow unless you set it |
| `plugins` | `list[SdkPluginConfig]` | `[]` | O | |

## Ceilings

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `max_turns` | `int \| None` | `None` | O | count each turn with tool calls, plus one for the final text-only response; without it the run ends `error_max_turns` with no final response. Measured 2026-10-29: one needed tool call with `max_turns=1` → `subtype error_max_turns`, `stop_reason tool_use`, `is_error True`, `num_turns 2`, no final text |
| `max_budget_usd` | `float \| None` | `None` | O | client-side estimate; counts subagent spend; ends the query with `error_max_budget_usd`. A **soft** cap: the estimate can pass the value, so leave headroom |
| `task_budget` | `TaskBudget \| None` | `None` | O | |
| `load_timeout_ms` | `int` | `60000` | O | |
| `max_buffer_size` | `int \| None` | `None` | O | |

## Where it runs and what it loads

| Field | Type | Default | | Note |
|---|---|---|---|---|
| `cwd` | `str \| Path \| None` | `None` | R | the runner forces a fresh directory per run |
| `cli_path` | `str \| Path \| None` | `None` | R | the **only** way to use the PATH `claude` instead of the bundled binary |
| `settings` | `str \| None` | `None` | O | a path or inline JSON; outranks user/project/local settings. From 0.2.182 a path is read relative to `cwd` and settings that cannot be loaded raise `CLIConnectionError` at connect (a missing file used to be logged and skipped), and Claude Code 2.1.325 stops at start-up when settings that turn the sandbox on fail validation instead of running Bash unsandboxed |
| `setting_sources` | `list[SettingSource] \| None` | `None` | O | `user` `project` `local`. Unset behaves like the CLI: everything loads. `[]` disables those three |
| `add_dirs` | `list[str \| Path]` | `[]` | O | |
| `env` | `dict[str, str]` | `{}` | O | **merged** into the inherited environment in Python (replaced, in TypeScript). Cannot remove an inherited variable. `API_TIMEOUT_MS` here is "how long each request attempt can wait for response headers" (default `600000`, `0` = no limit on 2.1.305+), not a cap on a streaming response |
| `client_app` | `str \| None` | `None` | O | 0.2.181+: your app's label (`"my-app/1.0.0"`), sent on API requests; sets `CLAUDE_AGENT_SDK_CLIENT_APP` for the subprocess and wins over a value in `env`; must be valid in an HTTP header (a character above U+00FF stops every request); `""` sends none. With neither set, a subscription-signed-in session sends the installed distribution's name once a qualifying Claude Code exists ("No released Claude Code qualifies yet"); API-key, Bedrock, Vertex, Foundry and telemetry-off sessions send nothing (`types.py:2813`) |
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
the model, and `set_model()` with no argument switches to Claude Code's default
model. Pass `"default"` or `"dontAsk"` explicitly — `lint_agent.py` reports the
omission as `OPT013`; this plugin's runner supplies `"dontAsk"` when it is unset.

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

## Not fields: two functions and two result keys

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
  on the wire, and **neither is on the 0.2.182 TypedDict** — read both with
  `.get()`. Measured 2026-10-11: `costBasis == "list"` on an API key, and the
  dict held two models (the agent's and the CLI's background Haiku 5.5).
- `credential_expires_at` (Claude Code 2.1.318 changelog; not in the docs) is in
  `claude -p --output-format json` results only when a stored claude.ai sign-in
  is in use (absent with an API key, measured 2026-11-04). It is **not** a
  `ResultMessage` field: the SDK's parser drops unknown result keys. That JSON
  has no `permission_mode` key either; the mode is in the stream `init`.

## Built-in tool output: the shapes moved

A `PostToolUse` `updatedToolOutput` must match the tool's own shape or it is
rejected and the original kept. **Edit** returns `filePath`, `oldString`,
`newString`, `originalFile`, `structuredPatch`, `userModified`, `replaceAll`,
`gitDiff` (no `message`, `replacements`, `file_path`); **Write** `type:
"create"|"update"`; **Read** branches on `type` under `file` (from 2.1.317 an
unchanged file is read again, not stubbed); **Glob** and **Grep** carry counts
and `filenames`; the Python docs page lists every shape.

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
nothing among the 50 fields or the seven message types carries agent state, so
assert state through files, `structured_output` or mock call records.

## Released in 0.2.166 (gate as "0.2.166+")

0.2.166 added richer hook inputs, 13 more `*HookSpecificOutput` types (21 in
all) and a documented init shape; `ClaudeAgentOptions` is exactly these 50 (49 before 0.2.181)
fields. Guard those names on 0.2.140–0.2.165. **`SystemInitData`** types
`SystemMessage.data` for `system`/`init`: `claude_code_version`, `cwd`, `tools`,
`mcp_servers`, `model`, `permissionMode`, `apiKeySource`, `skills`, `plugins`,
`fast_mode_state?` (`off`/`cooldown`/`on`), `fast_mode_disabled_reason?`
(`sdk_opt_in_required` measured) and `capabilities?`, among others. Use `capabilities` to **feature-detect instead of
comparing versions**, ignoring unknown strings: CLI 2.1.325 sends 19 (2.1.319 and 2.1.321 send 15), adding the undocumented
`mcp_call_check_permissions_v1` (recorded, never required) to the 14 that 2.1.316 and 2.1.318 sent (the `interrupt_*_v1` four, `msg_lifecycle_v1`,
`request_marker_lists_v1`, `ask_user_question_unanswered_v1`,
`lifecycle_wakeup_source_v1`, `sdk_mcp_tools_list_changed`, `sdk_mcp_manifests`,
`mcp_read_resource_v1`, `mcp_tool_ui_meta_v1`, `ui_surface_v1`,
`mcp_call_result_not_for_model_v1`); 2.1.310 sent 13. Read every key with
`.get()`: CLIs also send undeclared keys (`original_cwd`, `memory_paths`,
`view_mode`, `ultrathink_available` from 2.1.316, `ultrathink_typed_raises` from
2.1.318).

---

Sources: `claude-agent-sdk` 0.2.182, installed at
`site-packages/claude_agent_sdk/types.py:2341-2813` (the 50 fields in
declaration order), `:25` `PermissionMode`, `:30` `SdkBeta`, `:33`
`SettingSource`, `:37` `EffortLevel`, `:286` `HookEvent`, `:866` `on_failure`, `:1708`
`ResultMessage`, `:2185` `ThinkingConfig`;
<https://code.claude.com/docs/en/agent-sdk/python#claudeagentoptions> (also
`ResultMessage.is_error`, `ResultError`, `API_TIMEOUT_MS`), `_errors.py:56`
(`ResultError`), the Claude Code `CHANGELOG.md` (2.1.305, 2.1.307, 2.1.317 Read stub),
<https://code.claude.com/docs/en/agent-sdk/custom-tools#control-tool-access>,
<https://code.claude.com/docs/en/agent-sdk/permissions#allow-and-deny-rules>,
<https://code.claude.com/docs/en/agent-sdk/configuration#load-settings-files>,
<https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget> (the
`max_turns` "+1" rule), <https://code.claude.com/docs/en/agent-sdk/configuration>
(`set_model()` with no model),
<https://code.claude.com/docs/en/agent-sdk/session-storage>,
<https://code.claude.com/docs/en/permission-modes>,
<https://code.claude.com/docs/en/permissions#network-paths>,
<https://code.claude.com/docs/en/agent-sdk/permissions> (auto mode and
`set_model()`), <https://code.claude.com/docs/en/headless> (`init.capabilities`),
<https://code.claude.com/docs/en/settings-reference> (`sandbox.filesystem.denyWrite`,
`sandbox.failIfUnavailable`, `sandbox.ignoreViolations`); the Python page's
`SandboxIgnoreViolations` and `thinking.display` text read 2026-11-08;
<https://claude.dev/blog/spending-your-effort/> ("Using Claude Code: Spending your effort",
2026-09-25, what effort buys); `types.py:1474`
`SystemInitData`, `:1456` `FastModeState`, `:1460` `FastModeDisabledReason`,
`:1139` `SandboxIgnoreViolations`, `:1154` `SandboxSettings`. The
`max_turns=1 -> num_turns=2` result was measured by this plugin on 2026-09-30;
`costBasis`, `thinkingTokens` and the two-model `model_usage` 2026-10-11 (SDK
0.2.165, CLI 2.1.294); the init keys, capabilities and fast-mode values
2026-10-17 to 2026-11-02 (CLI 2.1.292–2.1.316) and 2026-11-04 (CLI 2.1.318, with
the `-p` JSON keys); the CHANGELOG 2.1.318 (`credential_expires_at`). Re-read
2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs; re-read
2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs (line numbers
re-pinned); `max_turns=1` re-measured 2026-10-29; `[1m]` from the 2.1.311 changelog.
Line numbers re-pinned to 0.2.178 on 2026-11-04 (unchanged in 0.2.179/0.2.180) and to 0.2.182 on 2026-11-14; 15 capabilities measured on 2.1.319 (2026-11-08) and 2.1.321, 19 on 2.1.325 (2026-11-14); `client_app`, `settings` and the prompt-tool rule from `types.py` 0.2.182 and the docs read 2026-11-14.
Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
