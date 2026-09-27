# `ClaudeAgentOptions`: all 49 fields

Read from the installed dataclass, `claude-agent-sdk` 0.2.162
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
| `allowed_tools` | `list[str]` | `[]` | O | **permission only**. Pre-approves; never restricts. Globs allowed after a literal `mcp__<server>__` prefix |
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
| `permission_mode` | `PermissionMode \| None` | `None` | O | `default` `acceptEdits` `plan` `bypassPermissions` `dontAsk` `auto` |
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
| `max_budget_usd` | `float \| None` | `None` | O | client-side estimate; counts subagent spend; ends the query with `error_max_budget_usd` |
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

---

Sources: `claude-agent-sdk` 0.2.162, installed at
`site-packages/claude_agent_sdk/types.py:1971-2430` (the 49 fields in
declaration order), `:25` `PermissionMode`, `:30` `SdkBeta`, `:33`
`SettingSource`, `:37` `EffortLevel`, `:284` `HookEvent`, `:1340`
`ResultMessage`, `:1817` `ThinkingConfig`;
<https://code.claude.com/docs/en/agent-sdk/python#claudeagentoptions>,
<https://code.claude.com/docs/en/agent-sdk/custom-tools#control-tool-access>,
<https://code.claude.com/docs/en/agent-sdk/permissions#allow-and-deny-rules>,
<https://code.claude.com/docs/en/agent-sdk/configuration#load-settings-files>,
<https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget>,
<https://code.claude.com/docs/en/agent-sdk/session-storage>. The
`max_turns=1 -> num_turns=2` result was measured by this plugin on 2026-09-30.
