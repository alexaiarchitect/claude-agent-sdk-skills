"""A faithful stand-in for `claude_agent_sdk`, for tests that must not call it.

The plugin's own test interpreter deliberately does not have the real SDK — the
whole point of the plugin is that it works before the project's environment does
— so the runner's unit tests import this package instead, through
`PYTHONPATH=tests/fixtures/stubs:runner`.

Faithfulness is the contract. Every public name, every dataclass field and every
field *order* here was read from the installed wheel (`claude-agent-sdk` 0.2.174,
bundled CLI 2.1.310; the stub mirrors a subset of the wheel's 159 exports); `ClaudeAgentOptions` carries all 49 fields in declaration
order, so a test can compare the runner's pinned option list against
`__dataclass_fields__` exactly as the runner does at run time.

`query()` and `ClaudeSDKClient` replay a scripted list of messages instead of
talking to anything:

* `set_script([...])` / `push_script([...])` from a test, or
* `AGENT_SDK_STUB_SCRIPT=<path to a JSON or JSONL file>` in the environment.

A script entry is a dict with a `__class__` key naming the message type and the
rest of the keys being that type's fields — the same shape the measured runs in
`.dev/measured/run*.jsonl` are stored in, so a real captured session can be
replayed verbatim. An optional `_turn` splits a script across the turns of a
multi-turn `ClaudeSDKClient` session.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Generic, Literal, TypedDict, TypeVar

__version__ = "0.2.174"
__cli_version__ = "2.1.310"

T = TypeVar("T")

# -- literals ---------------------------------------------------------------

PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"]
SettingSource = Literal["user", "project", "local"]
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
SdkBeta = Literal["context-1m-2025-08-07"]
SessionStoreFlushMode = Literal["batched", "eager"]
RateLimitStatus = Literal["allowed", "allowed_warning", "rejected"]
RateLimitType = Literal["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "overage"]
ServerToolName = Literal[
    "advisor", "web_search", "web_fetch", "code_execution", "bash_code_execution",
    "text_editor_code_execution", "tool_search_tool_regex", "tool_search_tool_bm25",
]
HookEvent = Literal[
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit", "Stop",
    "SubagentStop", "PreCompact", "Notification", "SubagentStart", "PermissionRequest",
]
TERMINAL_TASK_STATUSES = {"completed", "failed", "stopped", "killed"}



# -- exported in 0.2.166 (typed shapes only; `total=False` marks NotRequired) --
# Mirrors `types.py` of 0.2.174: hook-input extras (`HookEffort` 299,
# `BackgroundTaskSummary` 391, `SessionCronSummary` 417), the 17 newly exported
# `*HookSpecificOutput` classes (511-725), `SystemInitData` and its parts
# (1404-1461), `FastModeState`/`FastModeDisabledReason` (1443/1447). Nothing in
# the stub constructs them; they exist so the export list can be compared.

FastModeState = Literal["off", "cooldown", "on"]
FastModeDisabledReason = Literal[
    "free", "preference", "extra_usage_disabled", "network_error", "unknown",
    "not_first_party", "disabled_by_env", "model_not_allowed", "sdk_opt_in_required", "pending",
]


class HookEffort(TypedDict):
    level: str


class _BackgroundTaskSummaryRequired(TypedDict):
    id: str
    type: str
    status: str
    description: str


class BackgroundTaskSummary(_BackgroundTaskSummaryRequired, total=False):
    command: str
    agent_type: str
    server: str
    tool: str
    name: str


class SessionCronSummary(TypedDict):
    id: str
    schedule: str
    recurring: bool
    prompt: str


class _SystemInitMcpServerRequired(TypedDict):
    name: str
    status: str


class SystemInitMcpServer(_SystemInitMcpServerRequired, total=False):
    source: str


class _SystemInitPluginRequired(TypedDict):
    name: str
    path: str


class SystemInitPlugin(_SystemInitPluginRequired, total=False):
    version: str


class _SystemInitPluginErrorRequired(TypedDict):
    plugin: str
    type: str
    message: str


class SystemInitPluginError(_SystemInitPluginErrorRequired, total=False):
    path: str


class _SystemInitDataRequired(TypedDict):
    type: Literal["system"]
    subtype: Literal["init"]
    uuid: str
    session_id: str
    apiKeySource: str
    claude_code_version: str
    cwd: str
    tools: list[str]
    mcp_servers: list[SystemInitMcpServer]
    model: str
    permissionMode: PermissionMode
    slash_commands: list[str]
    output_style: str
    skills: list[str]
    plugins: list[SystemInitPlugin]


class SystemInitData(_SystemInitDataRequired, total=False):
    agents: list[str]
    betas: list[str]
    terminal_slash_commands: list[str]
    plugin_errors: list[SystemInitPluginError]
    fast_mode_state: FastModeState
    fast_mode_disabled_reason: FastModeDisabledReason
    capabilities: list[str]


class PreToolUseHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["PreToolUse"]
    permissionDecision: Literal["allow", "deny", "ask", "defer"]
    permissionDecisionReason: str
    updatedInput: dict[str, Any]
    additionalContext: str


class PostToolUseHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["PostToolUse"]
    additionalContext: str
    updatedToolOutput: Any
    updatedMCPToolOutput: Any


class UserPromptSubmitHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["UserPromptSubmit"]
    additionalContext: str
    sessionTitle: str
    suppressOriginalPrompt: bool


class UserPromptExpansionHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["UserPromptExpansion"]
    additionalContext: str
    suppressOriginalPrompt: bool


class SessionStartHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["SessionStart"]
    additionalContext: str
    initialUserMessage: str
    sessionTitle: str
    watchPaths: list[str]
    reloadSkills: bool


class PostToolBatchHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["PostToolBatch"]
    additionalContext: str


class StopHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["Stop"]
    additionalContext: str


class SubagentStopHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["SubagentStop"]
    additionalContext: str


class PermissionDeniedHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["PermissionDenied"]
    retry: bool


class PreModelSwitchHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["PreModelSwitch"]
    permissionDecision: Literal["allow", "deny", "ask"]
    permissionDecisionReason: str


class PostModelSwitchHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["PostModelSwitch"]
    additionalContext: str


class ElicitationHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["Elicitation"]
    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any]


class ElicitationResultHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["ElicitationResult"]
    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any]


class CwdChangedHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["CwdChanged"]
    watchPaths: list[str]


class FileChangedHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["FileChanged"]
    watchPaths: list[str]


class _WorktreeCreateRequired(TypedDict):
    hookEventName: Literal["WorktreeCreate"]
    worktreePath: str


class WorktreeCreateHookSpecificOutput(_WorktreeCreateRequired):
    pass


class MessageDisplayHookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["MessageDisplay"]
    displayContent: str


# -- exceptions -------------------------------------------------------------

class ClaudeSDKError(Exception):
    """Base error."""


class CLIConnectionError(ClaudeSDKError):
    pass


class CLINotFoundError(CLIConnectionError):
    def __init__(self, message: str = "Claude Code not found", cli_path: str | None = None) -> None:
        self.cli_path = cli_path
        super().__init__(f"{message}: {cli_path}" if cli_path else message)


class ProcessError(ClaudeSDKError):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str | None = None) -> None:
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(message)


class ResultError(ProcessError):
    """Raised for an error result. Subclasses `ProcessError`, so catch it first."""

    def __init__(self, message: str = "", *, subtype: str | None = None,
                 errors: list[str] | None = None, result: str | None = None,
                 api_error_status: int | None = None, terminal_reason: str | None = None,
                 session_id: str | None = None, data: dict[str, Any] | None = None,
                 exit_code: int | None = None) -> None:
        self.subtype = subtype
        self.errors = errors
        self.result = result
        self.api_error_status = api_error_status
        self.terminal_reason = terminal_reason
        self.session_id = session_id
        self.data = data or {}
        super().__init__(message or (result or "result error"), exit_code=exit_code)


class CLIJSONDecodeError(ClaudeSDKError):
    def __init__(self, line: str = "", original_error: Exception | None = None) -> None:
        self.line = line
        self.original_error = original_error
        super().__init__(f"could not decode: {line[:100]}")


class CanUseToolShadowedWarning(UserWarning):
    pass


# -- content blocks ---------------------------------------------------------

@dataclass
class TextBlock:
    text: str


@dataclass
class ThinkingBlock:
    thinking: str
    signature: str = ""


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    #: Measured `null` on success, not `False`.
    is_error: bool | None = None


@dataclass
class ServerToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ServerToolResultBlock:
    tool_use_id: str
    content: dict[str, Any] = field(default_factory=dict)


ContentBlock = (TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock,
                ServerToolUseBlock, ServerToolResultBlock)


# -- messages ---------------------------------------------------------------

@dataclass
class UserMessage:
    content: str | list[Any]
    uuid: str | None = None
    parent_tool_use_id: str | None = None
    tool_use_result: Any = None
    origin: dict[str, Any] | None = None


@dataclass
class AssistantMessage:
    content: list[Any]
    model: str
    parent_tool_use_id: str | None = None
    error: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    message_id: str | None = None
    stop_reason: str | None = None
    session_id: str | None = None
    uuid: str | None = None


@dataclass
class SystemMessage:
    subtype: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskStartedMessage(SystemMessage):
    pass


@dataclass
class TaskProgressMessage(SystemMessage):
    pass


@dataclass
class TaskNotificationMessage(SystemMessage):
    pass


@dataclass
class TaskUpdatedMessage(SystemMessage):
    pass


@dataclass
class MirrorErrorMessage(SystemMessage):
    pass


@dataclass
class HookEventMessage(SystemMessage):
    """Wire form is a `system` message with subtype `hook_started`/`hook_response`."""

    hook_event_name: str = ""
    session_id: str | None = None
    uuid: str | None = None


@dataclass
class ResultMessage:
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    model_usage: dict[str, Any] | None = None
    permission_denials: list[Any] | None = None
    deferred_tool_use: dict[str, Any] | None = None
    errors: list[str] | None = None
    api_error_status: int | None = None
    uuid: str | None = None
    terminal_reason: str | None = None
    origin: dict[str, Any] | None = None


@dataclass
class StreamEvent:
    uuid: str
    session_id: str
    event: dict[str, Any]
    parent_tool_use_id: str | None = None


@dataclass
class RateLimitInfo:
    status: str
    resets_at: int | None = None
    rate_limit_type: str | None = None
    utilization: float | None = None
    overage_status: str | None = None
    overage_resets_at: int | None = None
    overage_disabled_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RateLimitEvent:
    rate_limit_info: RateLimitInfo
    uuid: str = ""
    session_id: str = ""


@dataclass
class ConversationResetMessage:
    new_conversation_id: str
    uuid: str = ""
    session_id: str = ""


Message = (UserMessage, AssistantMessage, SystemMessage, ResultMessage, StreamEvent,
           RateLimitEvent, ConversationResetMessage)


# -- options ----------------------------------------------------------------

@dataclass
class ClaudeAgentOptions:
    """All 49 fields, in the installed wheel's declaration order."""

    tools: list[str] | str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    system_prompt: Any = None
    mcp_servers: dict[str, Any] | str | Path = field(default_factory=dict)
    strict_mcp_config: bool = False
    permission_mode: str | None = None
    continue_conversation: bool = False
    resume: str | None = None
    session_id: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    fallback_model: str | None = None
    betas: list[str] = field(default_factory=list)
    permission_prompt_tool_name: str | None = None
    cwd: str | Path | None = None
    cli_path: str | Path | None = None
    settings: str | None = None
    add_dirs: list[str | Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    extra_args: dict[str, str | None] = field(default_factory=dict)
    max_buffer_size: int | None = None
    debug_stderr: Any = None
    stderr: Callable[[str], None] | None = None
    can_use_tool: Any = None
    hooks: dict[str, list[Any]] | None = None
    user: str | None = None
    include_partial_messages: bool = False
    include_hook_events: bool = False
    forward_subagent_text: bool = False
    verbatim_prompts: bool = False
    fork_session: bool = False
    resume_session_at: str | None = None
    resume_drops_turn: str | None = None
    agents: dict[str, Any] | None = None
    setting_sources: list[str] | None = None
    skills: list[str] | str | None = None
    sandbox: Any = None
    plugins: list[Any] = field(default_factory=list)
    max_thinking_tokens: int | None = None
    thinking: dict[str, Any] | None = None
    effort: str | None = None
    output_format: dict[str, Any] | None = None
    enable_file_checkpointing: bool = False
    session_store: Any = None
    session_store_flush: str = "batched"
    load_timeout_ms: int = 60000
    task_budget: Any = None


@dataclass
class AgentDefinition:
    description: str
    prompt: str
    tools: list[str] | None = None
    model: str | None = None


@dataclass
class HookMatcher:
    """No `probability` field: per-tool probability lives inside the callback."""

    matcher: str | None = None
    hooks: list[Callable[..., Awaitable[dict[str, Any]]]] = field(default_factory=list)
    timeout: float | None = None


@dataclass
class ToolAnnotations:
    title: str | None = None
    readOnlyHint: bool | None = None
    maxResultSizeChars: int | None = None


McpToolAnnotations = ToolAnnotations


@dataclass
class SdkMcpTool(Generic[T]):
    name: str
    description: str
    input_schema: Any
    handler: Callable[[Any], Awaitable[dict[str, Any]]]
    annotations: ToolAnnotations | None = None


def tool(name: str, description: str, input_schema: Any, annotations: Any = None):
    """Decorator returning an `SdkMcpTool`, exactly as the SDK's does."""
    def decorator(handler: Callable[[Any], Awaitable[dict[str, Any]]]) -> SdkMcpTool[Any]:
        return SdkMcpTool(name=name, description=description, input_schema=input_schema,
                          handler=handler, annotations=annotations)
    return decorator


@dataclass
class McpSdkServerConfig:
    type: str = "sdk"
    name: str = ""
    version: str = "1.0.0"
    instance: Any = None
    tools: list[SdkMcpTool[Any]] = field(default_factory=list)


def create_sdk_mcp_server(name: str, version: str = "1.0.0",
                          tools: list[SdkMcpTool[Any]] | None = None) -> McpSdkServerConfig:
    return McpSdkServerConfig(type="sdk", name=name, version=version, tools=list(tools or []))


# -- the scripted transport -------------------------------------------------

_SCRIPT: list[dict[str, Any]] = []
_CALLS: list[dict[str, Any]] = []

_CLASSES: dict[str, Any] = {
    "UserMessage": UserMessage, "AssistantMessage": AssistantMessage,
    "SystemMessage": SystemMessage, "HookEventMessage": HookEventMessage,
    "ResultMessage": ResultMessage, "StreamEvent": StreamEvent,
    "RateLimitEvent": RateLimitEvent, "ConversationResetMessage": ConversationResetMessage,
    "TaskStartedMessage": TaskStartedMessage, "TaskProgressMessage": TaskProgressMessage,
    "TaskNotificationMessage": TaskNotificationMessage, "TaskUpdatedMessage": TaskUpdatedMessage,
    "MirrorErrorMessage": MirrorErrorMessage,
}


def set_script(messages: list[Any]) -> None:
    """Replace the script. Entries may be dicts or already-built message objects."""
    global _SCRIPT
    _SCRIPT = list(messages)
    _CALLS.clear()


def push_script(messages: list[Any]) -> None:
    _SCRIPT.extend(messages)


def calls() -> list[dict[str, Any]]:
    """Every `query()`/`client.query()` the code under test made."""
    return list(_CALLS)


def reset() -> None:
    set_script([])


def load_script_file(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON array or a JSONL file of message dicts."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return list(json.loads(text))
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _script() -> list[Any]:
    if _SCRIPT:
        return list(_SCRIPT)
    env = os.environ.get("AGENT_SDK_STUB_SCRIPT")
    if env and Path(env).is_file():
        return load_script_file(env)
    return []


def build_message(entry: Any) -> Any:
    """Turn a script dict into the message object the SDK would have yielded."""
    if not isinstance(entry, dict):
        return entry
    payload = {k: v for k, v in entry.items() if not k.startswith("_") and k != "__class__"}
    cls = _CLASSES.get(entry.get("__class__", ""))
    if cls is None:
        return SystemMessage(subtype=entry.get("__class__", "unknown"), data=payload)
    if cls is RateLimitEvent:
        info = payload.get("rate_limit_info") or {}
        if isinstance(info, dict):
            payload["rate_limit_info"] = RateLimitInfo(**info)
    if cls in (UserMessage, AssistantMessage):
        payload["content"] = [_build_block(b) for b in (payload.get("content") or [])] \
            if isinstance(payload.get("content"), list) else payload.get("content")
    known = set(getattr(cls, "__dataclass_fields__", {}))
    return cls(**{k: v for k, v in payload.items() if k in known})


def _build_block(block: Any) -> Any:
    if not isinstance(block, dict):
        return block
    if "thinking" in block:
        return ThinkingBlock(thinking=block.get("thinking", ""), signature=block.get("signature", ""))
    if "tool_use_id" in block:
        return ToolResultBlock(tool_use_id=block["tool_use_id"], content=block.get("content"),
                               is_error=block.get("is_error"))
    if "name" in block and "id" in block:
        cls = ServerToolUseBlock if block.get("server") else ToolUseBlock
        return cls(id=block["id"], name=block["name"], input=block.get("input") or {})
    if "text" in block:
        return TextBlock(text=block["text"])
    return block


def _turn_of(entry: Any) -> int | None:
    return entry.get("_turn") if isinstance(entry, dict) else None


async def query(*, prompt: Any, options: ClaudeAgentOptions | None = None,
                transport: Any = None) -> AsyncIterator[Any]:
    """Replay the script once. Raises whatever the script says to raise."""
    _CALLS.append({"prompt": prompt, "options": options, "via": "query"})
    for entry in _script():
        if isinstance(entry, dict) and entry.get("__class__") == "raise":
            raise _build_error(entry)
        yield build_message(entry)


def _build_error(entry: dict[str, Any]) -> BaseException:
    name = entry.get("error", "ClaudeSDKError")
    kwargs = {k: v for k, v in entry.items() if k not in ("__class__", "error", "message")}
    message = entry.get("message", name)
    if name == "ResultError":
        return ResultError(message, **kwargs)
    if name == "ProcessError":
        return ProcessError(message, exit_code=kwargs.get("exit_code"), stderr=kwargs.get("stderr"))
    if name == "CLINotFoundError":
        return CLINotFoundError(message, cli_path=kwargs.get("cli_path"))
    if name == "CLIJSONDecodeError":
        return CLIJSONDecodeError(line=kwargs.get("line", ""))
    return {"CLIConnectionError": CLIConnectionError}.get(name, ClaudeSDKError)(message)


@dataclass
class McpStatusResponse:
    servers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ContextUsageResponse:
    total_tokens: int = 0


class ClaudeSDKClient:
    """Replays the script, split into turns by each entry's `_turn`."""

    def __init__(self, options: ClaudeAgentOptions | None = None, transport: Any = None) -> None:
        self.options = options
        self._connected = False
        self._turn = 0
        self._pending: list[Any] = []

    async def connect(self, prompt: Any = None) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def __aenter__(self) -> "ClaudeSDKClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.disconnect()

    def _require(self) -> None:
        if not self._connected:
            raise CLIConnectionError("Not connected. Call connect() first.")

    async def query(self, prompt: Any, session_id: str = "default") -> None:
        self._require()
        self._turn += 1
        _CALLS.append({"prompt": prompt, "options": self.options, "via": "client",
                       "turn": self._turn})
        script = _script()
        turns = {_turn_of(e) for e in script}
        if turns == {None}:
            self._pending = script if self._turn == 1 else []
        else:
            self._pending = [e for e in script if (_turn_of(e) or 1) == self._turn]

    async def receive_response(self) -> AsyncIterator[Any]:
        self._require()
        for entry in self._pending:
            if isinstance(entry, dict) and entry.get("__class__") == "raise":
                raise _build_error(entry)
            message = build_message(entry)
            yield message
            if isinstance(message, ResultMessage):
                break
        self._pending = []

    async def receive_messages(self) -> AsyncIterator[Any]:
        async for message in self.receive_response():
            yield message

    async def get_mcp_status(self) -> McpStatusResponse:
        self._require()
        servers = [{"name": name, "status": "connected"}
                   for name in (getattr(self.options, "mcp_servers", None) or {})]
        return McpStatusResponse(servers=servers)

    async def get_context_usage(self) -> ContextUsageResponse:
        self._require()
        return ContextUsageResponse()

    async def get_server_info(self) -> dict[str, Any]:
        self._require()
        return {"models": [], "commands": [], "agents": []}

    async def interrupt(self) -> None:
        self._require()

    async def set_permission_mode(self, mode: str) -> None:
        self._require()
        if self.options is not None:
            self.options.permission_mode = mode

    async def set_model(self, model: str | None = None) -> None:
        self._require()
        if self.options is not None:
            self.options.model = model

    async def rewind_files(self, user_message_id: str) -> None:
        self._require()

    async def reconnect_mcp_server(self, server_name: str) -> None:
        self._require()

    async def toggle_mcp_server(self, server_name: str, enabled: bool) -> None:
        self._require()

    async def stop_task(self, task_id: str) -> None:
        self._require()


# -- session helpers --------------------------------------------------------

def project_key_for_directory(directory: str | Path | None = None) -> str:
    path = Path(directory or Path.cwd()).resolve()
    return str(path).replace(os.sep, "-")


def get_session_messages(session_id: str, directory: str | Path | None = None,
                         limit: int | None = None, offset: int = 0) -> list[Any]:
    return []


def list_sessions(directory: str | Path | None = None, limit: int | None = None,
                  offset: int = 0, include_worktrees: bool = True) -> list[Any]:
    return []


__all__ = [
    "__version__", "__cli_version__",
    "ClaudeAgentOptions", "ClaudeSDKClient", "query", "tool", "create_sdk_mcp_server",
    "SdkMcpTool", "McpSdkServerConfig", "HookMatcher", "ToolAnnotations", "McpToolAnnotations",
    "AgentDefinition", "McpStatusResponse", "ContextUsageResponse",
    "TextBlock", "ThinkingBlock", "ToolUseBlock", "ToolResultBlock",
    "ServerToolUseBlock", "ServerToolResultBlock", "ContentBlock",
    "UserMessage", "AssistantMessage", "SystemMessage", "HookEventMessage", "ResultMessage",
    "StreamEvent", "RateLimitEvent", "RateLimitInfo", "ConversationResetMessage", "Message",
    "TaskStartedMessage", "TaskProgressMessage", "TaskNotificationMessage",
    "TaskUpdatedMessage", "MirrorErrorMessage", "TERMINAL_TASK_STATUSES",
    "ClaudeSDKError", "CLIConnectionError", "CLINotFoundError", "ProcessError", "ResultError",
    "CLIJSONDecodeError", "CanUseToolShadowedWarning",
    "PermissionMode", "SettingSource", "EffortLevel", "SdkBeta", "SessionStoreFlushMode",
    "RateLimitStatus", "RateLimitType", "ServerToolName", "HookEvent",
    "set_script", "push_script", "load_script_file", "build_message", "calls", "reset",
    "project_key_for_directory", "get_session_messages", "list_sessions",
    # exported in 0.2.166
    "SystemInitData", "SystemInitMcpServer", "SystemInitPlugin", "SystemInitPluginError",
    "FastModeState", "FastModeDisabledReason", "HookEffort", "BackgroundTaskSummary",
    "SessionCronSummary",
    "PreToolUseHookSpecificOutput", "PostToolUseHookSpecificOutput",
    "UserPromptSubmitHookSpecificOutput", "UserPromptExpansionHookSpecificOutput",
    "SessionStartHookSpecificOutput", "PostToolBatchHookSpecificOutput",
    "StopHookSpecificOutput", "SubagentStopHookSpecificOutput",
    "PermissionDeniedHookSpecificOutput", "PreModelSwitchHookSpecificOutput",
    "PostModelSwitchHookSpecificOutput", "ElicitationHookSpecificOutput",
    "ElicitationResultHookSpecificOutput", "CwdChangedHookSpecificOutput",
    "FileChangedHookSpecificOutput", "WorktreeCreateHookSpecificOutput",
    "MessageDisplayHookSpecificOutput",
]
