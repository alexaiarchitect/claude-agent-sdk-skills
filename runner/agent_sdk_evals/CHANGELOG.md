# Changelog — `agent_sdk_evals`

The runner is versioned separately from the plugin that ships it; `VERSION` is
what a project's copy carries and what the plugin's staleness check compares.

## 0.2.5 — 2026-11-08

Re-pinned to `claude-agent-sdk` 0.2.182 with its bundled CLI 2.1.325 (docs and
changelog re-read at Claude Code 2.1.325 on 2026-11-14, 52 pages with lastmod
2026-11-12 to 2026-11-14); minimum supported SDK stays 0.2.140. 0.2.180
(2026-11-09) was a CLI-only release (bundled 2.1.321); **0.2.181 (2026-11-12,
CLI 2.1.323) and 0.2.182 (2026-11-13, CLI 2.1.325) change code**: a new
`client_app` option (the 50th `ClaudeAgentOptions` field, `types.py:2813`), the
transport now reads the CLI version from the `init` message instead of probing
`claude --version`, and `settings` that cannot be loaded or merged with `sandbox`
raise `CLIConnectionError` instead of being skipped. None of 0.2.179-0.2.182 has
a CHANGELOG entry upstream (see
https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.182 and
the v0.2.180...v0.2.182 compare). `types.py` gained 21 lines (lines up to 191
unchanged, 196-2478 moved by 2, 2505-2673 by 4, 2675-2807 by 5, 2808 on by 21),
so every `types.py:<line>` citation was renumbered. Modes (6), Python hook
events (10), `HookSpecificOutput` members (21), exports (159), `ResultMessage`
fields (19) and `HookMatcher` fields (4) are unchanged. No runner behaviour
changed; the model policy did. A project copy at 0.2.4 is reported as older
(`DEP001`).

