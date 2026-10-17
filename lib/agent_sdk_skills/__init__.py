"""Stdlib-only helpers shared by the `agent-sdk` plugin's skill scripts.

Nothing in this package imports `claude_agent_sdk` or `anthropic`. Agent code is
read with `ast`, never executed, so every validator runs in any Python 3.10+
interpreter even when the target project's virtualenv is missing or broken.
Scripts that truly need the SDK shell out through
:mod:`agent_sdk_skills.sdk_subprocess` to the project's own interpreter, where
the runner package (`agent_sdk_evals`, copied into the project) does the work.

Every constant below that describes the SDK was read from the installed wheel
named in `.dev/VERIFIED-FACTS.md` and is re-pinned at each upstream sync.
"""

__version__ = "0.1.3"

#: The runner package version this plugin ships under `runner/agent_sdk_evals/`.
#: A project's copy carries its own `VERSION`; `runner_version.py` compares them.
RUNNER_VERSION = "0.1.3"

#: The `claude-agent-sdk` release the rules were checked against, and the
#: oldest release the runner is known to work with (`ResultError` and the
#: mcp 2.x transport arrived in 0.2.140). The SDK bundles its own CLI, so the
#: CLI version is reported separately (`cli_version`), never derived.
SDK_TARGET = "0.2.168"
SDK_MIN_SUPPORTED = "0.2.140"
CLI_BUNDLED_WITH_TARGET = "2.1.301"

#: Model policy. Ids from platform.claude.com/docs/en/models/overview and
#: .../about-claude/model-deprecations (read 2026-10-11). Four grades, in order
#: of how urgently a reader has to act: `CURRENT_MODELS` are generally
#: available; `DEPRECATED_MODELS` have an announced retirement *date*, not just
#: a floor, so they map id -> that date; `RETIRING_MODELS` are past or within 60
#: days of their "not sooner than" date; `RETIRED_MODELS` are gone.
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
MODEL_ENV_VAR = "CLAUDE_MODEL"
CURRENT_MODELS = (
    "claude-sonnet-5-5",            # $2/$10 per Mtok, 1M context, effort high
    "claude-opus-5-5",              # $4/$20
    "claude-fable-5-1",             # $10/$50
    "claude-haiku-5-5",             # $0.10/$0.50; the `haiku` alias from CLI 2.1.293
)
#: Deprecated ids: the retirement date is committed, not a floor. Keep the date
#: in every message about one, because that is what makes the warning actionable.
DEPRECATED_MODELS = {
    "claude-sonnet-4-5-20250929": "2026-11-30",   # deprecated 2026-09-30
}
RETIRING_MODELS = (
    "claude-haiku-4-5-20251001",    # retirement not sooner than 2026-10-15
    "claude-opus-4-5-20251101",     # retirement not sooner than 2026-11-24
)
RETIRED_MODELS = (
    "claude-opus-4-1-20250805", "claude-opus-4-20250514", "claude-sonnet-4-20250514",
    "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022", "claude-3-haiku-20240307",
    "claude-3-5-sonnet-20241022", "claude-3-5-sonnet-20240620", "claude-3-opus-20240229",
    "claude-3-sonnet-20240229", "claude-mythos-preview",
)
#: Aliases the CLI resolves at run time; they never go stale but do move.
ALIAS_MODELS = ("sonnet", "opus", "haiku", "fable", "best", "default", "opusplan")

#: `ClaudeAgentOptions` field names in declaration order (`types.py:2326` of
#: claude-agent-sdk 0.2.168, 49 fields). "Is this even an option?" (EVC003).
OPTION_NAMES = (
    "tools", "allowed_tools", "system_prompt", "mcp_servers", "strict_mcp_config",
    "permission_mode", "continue_conversation", "resume", "session_id", "max_turns",
    "max_budget_usd", "disallowed_tools", "model", "fallback_model", "betas",
    "permission_prompt_tool_name", "cwd", "cli_path", "settings", "add_dirs", "env",
    "extra_args", "max_buffer_size", "debug_stderr", "stderr", "can_use_tool", "hooks",
    "user", "include_partial_messages", "include_hook_events", "forward_subagent_text",
    "verbatim_prompts", "fork_session", "resume_session_at", "resume_drops_turn", "agents",
    "setting_sources", "skills", "sandbox", "plugins", "max_thinking_tokens", "thinking",
    "effort", "output_format", "enable_file_checkpointing", "session_store",
    "session_store_flush", "load_timeout_ms", "task_budget",
)

