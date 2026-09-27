"""The eval runner that lives inside a user's project.

This package is the only code in the plugin allowed to import
`claude_agent_sdk`. It is copied verbatim into `<project>/evals/runner/` by the
plugin, so it depends on the standard library and the SDK and nothing else — no
`anthropic`, no `pydantic`, no YAML reader, and never the plugin's own library.

It is invoked as ``python -m agent_sdk_evals <subcommand> ...`` with
`<project>/evals/runner` and `<project>` on `PYTHONPATH` and the project as the
working directory. Every subcommand prints exactly one JSON object as its
**last** stdout line; human-readable lines may precede it. Exit codes are
0 (all cases at or above threshold), 1 (a case below threshold), 2 (usage,
import, backend or runner-version error), 3 (inconclusive: only NOT_EVALUATED
results, a cost ceiling hit with partial results, or a rejected rate limit).

The constants below are the runner's own copy of what the plugin knows about
the SDK; a test asserts the two copies are equal tuple for tuple.
"""

from __future__ import annotations

from pathlib import Path

#: Read from the sibling `VERSION` file so the copy in a project and the file
#: the plugin's staleness check reads can never disagree.
try:
    RUNNER_VERSION = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:  # pragma: no cover - the file ships with the package
    RUNNER_VERSION = "0.0.0"

__version__ = RUNNER_VERSION

SCHEMA_TRACE = "agent-sdk-skills.trace/1"
SCHEMA_RESULT = "agent-sdk-skills.result/1"
SCHEMA_AGGREGATE = "agent-sdk-skills.aggregate/1"
SCHEMA_EVAL_CONFIG = "agent-sdk-skills.eval-config/1"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INCONCLUSIVE = 3

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
MODEL_ENV_VAR = "CLAUDE_MODEL"

#: `ClaudeAgentOptions` field names in declaration order (49 fields). Used to
#: answer "is this even an option?" before a single token is spent (EVC003).
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

#: Options the runner owns: callables, objects, or things the runner sets itself.
#: A case that names one of these gets EVC004, not EVC003.
RUNNER_OWNED_OPTIONS = (
    "cwd", "cli_path", "hooks", "can_use_tool", "stderr", "debug_stderr", "mcp_servers",
    "session_store", "resume", "resume_session_at", "resume_drops_turn", "fork_session",
    "continue_conversation", "session_id", "permission_prompt_tool_name",
    "enable_file_checkpointing",
)
OVERRIDABLE_OPTIONS = tuple(name for name in OPTION_NAMES if name not in RUNNER_OWNED_OPTIONS)

#: Deprecated upstream; naming one in `overrides` is a warning, not a refusal.
DEPRECATED_OPTIONS = ("max_thinking_tokens", "debug_stderr")

#: Forced on every run unless a case overrides them. Measured 17x cost
#: difference with and without (CONTRACTS section 1.2).
ISOLATION_DEFAULTS = {"setting_sources": [], "strict_mcp_config": True}

PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto")
SETTING_SOURCES = ("user", "project", "local")
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

#: The 10 hook events the Python SDK accepts. `SessionStart`/`SessionEnd` are
#: not among them even though a `SessionStartHookSpecificOutput` type exists.
PYTHON_HOOK_EVENTS = (
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit", "Stop",
    "SubagentStop", "PreCompact", "Notification", "SubagentStart", "PermissionRequest",
)
HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT = ("Stop", "SubagentStop", "PreCompact")

#: Tool names the CLI synthesizes. `output_format` results arrive as a
#: `StructuredOutput` tool call, so trajectory-style graders skip them unless a
#: grader names one explicitly.
#: `ToolSearch` is the CLI loading deferred MCP tool schemas on the model's behalf
#: (measured: the first call of every MCP-tool case); infrastructure, not agent behaviour.
SYNTHETIC_TOOLS = ("StructuredOutput", "ToolSearch")
#: The subagent tool has two names: the CLI reports `Task`, the SDK says `Agent`.
SUBAGENT_TOOL_NAMES = ("Task", "Agent")

RESULT_SUBTYPES = ("success", "error_max_turns", "error_during_execution", "error_max_budget_usd")
TERMINAL_REASONS = ("completed", "max_turns", "aborted_streaming", "aborted_tools", "api_error")
RATE_LIMIT_STATUSES = ("allowed", "allowed_warning", "rejected")

#: Grader verdicts. Counted separately for ever; never merged.
PASSED = "PASSED"
FAILED = "FAILED"
NOT_EVALUATED = "NOT_EVALUATED"
INFORMATIONAL = "INFORMATIONAL"
STATUSES = (PASSED, FAILED, NOT_EVALUATED, INFORMATIONAL)

#: Identifies eval traffic to the backend.
CLIENT_APP = "agent-sdk-evals/" + RUNNER_VERSION


class EvalError(Exception):
    """A usage, import or configuration error: exit 2, nothing is spent."""

    def __init__(self, message: str, *, code: str = "", fix: str = "") -> None:
        self.code = code
        self.fix = fix
        super().__init__(message)

    def to_dict(self) -> dict:
        payload = {"error": str(self)}
        if self.code:
            payload["code"] = self.code
        if self.fix:
            payload["fix"] = self.fix
        return payload


class InconclusiveError(Exception):
    """Nothing could be decided: exit 3. Carries the reason and a reset time."""

    def __init__(self, message: str, *, reason: str = "", resets_at: int | None = None) -> None:
        self.reason = reason
        self.resets_at = resets_at
        super().__init__(message)


__all__ = [
    "RUNNER_VERSION", "__version__",
    "SCHEMA_TRACE", "SCHEMA_RESULT", "SCHEMA_AGGREGATE", "SCHEMA_EVAL_CONFIG",
    "EXIT_OK", "EXIT_FINDINGS", "EXIT_USAGE", "EXIT_INCONCLUSIVE",
    "DEFAULT_MODEL", "DEFAULT_JUDGE_MODEL", "MODEL_ENV_VAR",
    "OPTION_NAMES", "RUNNER_OWNED_OPTIONS", "OVERRIDABLE_OPTIONS", "DEPRECATED_OPTIONS",
    "ISOLATION_DEFAULTS", "PERMISSION_MODES", "SETTING_SOURCES", "EFFORT_LEVELS",
    "PYTHON_HOOK_EVENTS", "HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT",
    "SYNTHETIC_TOOLS", "SUBAGENT_TOOL_NAMES",
    "RESULT_SUBTYPES", "TERMINAL_REASONS", "RATE_LIMIT_STATUSES",
    "PASSED", "FAILED", "NOT_EVALUATED", "INFORMATIONAL", "STATUSES",
    "CLIENT_APP", "EvalError", "InconclusiveError",
]