- **`OPTION_NAMES` has 50 entries**: `client_app` (`str | None`, default `None`)
  sets `CLAUDE_AGENT_SDK_CLIENT_APP` for the Claude Code subprocess, the app
  label sent on API requests; it must be valid in an HTTP header. It is
  overridable from a case (`EVC004` does not list it). The SDK derives a label
  from the installed distribution only for subscription-signed-in sessions and
  only once a qualifying Claude Code exists ("No released Claude Code qualifies
  yet", `types.py:2813`); the runner sets nothing.
- **Model policy**: `CURRENT_MODELS` adds **`claude-fable-5-2`** (launched
  2026-11-09: $8/$40 per Mtok, cache reads $0.20, 1M context, 128k output, API
  default effort `high`, Claude Code default `medium`, needs Claude Code
  2.1.321+). `claude-fable-5-1` stays current: the models page lists it as
  legacy but still available with no deprecation date (retirement not sooner
  than 2027-09-01). `AGT010`/`AGT011` suggestion text names Fable 5.2.
- **The default-model sentence in `OPT012` and `CFG060` was wrong and is
  corrected.** The 2026-10-11 measurement that put Claude Code's default at
  `claude-fable-5-1` ($0.34, 4x Sonnet) ran on subscription auth with a model
  recorded on that account. The `model-config` page says no Fable model is any
  plan's default; a run with no `model` starts on the account's default or saved
  model, Opus 5.5 on every plan and on the API unless a model is saved. Measured
  with an API key on Claude Code 2.1.322 (2026-11-10): `claude-opus-5-5`,
  $0.0667 for "Reply with exactly: ready", 2.0x Sonnet 5.5 ($0.0331). The advice
  is unchanged: pin `model`.
- **`init` on 2.1.325 carries 19 `capabilities`** (15 on 2.1.319 and 2.1.321):
  the four new strings are `reload_plugins_refuse_if_busy_v1`, `ui_pane_widget_v1`,
  `voice_call_talk_line_v1` and `withdrawn_files_note_v2`; the init key set, the
  24 tools and the four built-in `plugins[]` entries are unchanged. `Capture`
  records capabilities when present and never requires them, so no code changed.
  `tests/fixtures/traces/init_2_1_325.{script,trace}.jsonl` hold the measured
  run, which ended in an authentication failure: the `init`, a synthetic
  `AssistantMessage` (`model: "<synthetic>"`, `error: "authentication_failed"`)
  and a `ResultMessage` with `subtype: "success"`, `is_error: true`,
  `api_error_status: 401`, `terminal_reason: "api_error"` and
  `total_cost_usd: 0` — the shape a run with a revoked API key produces, which
  the runner reports as `NOT_EVALUATED` with the result text, never as a FAIL.
- **What a 0.2.4 copy should know** (Claude Code 2.1.321-2.1.325 and the docs
  read on 2026-11-14; changelog only unless said so):
  - `sandbox.autoAllowBashIfSandboxed` now defaults to **`false`** (Claude Code
    2.1.324; the Python SDK docs say the `False` default needs SDK 0.2.182 or
    later): a sandboxed Bash command goes through the normal permission flow
    unless the setting is `true`. A case that relied on the sandbox to
    auto-approve Bash under `default` mode now prompts; the runner's forced
    `dontAsk` denies instead. Set the key explicitly.
  - `claude -p` and the SDK **no longer run Bash unsandboxed** when `--settings`
    or SDK settings that turn the sandbox on fail validation: start-up stops and
    names the invalid setting (2.1.325), and the 0.2.182 transport raises
    `CLIConnectionError` for settings it cannot load. A run with a broken
    `settings` path now ends `NOT_EVALUATED` at connect instead of running.
  - `permissions.denyInsteadOfPrompting` (2.1.319+) is documented on the
    settings page: in `-p` runs it denies calls that would prompt, skips
    `can_use_tool` and `--permission-prompt-tool`, drops `AskUserQuestion`, and
    in auto mode ends the turn after 20 refused calls as `error_during_execution`.
    The runner never sets it; a case that does must expect those denials.
  - A structured-output result must be checked for `is_error` before
    `structured_output` is used (`agent-sdk/structured-outputs`, 2026-11-12):
    the runner's `result` event already records both.
  - `task_type` `"mcp_task"` is now documented for Python background MCP tool
    calls (the TS-only note in 0.2.4 is withdrawn); `TaskStarted` events with
    it are recorded like any other.
  - OpenTelemetry: `claude_code.safety_event` is withdrawn (2.1.312 and later
    never send it); refused tool calls are found through `tool_decision`.
    `OTEL_EXPORTER_OTLP_PROTOCOL` defaults to `http/protobuf` from 2.1.323.
  - `fable` resolves to Fable 5.2 and `best` to the same model as `opus` from
    2.1.321; `--permission-mode auto` with auto mode unavailable starts in Manual
    (2.1.325); unknown model ids are assumed to have a 1M context window
    (`CLAUDE_CODE_DISABLE_1M_CONTEXT=1` keeps 200K).
  - `CLAUDE_CODE_DISABLE_AGENT_PROGRESS_SUMMARIES=1` (since 2.1.318) turns off
    subagent progress summaries and the requests that write them.
  - The result file's `config` still does not record `effort` (left for a later
    release).
- `DOCS_READ_AT_CLI = "2.1.325"`.

## 0.2.4 — 2026-11-08

Re-pinned to `claude-agent-sdk` 0.2.179 with its bundled CLI 2.1.319 (docs and
changelog re-read at Claude Code 2.1.319, 17 pages with lastmod 2026-11-06/07);
minimum supported SDK stays 0.2.140. 0.2.179 is a **CLI-only release**: against
0.2.178 it changes `pyproject.toml`, `_version.py`, `_cli_version.py` and the
bundled binary, and its tag carries no CHANGELOG entry (see
https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.179 and
the v0.2.178...v0.2.179 compare). `types.py` is byte-identical (2,914 lines), so
every `types.py:<line>` citation holds, and the 49 options, 6 permission modes,
10 Python hook events, 21 `HookSpecificOutput` members, 159 exports, 19
`ResultMessage` fields and the 4 `HookMatcher` fields are unchanged. One runner
behaviour changed (below, auto memory); the rest is version strings, comments
and a new test fixture. A project copy at 0.2.3 is reported as older (`DEP001`)
and should be updated so its runs stop sharing auto memory.