#: Options a case may set in `overrides`: JSON-expressible and not owned by the
#: runner. A name in OPTION_NAMES but not here is EVC004 (exists, not overridable).
RUNNER_OWNED_OPTIONS = (
    "cwd", "cli_path", "hooks", "can_use_tool", "stderr", "debug_stderr", "mcp_servers",
    "session_store", "resume", "resume_session_at", "resume_drops_turn", "fork_session",
    "continue_conversation", "session_id", "permission_prompt_tool_name",
    "enable_file_checkpointing",
)
OVERRIDABLE_OPTIONS = tuple(name for name in OPTION_NAMES if name not in RUNNER_OWNED_OPTIONS)

#: Options that are deprecated upstream; naming them is a warning.
DEPRECATED_OPTIONS = ("max_thinking_tokens", "debug_stderr")

#: Isolation the runner forces unless a case overrides it (17x cost difference
#: measured with and without; see CONTRACTS §1.2).
#: The runner also resolves one *conditional* default that is not a key here,
#: because it only applies when the agent leaves the field `None`:
#: `permission_mode="dontAsk"`. With the mode unset the CLI picks it: a
#: headless session that fetches feature flags starts in `default` (measured on
#: CLI 2.1.292 and 2.1.301, direct API key, telemetry on); on CLI 2.1.285-2.1.301
#: one that does not (third-party provider, telemetry off, first run after an
#: install or upgrade) starts in `auto`, where a classifier reviews each tool
#: call and a bare allow rule no longer settles it; 2.1.302+ starts those in
#: `default` too. The runner forces `dontAsk` for unattended runs either way.
#: The trace `init` event records which way it went as `permission_mode_source`
#: ("agent" or "runner-default").
ISOLATION_DEFAULTS = {"setting_sources": [], "strict_mcp_config": True}

PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto")
SETTING_SOURCES = ("user", "project", "local")
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

#: Hook events the Python SDK accepts (`HookEvent` literal, 10 values).
#: `SessionStart`/`SessionEnd` are not among them (HOK020).
PYTHON_HOOK_EVENTS = (
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit", "Stop",
    "SubagentStop", "PreCompact", "Notification", "SubagentStart", "PermissionRequest",
)
#: Events whose hook output has no `hookSpecificOutput` type at all. Since
#: 0.2.166 the SDK types 21 `*HookSpecificOutput` classes; of the 10 Python events
#: only `PreCompact` lacks one (`Stop`/`SubagentStop` take `additionalContext`;
#: blocking a stop is still the top-level `decision: "block"`). The CLI reads the
#: dict shape on older SDKs too, so this is not version-gated.
HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT = ("PreCompact",)

#: Tool names the CLI synthesizes; trajectory-style graders skip them unless
#: named explicitly. `output_format` results arrive as a `StructuredOutput` call.
#: `ToolSearch` is the CLI loading deferred MCP tool schemas on the model's behalf
#: (measured: the first call of every MCP-tool case); infrastructure, not agent behaviour.
SYNTHETIC_TOOLS = ("StructuredOutput", "ToolSearch")
#: The subagent tool has two names: the CLI reports `Task`, the SDK and docs say `Agent`.
SUBAGENT_TOOL_NAMES = ("Task", "Agent")

#: Result subtypes and terminal reasons the SDK reports.
RESULT_SUBTYPES = ("success", "error_max_turns", "error_during_execution", "error_max_budget_usd")
TERMINAL_REASONS = ("completed", "max_turns", "aborted_streaming", "aborted_tools", "api_error")
RATE_LIMIT_STATUSES = ("allowed", "allowed_warning", "rejected")