- **The runner disables Claude Code auto memory in eval runs so runs stay
  independent.** Every run's `ClaudeAgentOptions.env` now carries
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` (`RUN_ENV_DEFAULTS`), added to the agent's
  own `env` entries, which are kept; neither the agent's options nor a case can
  turn it back on. Auto memory loads in Agent SDK sessions regardless of
  `setting_sources` (`agent-sdk/claude-code-features`; `agent-sdk/hosting`
  recommends this variable for multi-tenant apps; the 2.1.319 `init` reports
  `memory_paths.auto` with `setting_sources=[]`, measured 2026-11-08), and the
  agent writes it with `Write`/`Edit` under `~/.claude/projects/<cwd>/memory/`.
  The runner's per-run temporary `cwd` already gives each run its own folder,
  so the switch is what guarantees it: no run loads memory, none leaves a
  memory folder behind on the host, and a run whose path is ever reused cannot
  read an earlier run's notes. A 0.2.3
  copy can get the same by setting the variable in the agent's own options'
  `env` (case `env` keys must start with `EVAL_` and only reach the scaffold).

- **`init` on 2.1.319 carries 15 `capabilities`** (14 on 2.1.316 and 2.1.318):
  the new string is `mcp_call_check_permissions_v1`; the init key set and the
  tool list are unchanged (measured 2026-11-08 with `setting_sources=[]`).
  `Capture` records capabilities when present and never requires them, so no
  code changed; `tests/fixtures/traces/init_2_1_319.{script,trace}.jsonl` hold
  the measured message and what `Capture` writes from it.
- **What a 0.2.3 copy should know** (Claude Code 2.1.319 changelog unless noted;
  changelog only, not reproduced here unless said so):
  - `claude -p` now exits 1 (text and JSON output) when auto mode refused actions
    because no safety check was available. The runner forces `dontAsk` unless a
    case sets a mode; a case that runs in `auto` can now end with
    `ProcessError(exit_code=1)`, which the runner classifies as before (exit 2,
    outcome `NOT_EVALUATED`, never a FAIL).
  - A run that hits a full disk now gives an SDK host the run's own error rather
    than an unrelated one, so the `NOT_EVALUATED` reason names the real cause.
  - Claude Code moves MCP tasks to the background at once;
    `CLAUDE_CODE_DISABLE_MCP_TASK_BACKGROUND=1` makes it wait inline. A call
    becomes an MCP task in an Agent SDK session only under the conditions the
    `mcp` page lists (among them `CLAUDE_AUTO_BACKGROUND_TASKS=1`), which the
    runner never sets; a case that sets them and wants the call to wait can put
    the variable in its `env`.
  - `claude -p --resume` with a deferred MCP tool that is no longer available
    exits 1 and keeps the pending call; `CLAUDE_CODE_DROP_UNAVAILABLE_DEFERRED_TOOL=1`
    with a prompt drops it (also on the `hooks` and `env-vars` pages, 2.1.319).
    The runner owns `resume` (a case cannot set it) and starts every run fresh,
    so it is not affected; a resumed session's
    `stop_reason: "tool_deferred_unavailable"` is still reported as the
    `tool_deferred` outcome.
  - The `hook_callback_failed` informational texts (both `on_failure` modes) were
    measured on 2.1.319 and are identical to 2.1.318's; the 2.1.319 changelog's
    fix for text dropped from informational messages sent to SDK clients does
    not change them. The runner's fault and budget hooks keep the default.
- `DOCS_READ_AT_CLI = "2.1.319"` (was 2.1.318).

## 0.2.3 — 2026-11-05

Docs-only re-read: no SDK or Claude Code release since 0.2.2, so the pins stay
`claude-agent-sdk` 0.2.178 with its bundled CLI 2.1.318 and the documentation is
re-read at Claude Code 2.1.318 (13 pages with lastmod 2026-11-04); minimum
supported SDK stays 0.2.140. `types.py` is unchanged (2,914 lines), so every
`types.py:<line>` citation, the 49 options, 6 permission modes and 10 Python hook
events hold as checked for 0.2.2. Nothing in the runner's behaviour changed:
version strings and comments only. A project copy at 0.2.2 behaves the same and
is reported as older (`DEP001`) only so it picks up the new version string.

- **What a 0.2.2 copy should know.**
  - Reading `permission_denials`: the `agent-sdk/permissions` page now says that
    a call an `allowed_tools` entry or a settings allow rule approves, and a call
    the permission mode approves (a file edit in `acceptEdits`), runs without
    calling `can_use_tool`; a `PreToolUse` hook still runs for those calls. So an
    entry in `ResultMessage.permission_denials` came from a deny rule, a hook
    `deny`, a `can_use_tool` deny, or the mode turning a prompt into a denial
    (the runner's default `dontAsk`); a call an allow rule or the mode approved
    never reaches `can_use_tool` and is not there. A scoped allow rule's other
    calls fall through to the permission mode, not to the callback. The
    runner's capture and fault hooks are `PreToolUse` hooks, so they see
    rule- and mode-approved calls as before; no trace field changed.
  - Startup exits: per the `errors` page (2.1.318), `claude -p` exits 1 each
    time while `~/.claude.json` is broken, until it is repaired, and a
    non-interactive run whose organization settings fail to load prints the
    error and exits 1. Through the SDK such a child surfaces as
    `ProcessError(exit_code=1)` before the first message, which the runner
    classifies as before (exit 2, outcome `NOT_EVALUATED`, never a FAIL).
    Docs only, not reproduced here.
- `DOCS_READ_AT_CLI = "2.1.318"` (unchanged).

## 0.2.2 — 2026-11-04

Re-checked against `claude-agent-sdk` 0.2.178 with its bundled CLI 2.1.318
(docs and changelog read at Claude Code 2.1.318); minimum supported SDK stays
0.2.140. **The first SDK API change since 0.2.166:** 0.2.177 added
`HookMatcher.on_failure` (`types.py:866`); 0.2.178 changes only
`_cli_version.py`, `_version.py` and the bundled binary. `types.py` grew by 13
lines (up to 854 unchanged, 855-2320 +11, 2321 on +13), so every `types.py:<line>`
the plugin cites was renumbered and re-checked against the wheel. The 49
options, 6 permission modes, 10 Python hook events, 21 `HookSpecificOutput`
members (only `PreCompact` lacks one), 159 exports and 19 `ResultMessage` fields
are unchanged. No runner behaviour changed: pins, comments and tests only. A
project copy at 0.2.1 behaves the same and is reported as older (`DEP001`) only so
it picks up the new version string.

- **`HookMatcher.on_failure` (SDK 0.2.177+, Claude Code 2.1.317+).** A field of
  the matcher, not a `ClaudeAgentOptions` option, so `OPTION_NAMES` stays 49 and
  no case or override can name it. What it means for the hook callbacks a
  project registers:
  - Unset or `"continue"` (the default, as before): a callback that raises,
    returns `None` (a path with no `return`) or returns a value the CLI rejects
    counts as no decision, so a crashing `PreToolUse` guard lets the call reach
    the normal permission flow. Measured on 2.1.318: the CLI sends a
    `SystemMessage` with `subtype "informational"`, `level "warning"`,
    `data["tag"] == "hook_callback_failed"` and content ending "Its answer was
    treated as empty.", and the tool runs.
  - `"block"`: the same failures block the action. Measured: the same
    informational message, ending "onFailure is \"block\", so this failure counts
    as a block." (so it appears in both modes, not only the default one the docs
    describe), then a tool result with `is_error: true` reading `PreToolUse:Bash
    hook error: [callback]: failed; blocking because onFailure is "block"` (the
    callback's own error text is not shown to Claude). The blocked call is listed
    in `ResultMessage.permission_denials`, the run still ends `subtype
    "success"`, and the model may retry the call, which spends a turn (size
    `max_turns` for it).
  - A callback with no opinion must `return {}`; unrecognised keys are not a
    failure; a guard that catches its own error and returns `{}` is not failing.
    `Stop`, `SubagentStop`, `TaskCompleted` and `TeammateIdle` ignore the field;
    a `PermissionRequest` block counts only before `can_use_tool` answers;
    `PostToolUse` failures arrive after the tool ran; with `"block"` a timeout
    also blocks `PreCompact`, `Elicitation` and `WorktreeCreate`.
  - With any value but `"continue"` (the SDK does not validate it), connecting
    raises `CLIConnectionError` before a prompt is sent if the CLI is too old to
    honour it ("does not honor on_failure") or the session was already running
    ("did not register your hooks").
- **The runner's own hooks stay on the default.** The capture and fault-injection
  matchers (`faults.build_hooks`) leave `on_failure` unset on purpose: a crash in
  them is a harness bug, and with `"block"` it would block the agent's tool call
  and fail the case for a reason the case never tested. A crash still leaves the
  informational message in the trace as a plain `system` event with
  `data.tag == "hook_callback_failed"`, so it is visible, not silent. Leaving the
  field unset also keeps the runner working with SDKs before 0.2.177.
- **What a 0.2.1 copy should know about 2.1.317/2.1.318.**
  - The 2.1.318 `init` still carries the same 14 `capabilities`; its new key
    `ultrathink_typed_raises` is not a `SystemInitData` field and is dropped like
    every undeclared key (measured; no new fixture).
  - Changelog only, not measured here: `claude -p` now exits 1 (text and json)
    when a full disk or quota loses transcript or `~/.claude.json` writes
    (2.1.317); `claude -p` and SDK sessions no longer report success when an API
    error cut off a reply while a mod hooked `turn.step` (2.1.318); failing custom
    slash commands now print in `-p`/SDK sessions (2.1.318); unattended runs stop
    rewriting `~/.claude.json`, and a non-interactive start no longer replaces an
    invalid one (2.1.318).
  - `credential_expires_at` in `claude -p` JSON (2.1.318) appears only with a
    stored claude.ai sign-in: absent with an API key (measured). It is not a
    `ResultMessage` field (the SDK drops unknown keys) and the runner never parses
    `-p` JSON, so nothing reads it.
  - Subagents and teammates on a different model from the session now use that
    model's saved effort level or its default, not the session's (2.1.317
    changelog; the `model-config` docs carry the rule): set `effort` on an
    `AgentDefinition` when a case depends on it.
- `DOCS_READ_AT_CLI = "2.1.318"`.

## 0.2.1 — 2026-11-02

Re-checked against `claude-agent-sdk` 0.2.176 with its bundled CLI 2.1.316
(docs and changelog read at Claude Code 2.1.316); minimum supported SDK stays
0.2.140. No SDK API change: 0.2.175 and 0.2.176 change only `_cli_version.py`,
`_version.py` and the bundled binary (wheel diff against 0.2.174), `types.py` is
byte-identical, and the 49 options, 6 permission modes, 10 Python hook events,
21 `HookSpecificOutput` members (only `PreCompact` lacks one) and 159 exports
are re-verified against the installed wheel. No runner code changed beyond the
pins and comments; a project copy at 0.2.0 behaves the same and is reported as
older (`DEP001`) only so it picks up the new version string.

- **What a 0.2.0 copy should know.**
  - Startup failures: the 2.1.314 changelog says `claude -p` that fails at
    startup now prints the error and exits 1 (it used to exit 0 with no
    output). That is the changelog's claim; it was not reproduced here: six
    bad flags or configs (`--settings` to a missing file, a bad `--mcp-config`,
    an unknown `--resume`, a bad `--permission-mode`, bad `--agents`, bad
    `--setting-sources`) already exited 1 with the error on stderr on 2.1.310,
    and still do on 2.1.316. Through the SDK (0.2.174 and 0.2.176) such a child
    surfaces as `ProcessError(exit_code=1)` before the first message; the runner
    classifies it as before (`session.classify_exception`: exit 2, outcome
    `NOT_EVALUATED`, never a FAIL). No classification text changed.
  - The 2.1.316 `init` carries 14 `capabilities` (new:
    `ask_user_question_unanswered_v1`) and a new key `ultrathink_available`.
    Capabilities are recorded, never required; `ultrathink_available` is not a
    `SystemInitData` field and is dropped like every undeclared key. Measured
    once live (`tests/fixtures/traces/init_2_1_316.*`).
  - From 2.1.314 the parent no longer keeps each subagent's tool results until
    a long headless/SDK turn ends (changelog). Memory, not billing: cost and
    `max_budget_usd` behaviour are unchanged.
- **`HookMatcher.on_failure` is not supported.** It exists only on upstream
  `main` (`d38e51e`, 2026-11-02, after 0.2.176). The 2.1.316 CLI does not answer
  `hook_on_failure_supported`, so `on_failure="block"` raises
  `CLIConnectionError` at connect (measured). It is not an option, so
  `OPTION_NAMES` stays 49; a test asserts the pinned `HookMatcher` has no such
  field, to be flipped when a release ships it.
- `DOCS_READ_AT_CLI = "2.1.316"`.

## 0.2.0 — 2026-10-29

Re-checked against `claude-agent-sdk` 0.2.174 with its bundled CLI 2.1.310
(docs and changelog read at Claude Code 2.1.312); minimum supported SDK stays
0.2.140. No SDK API change: no release since 0.2.174 (upstream `main` differs
only in its bundled CLI string), `types.py` is byte-identical, and the 49
options, 6 permission modes, 10 Python hook events and 21 `HookSpecificOutput`
members (only `PreCompact` lacks one) are re-verified against the installed
wheel. The minor version moves with the plugin's 0.2.0 release (new skill
`/agent-sdk:agent-design`). The runner's reports changed, so a project copy at
0.1.4 is reported as older (`DEP001`) and offered the upgrade.

- **A turn-limit result states how to size `max_turns`.** The docs
  (`agent-sdk/agent-loop`, read 2026-10-29) now say: count each turn with tool
  calls plus one for the final text-only response; without that extra turn the
  run ends `error_max_turns` with no final response. Measured the same day on
  CLI 2.1.310: one tool call under `max_turns=1` ends `subtype
  "error_max_turns"`, `stop_reason "tool_use"`, `is_error true`, `result` null,
  `num_turns` 2, then `ResultError` from the iterator; with `max_turns=2` the
  run succeeds with the answer. A `terminal` grader's reason now carries that
  sentence (`graders/terminal.py`, `MAX_TURNS_PLUS_ONE`) whenever the run ended
  on the turn limit; verdicts and outcome labels are unchanged. The plugin's
  `RES010` finding and `max_turns` trajectory signature say the same.
- **`\uXXXX`-escaped characters are tolerated.** From Claude Code 2.1.311,
  `--output-format json`/`stream-json` write DEL, C1 and Unicode format
  characters inside strings as `\uXXXX` escapes; the parsed values are
  unchanged. Confirmed with tests: the capture and the trace replay loader
  keep such characters through a round trip, and the plugin's session import
  decodes them. No code change was needed.
- `DOCS_READ_AT_CLI = "2.1.312"` records which Claude Code documentation the
  runner's comments were read against (a test keeps it equal to the plugin's).
- Documentation-only notes (no runner code depends on them): from 2.1.312,
  prompt and agent hooks run at most 24 at a time per session, sub-agents
  included, plus at most 12 that waited past their timeout (a `timeout` under
  1 s counts as 1 s); and `claude_code.safety_event` is no longer sent (it was
  sent 2.1.307–2.1.311). 2.1.311 also fixed `-p`/SDK transcripts being saved
  out of order, which the plugin's session import already reorders.

## 0.1.4 — 2026-10-24

Re-checked against `claude-agent-sdk` 0.2.174 with its bundled CLI 2.1.310
(docs and changelog read at Claude Code 2.1.310); minimum supported SDK stays
0.2.140. No SDK API change since 0.2.168: the 49 options, 6 permission modes,
10 Python hook events and the 19 `ResultMessage` fields are re-verified against
the installed wheel. The runner's behaviour changed, so a project copy at 0.1.3
is reported as older (`DEP001`) and offered the upgrade.

- **A refusal is not an error result.** The Python SDK docs now say
  `ResultMessage.is_error` can be `True` with `subtype="success"`: when
  `stop_reason` is `"refusal"` (the model declined) or
  `"tool_deferred_unavailable"` (a deferred tool was missing on resume), and for
  any other `stop_reason` as an error reported in place of a model response; read
  `stop_reason` first, then `terminal_reason`, then `subtype`. The new
  `RESULT_STOP_REASON_OUTCOMES` maps the two to the outcomes `refusal` and
  `tool_deferred`, and `capture.result_outcome()` classifies a result that way.
  The trace `result` event already carried `subtype`, `is_error`,
  `terminal_reason` and `stop_reason` together (0.1.3, measured on 2.1.310);
  the per-run block of `<case>.result.json` now carries `stop_reason` and
  `is_error` too.
- **Limit wording in a refusal is not a usage limit.** The capture and the
  `ResultError` mapping no longer search a refusal's or a deferred tool's
  result text for limit words, so such a run is never marked NOT_EVALUATED as a
  usage-limit hit. A `ResultError` whose `data["stop_reason"]` is `refusal` or
  `tool_deferred_unavailable` is reported with the error kind `refusal` or
  `tool_deferred` (exit hint 1) instead of `result_error`, and a `terminal`
  grader that does not set `allow_error` names which of the two it saw.
- **The permission-default rationale cites the docs.** "In Claude Code v2.1.302
  or later, `claude -p` and Agent SDK runs with no permission mode set start in
  Manual mode" (`default`; measured again on 2.1.310), and "Before v2.1.302,
  these runs could start in auto mode if they didn't fetch feature flags"
  (`permission-modes#which-mode-a-non-interactive-run-starts-in`). The measured
  2.1.285–2.1.301 detail stays; the runner still forces `dontAsk` when the
  agent leaves the mode unset.
- `init.capabilities` is recorded, never required: 13 strings on 2.1.310
  (`interrupt_requeue_taken_v1` and `lifecycle_wakeup_source_v1` are new). The
  `system`/`commands_changed` message 2.1.301 sent after `init` was not seen on
  2.1.310 and is still tolerated either way.
- Cost note: the bundled CLI 2.1.310 still estimates Sonnet 5.5 cache reads at
  $0.10/Mtok (measured).

## 0.1.3 — 2026-10-17

Re-checked against `claude-agent-sdk` 0.2.168 with its bundled CLI 2.1.301
(docs and changelog read at Claude Code 2.1.302); minimum supported SDK stays
0.2.140. The 49 options, 6 permission modes, 10 Python hook events, 5 effort
levels and the 19 `ResultMessage` fields are unchanged and re-verified against
the installed wheel.

- **`HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT` is `("PreCompact",)`.** SDK 0.2.166
  types 21 `*HookSpecificOutput` classes; of the 10 Python events only
  `PreCompact` has none. A `Stop` or `SubagentStop` hook may now return
  `hookSpecificOutput.additionalContext`; blocking a stop is still the
  top-level `decision: "block"`. The CLI reads that dict shape on older SDKs
  too, so the constant is not version-gated.
- **The `init` event records `capabilities`, `fast_mode_state` and
  `fast_mode_disabled_reason` when the CLI sends them** (11 capability strings
  and `off`/`sdk_opt_in_required` measured on 2.1.301). They are read with
  `.get()`, never required, and nothing grades on them. The capture tolerates
  the `system`/`commands_changed` message 2.1.301 sends right after `init`
  (a plain `system` event), the undeclared `init` keys (`original_cwd`,
  `additional_directories`, `memory_paths`, `messaging_socket_path`,
  `per_turn_effort_active`, `view_mode`, `analytics_disabled`,
  `product_feedback_disabled`) and `plugins[]` entries that carry `source`
  instead of `version`.
- **The permission-default rationale is version-ranged.** With
  `permission_mode` unset the CLI picks the mode: a headless session that
  fetches feature flags starts in `default` (measured on CLI 2.1.292 and
  2.1.301, direct API key, telemetry on); on CLI 2.1.285–2.1.301 one that does
  not (third-party provider, telemetry off, first run after an install or
  upgrade) starts in `auto`; 2.1.302+ starts those in `default` too. The runner
  still forces `dontAsk` when the agent leaves the mode unset, and
  `permission_mode_source` keeps its two values.
- **`sandbox` literals accept the released shapes.** `ignoreViolations` is
  `dict[str, list[str]]` (command-pattern substring, `"*"` for all, mapped to
  violation-text substrings; reporting only), and the forwarded-but-undeclared
  `failIfUnavailable` and `filesystem` (`denyWrite`, ...) keys are accepted
  (plugin library `options_ast.sandbox_problems`).
- Cost note: the bundled CLI 2.1.301 estimates Sonnet 5.5 cache reads at the
  list $0.10/Mtok (measured); CLI 2.1.294 used $0.20 (2026-10-11, history).

## 0.1.2 — 2026-10-11

The runner's behaviour changed, so a project copy at 0.1.1 is reported as older
(`DEP001`) and offered the upgrade.

- **`--dry-run` counts sessions, not cases.** `runs` is resolved
  narrowest-first — `--runs`, then the case's own `runs:`, then the tier's, then
  1 — and a case pinning its own repetition outranks the tier, which is the
  design. The dry run now says so: the JSON carries `sessions_total` (the sum of
  the per-case runs; one session per run, since a `turns:` or `simulated_user`
  case replays inside the one session) and per-case `runs`, `sessions` and
  `runs_source` (`"cli"` | `"case"` | `"tier"` | `"default"`), and the prose
  prints `sessions: 11 (3 cases pin runs: 3)`. The plugin's `run_evals.py
  --dry-run` reports the same total. Before this, the worked example's `pr` tier
  read as 5 sessions and started 11.

## 0.1.1 — 2026-10-11

Re-checked against `claude-agent-sdk` 0.2.165 with its bundled CLI 2.1.294;
minimum supported SDK stays 0.2.140. `types.py` is byte-identical to 0.2.162, so
the 49 options, the 6 permission modes, the 10 Python hook events, the 5 effort
levels and the `ResultMessage` fields are unchanged and re-verified against the
installed wheel rather than against the test stub.

- **`permission_mode` is resolved by the runner.** An agent whose
  `build_options()` leaves it `None` now gets `permission_mode="dontAsk"`, and
  the trace `init` event records who decided: `permission_mode_source: "agent"`
  (the agent's options or a case's `overrides` set a mode) or `"runner-default"`.
  `--dry-run` prints both. An unset mode is not `default`: from CLI 2.1.285 a
  headless session without the interactive feature flags can start in `auto`,
  where a classifier reviews each tool call and a bare allow rule no longer
  settles it, so a run's permission rules were not knowable before.
- **The `result` event says what was billed, and on what basis.**
  `models_billed` lists every model in `model_usage` and `cost_basis_list` is
  true when none reported a negotiated rate. Measured 2026-10-11: CLI 2.1.294
  bills its own background work to `claude-haiku-5-5` unasked, so the agent's
  model is not the whole cost. `costBasis` and `thinkingTokens` are on the wire
  but not on the 0.2.165 `ModelUsage` TypedDict, so both are read with `.get()`.
  The `budget` grader's help now says `max_budget_usd` is a soft cap: the
  estimate can finish over it, and only the next request is refused.
- **An imported session reports its own cost.** A session JSONL with a
  `cost-state` line (what `entrypoint: "sdk-py"` sessions write) becomes a
  synthesised `result` event carrying `total_cost_usd`, `duration_ms` and
  `model_usage`, marked `imported_cost: true`. `budget` graders can now be
  decided on imported evidence; `terminal` and `structured_output` abstain on
  one, because a cost line has no subtype, `terminal_reason` or `num_turns`.
  A `claude -p` session writes no such line and still yields no result event.
- Model policy copies added beside the option tuples: `CURRENT_MODELS` (Sonnet 5.5,
  Opus 5.5, Fable 5.1 and **Haiku 5.5**), `DEPRECATED_MODELS`
  (`claude-sonnet-4-5-20250929` retires 2026-11-30), `RETIRING_MODELS` and
  `RETIRED_MODELS`. The default model and judge model are unchanged.

## 0.1.0 — 2026-09-30

First release. Built against `claude-agent-sdk` 0.2.162 with bundled CLI 2.1.285.

- `run`, `list-tools`, `replay`, `version`, `whoami`. One JSON object as the last
  stdout line of each; exit codes 0/1/2/3.
- Trace (`agent-sdk-skills.trace/1`), result (`.result/1`) and aggregate
  (`.aggregate/1`) schemas, all snake_case and language-neutral.
- Eleven free graders (`regex`, `tool_used`, `tool_order`, `no_tool`,
  `trajectory`, `file_exists`, `structured_output`, `budget`, `hook_event`,
  `final_text`, `terminal`) and one judge grader (`llm`).
- In-process MCP mocks from `evals/mocks/<server>/<tool>.md`, hook-based fault
  injection with a seeded RNG, and a persona-driven simulated user.

Behaviour that came out of measuring the SDK rather than reading it:

- `setting_sources=[]` and `strict_mcp_config=True` are forced on every run.
- `StructuredOutput` is a synthetic tool name the CLI uses to deliver
  `output_format` results; tool graders skip it unless a grader names it.
- `Task` and `Agent` are the same tool under two names and match each other.
- `total_cost_usd` is a session running total, so the trace records
  `cost_delta_usd` and a case's cost is the last total, not a sum.
- `budget.max_turns` is the grader's own ceiling: a successful run reported
  `num_turns=2` under `max_turns=1`. Assert a tripped limit with `terminal`.
- `ToolResultBlock.is_error` is `null` on success, not `False`.
- A `hook_event` grader without its hook installed is NOT_EVALUATED, not FAILED:
  `include_hook_events=True` alone emits nothing.
- Only a `rejected` rate limit stops the suite; `allowed_warning` fired on every
  measured healthy run and is recorded, not acted on.
- `ResultError` is caught before `ProcessError`, which it subclasses.
- `whoami` reports `kind`, `cost_basis`, `plan`, `auth_method` and
  `api_provider` only; `claude auth status` also returns `email`, `orgId` and
  `orgName`, which are dropped before anything is printed or written.
