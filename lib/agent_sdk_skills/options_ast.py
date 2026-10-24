"""Read a Claude Agent SDK project statically: options, tools, hooks, MCP, subagents.

Everything here works on the syntax tree. Nothing is imported and nothing is
run, so a missing virtualenv, a broken dependency or a side effect at module
scope cannot affect a review — and a review works on the project that does not
start, which is exactly when it is needed.

What matters about an Agent SDK program is almost entirely in one call:
``ClaudeAgentOptions(...)``. Which tools exist, which are pre-approved, which
are removed, what pays for the session, which settings files leak in, which
hooks fire and what they return. This module extracts that call (and its
legacy ``ClaudeCodeOptions`` spelling) along with everything it references:

* keyword values as literals, as **env-derived** (``os.getenv("X", "default")``
  is recorded with its default, because a value that comes from the
  environment is not a hardcoded value), or as ``dynamic`` when they are
  computed;
* the enclosing function, so "built at module level", "built in
  ``build_options()``" and "built inside ``main()``" are distinguishable —
  only the first two can be handed to an eval runner;
* ``@tool(name, description, schema)`` functions and their schema keys, and the
  ``create_sdk_mcp_server(name=...)`` servers that publish them, which is where
  the ``mcp__<server>__<tool>`` names a grader must use come from;
* external ``mcp_servers`` entries with their ``command`` or ``url``;
* ``hooks`` events, matchers and callbacks, and for each callback whether it is
  ``async def``, how many parameters it takes, and whether it returns a dict
  carrying ``hookSpecificOutput`` with a matching ``hookEventName`` — the three
  things that decide whether a hook does anything at all;
* ``agents`` definitions, ``system_prompt`` kind, ``output_format`` shape;
* string literals that look like credentials, and model ids anywhere.

Two entry points, both returning a dataclass with ``to_dict()``:
:func:`extract_module` for one file and :func:`extract_project` for a project.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .layout import find_agent_modules

# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

#: Value kinds. `partial` is a container whose elements are not all literal.
LITERAL = "literal"
ENV = "env"
DYNAMIC = "dynamic"
PARTIAL = "partial"

OPTIONS_CALL = "ClaudeAgentOptions"
LEGACY_OPTIONS_CALL = "ClaudeCodeOptions"
OPTIONS_CALLS = (OPTIONS_CALL, LEGACY_OPTIONS_CALL)

TOOL_DECORATOR = "tool"
SERVER_FACTORY = "create_sdk_mcp_server"
HOOK_MATCHER_CALL = "HookMatcher"
AGENT_DEFINITION_CALL = "AgentDefinition"
QUERY_CALL = "query"
CLIENT_CALL = "ClaudeSDKClient"

#: Function names that mean "the program's own entry point", where options are
#: built for this process and cannot be obtained by anything else.
MAIN_NAMES = ("main", "_main", "amain", "async_main", "cli", "_run_cli")

#: The convention this plugin's scaffolds and runner expect.
BUILD_OPTIONS = "build_options"

#: Top-level keys a hook may return on *any* event (`SyncHookJSONOutput` and
#: `AsyncHookJSONOutput`). A return made only of these is well formed even
#: without `hookSpecificOutput` — `{"continue_": False, "stopReason": ...}` is
#: how a hook halts a turn, `PreCompact` has nothing else to use, and blocking a
#: `Stop`/`SubagentStop` is still the top-level `decision: "block"` (those two
#: gained a `hookSpecificOutput` with `additionalContext` in SDK 0.2.166).
HOOK_COMMON_KEYS = (
    "continue_", "continue", "suppressOutput", "stopReason", "decision",
    "systemMessage", "reason", "async_", "async", "asyncTimeout",
    "hookSpecificOutput",
)

#: `SandboxSettings` keys the SDK declares (`types.py:1141` of claude-agent-sdk
#: 0.2.174), and the keys it forwards to the CLI without declaring them
#: (`failIfUnavailable`, `filesystem` with `denyWrite` and friends; Python SDK
#: docs and `settings-reference`, read 2026-10-17). Both sets are accepted.
SANDBOX_DECLARED_KEYS = (
    "enabled", "autoAllowBashIfSandboxed", "excludedCommands", "allowUnsandboxedCommands",
    "network", "ignoreViolations", "enableWeakerNestedSandbox",
)
SANDBOX_FORWARDED_KEYS = ("failIfUnavailable", "filesystem")


def sandbox_problems(sandbox: Any) -> list[str]:
    """What is wrong with a literal `sandbox` dict, as plain sentences.

    `ignoreViolations` is `dict[str, list[str]]` from SDK 0.2.166
    (`SandboxIgnoreViolations`, `types.py:1126` of 0.2.174): a command-pattern
    substring (`"*"` for every command) mapped to substrings of the violation
    text. It changes which violations are *reported*, not what the sandbox
    blocks. The earlier `{file, network}` TypedDict shape is gone. Keys the SDK
    forwards without declaring (:data:`SANDBOX_FORWARDED_KEYS`) are accepted.
    A non-dict value (a computed one) yields no problems: nothing is known.
    """
    if not isinstance(sandbox, dict):
        return []
    problems: list[str] = []
    known = SANDBOX_DECLARED_KEYS + SANDBOX_FORWARDED_KEYS
    for key in sandbox:
        if isinstance(key, str) and key not in known:
            problems.append(f"`sandbox` key {key!r} is neither declared on `SandboxSettings` "
                            f"nor forwarded by the SDK ({', '.join(known)})")
    ignore = sandbox.get("ignoreViolations")
    if ignore is not None:
        if not isinstance(ignore, dict):
            problems.append("`ignoreViolations` must map a command pattern to a list of "
                            "violation substrings (`dict[str, list[str]]`)")
        else:
            for pattern, needles in ignore.items():
                if not isinstance(pattern, str) or not isinstance(needles, (list, tuple)) \
                        or not all(isinstance(n, str) for n in needles):
                    problems.append(f"`ignoreViolations[{pattern!r}]` must be a list of "
                                    "violation-text substrings")
    filesystem = sandbox.get("filesystem")
    if filesystem is not None and not isinstance(filesystem, dict):
        problems.append("`filesystem` must be a dict (e.g. `{\"denyWrite\": [...]}`)")
    return problems

#: A string that starts with one of these is a credential, wherever it appears.
SECRET_PREFIXES = ("sk-ant-", "sk-ant-api03-", "sk-ant-oat01-")
#: Names whose literal string value is a credential by virtue of the name.
SECRET_NAMES = (
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_ADMIN_KEY", "AWS_SECRET_ACCESS_KEY",
)
#: Placeholder values that are documentation, not a leak.
SECRET_PLACEHOLDERS = (
    "", "...", "your-api-key", "your-api-key-here", "changeme", "replace-me",
    "xxx", "todo", "none", "unset",
)

_MODEL_RE = re.compile(
    r"^(?:claude-[a-z0-9][a-z0-9.\-]*"
    r"|(?:us|eu|apac|global)\.anthropic\.claude-[a-z0-9.\-:]+"
    r"|anthropic\.claude-[a-z0-9.\-:]+"
    r"|publishers/anthropic/models/claude-[a-z0-9.\-@]+)$"
)

#: `getenv`-shaped readers: (module, attribute) pairs, plus `os.environ[...]`.
_ENV_READERS = (("os", "getenv"), ("os", "environ"), ("environ", "get"))


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, TypeError, RecursionError):
        return "<unreadable expression>"


def _call_name(node: ast.AST) -> str | None:
    """The bare name of a call, `pkg.Thing(...)` included."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _decorator_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _call_name(node)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ---------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------

@dataclass
class Value:
    """One keyword value, graded by how knowable it is.

    ``literal`` we know exactly; ``env`` comes from the environment and we know
    the fallback; ``partial`` is a list or dict with some computed elements;
    ``dynamic`` is computed and nothing can be claimed about it. The grade is
    the difference between "this agent hardcodes a model id" and "this agent
    reads its model from the environment", which is the whole of the model
    policy.
    """

    kind: str = DYNAMIC
    value: Any = None
    env_var: str | None = None
    expr: str | None = None

    @property
    def is_literal(self) -> bool:
        return self.kind == LITERAL

    @property
    def is_env(self) -> bool:
        return self.kind == ENV

    @property
    def is_dynamic(self) -> bool:
        return self.kind == DYNAMIC

    @property
    def is_known(self) -> bool:
        """True when a check may reason about :attr:`value`."""
        return self.kind in (LITERAL, ENV, PARTIAL)

    def as_str(self) -> str | None:
        return self.value if isinstance(self.value, str) else None

    def as_str_list(self) -> list[str]:
        """The string elements we are sure of; computed elements are dropped."""
        if isinstance(self.value, str):
            return [self.value]
        if isinstance(self.value, (list, tuple)):
            return [item for item in self.value if isinstance(item, str)]
        return []

    def as_dict(self) -> dict[str, Any]:
        return dict(self.value) if isinstance(self.value, dict) else {}

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.env_var:
            data["env_var"] = self.env_var
        if self.expr:
            data["expr"] = self.expr
        return data


def _dynamic_marker(node: ast.AST) -> dict[str, str]:
    return {"__dynamic__": _unparse(node)}


def _resolve_env(node: ast.AST) -> Value | None:
    """`os.getenv("X", "d")`, `os.environ.get("X", "d")`, `os.environ["X"]`."""
    if isinstance(node, ast.Subscript):
        target = _unparse(node.value)
        if target in ("os.environ", "environ"):
            key = _literal_or_none(node.slice)
            if isinstance(key, str):
                return Value(kind=ENV, value=None, env_var=key, expr=_unparse(node))
        return None
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    owner = attr = None
    if isinstance(func, ast.Attribute):
        attr = func.attr
        owner = _unparse(func.value)
    elif isinstance(func, ast.Name):
        attr, owner = func.id, ""
    if attr not in ("getenv", "get"):
        return None
    if attr == "getenv" and owner not in ("os", ""):
        return None
    if attr == "get" and owner not in ("os.environ", "environ"):
        return None
    if not node.args:
        return None
    key = _literal_or_none(node.args[0])
    if not isinstance(key, str):
        return None
    default: Any = None
    if len(node.args) > 1:
        default = _literal_or_none(node.args[1])
    else:
        for keyword in node.keywords:
            if keyword.arg == "default":
                default = _literal_or_none(keyword.value)
    return Value(kind=ENV, value=default, env_var=key, expr=_unparse(node))


def _literal_or_none(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def resolve(node: ast.AST | None) -> Value:
    """Grade one expression. Never executes anything."""
    if node is None:
        return Value(kind=DYNAMIC, expr=None)
    try:
        return Value(kind=LITERAL, value=ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        pass
    env = _resolve_env(node)
    if env is not None:
        return env
    if isinstance(node, ast.Dict):
        out: dict[Any, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            key = _literal_or_none(key_node)
            if key is None and key_node is not None:
                key = _unparse(key_node)
            child = resolve(value_node)
            out[key] = child.value if child.is_known else _dynamic_marker(value_node)
        return Value(kind=PARTIAL, value=out, expr=_unparse(node))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        items: list[Any] = []
        for element in node.elts:
            child = resolve(element)
            items.append(child.value if child.is_known else _dynamic_marker(element))
        return Value(kind=PARTIAL, value=items, expr=_unparse(node))
    if isinstance(node, ast.JoinedStr):
        return Value(kind=DYNAMIC, value=None, expr=_unparse(node))
    return Value(kind=DYNAMIC, expr=_unparse(node))


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------

@dataclass
class ToolDef:
    """One `@tool(...)` function: the contract the model is shown."""

    tool_name: str | None
    func_name: str
    lineno: int
    description: str | None = None
    is_async: bool = True
    schema_kind: str = "missing"      # types | json_schema | typeddict | dynamic | missing
    schema_keys: list[str] = field(default_factory=list)
    schema_types: dict[str, str] = field(default_factory=dict)
    path: str | None = None

    @property
    def has_description(self) -> bool:
        return bool(self.description and self.description.strip())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["has_description"] = self.has_description
        return data


@dataclass
class SdkServer:
    """A `create_sdk_mcp_server(...)` call: in-process tools under one name."""

    name: str | None
    lineno: int
    version: str | None = None
    tool_refs: list[str] = field(default_factory=list)
    assigned_to: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class McpServerRef:
    """One entry of the `mcp_servers` option, however it is spelled."""

    key: str
    kind: str = "unknown"            # sdk | stdio | http | sse | dynamic | unknown
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    expr: str | None = None
    lineno: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HookRegistration:
    """One matcher under one hook event."""

    event: str
    lineno: int
    matcher: str | None = None
    matcher_dynamic: bool = False
    matcher_regex_error: str | None = None
    callbacks: list[str] = field(default_factory=list)
    uses_hook_matcher: bool = True
    timeout: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDef:
    """One entry of the `agents` option (a programmatic subagent)."""

    name: str
    lineno: int
    call: str = AGENT_DEFINITION_CALL
    keys: list[str] = field(default_factory=list)
    tools: Value | None = None
    model: Value | None = None
    max_turns: Value | None = None
    description: bool = False
    prompt: bool = False

    @property
    def has_tools(self) -> bool:
        return self.tools is not None

    @property
    def has_max_turns(self) -> bool:
        return self.max_turns is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "lineno": self.lineno, "call": self.call,
            "keys": self.keys,
            "tools": self.tools.to_dict() if self.tools else None,
            "model": self.model.to_dict() if self.model else None,
            "max_turns": self.max_turns.to_dict() if self.max_turns else None,
            "description": self.description, "prompt": self.prompt,
            "has_tools": self.has_tools, "has_max_turns": self.has_max_turns,
        }


@dataclass
class OutputFormat:
    """The `output_format` option, checked for the one shape the CLI acts on."""

    lineno: int
    type_value: str | None = None
    has_schema: bool = False
    schema_is_dict: bool = False
    dynamic: bool = False

    @property
    def is_json_schema(self) -> bool:
        return self.type_value == "json_schema" and self.has_schema and self.schema_is_dict

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_json_schema"] = self.is_json_schema
        return data


@dataclass
class SecretLiteral:
    """A credential written into source."""

    kind: str                       # api_key_prefix | named_assignment
    lineno: int
    name: str | None = None
    preview: str = ""
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelRef:
    """A model id seen in source, and where it came from."""

    value: str
    lineno: int
    where: str = "literal"          # options | agent | env_default | literal | judge
    env_var: str | None = None
    path: str | None = None

    @property
    def hardcoded(self) -> bool:
        return self.env_var is None and self.where in ("options", "agent")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["hardcoded"] = self.hardcoded
        return data


@dataclass
class FunctionFacts:
    """What a function is, and what it returns — enough to judge a hook."""

    name: str
    lineno: int
    is_async: bool = False
    params: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    returns_dict: bool = False
    returns_empty_dict: bool = False
    returns_nonempty_dict: bool = False
    returns_unrecognised_dict: bool = False
    hook_event_names: list[str] = field(default_factory=list)
    has_hook_specific_output: bool = False
    permission_decisions: list[str] = field(default_factory=list)
    deny_without_reason: bool = False
    returns_async_ack: bool = False
    builds_options: bool = False
    path: str | None = None

    @property
    def param_count(self) -> int:
        return len(self.params)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["param_count"] = self.param_count
        return data


@dataclass
class QueryCall:
    """A `query(...)` or `ClaudeSDKClient(...)` call site."""

    call: str
    lineno: int
    has_options: bool = False
    options_expr: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OptionsCall:
    """One `ClaudeAgentOptions(...)` construction, fully unpacked."""

    call: str
    lineno: int
    path: str | None = None
    function: str | None = None          # None means module level
    in_main: bool = False
    in_build_options: bool = False
    kwargs: dict[str, Value] = field(default_factory=dict)
    unpacked: list[str] = field(default_factory=list)
    mcp_servers: list[McpServerRef] = field(default_factory=list)
    mcp_servers_dynamic: bool = False
    hooks: list[HookRegistration] = field(default_factory=list)
    hooks_dynamic: bool = False
    agents: list[AgentDef] = field(default_factory=list)
    agents_dynamic: bool = False
    system_prompt_kind: str = "absent"   # string | preset | custom | file | dynamic | absent
    system_prompt_append: bool = False
    output_format: OutputFormat | None = None

    @property
    def legacy(self) -> bool:
        return self.call == LEGACY_OPTIONS_CALL

    @property
    def injectable(self) -> bool:
        """Can anything outside this module obtain these options?

        Module level or a named builder: yes. Inside ``main()``: no — the
        options exist only for that process, so an eval runner cannot get them
        and every override has to be a source edit.
        """
        return not self.in_main

    def get(self, name: str) -> Value | None:
        return self.kwargs.get(name)

    def has(self, name: str) -> bool:
        return name in self.kwargs

    def names(self) -> list[str]:
        return sorted(self.kwargs)

    def str_list(self, name: str) -> list[str]:
        value = self.kwargs.get(name)
        return value.as_str_list() if value else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "call": self.call, "lineno": self.lineno, "path": self.path,
            "function": self.function, "in_main": self.in_main,
            "in_build_options": self.in_build_options,
            "legacy": self.legacy, "injectable": self.injectable,
            "kwargs": {k: v.to_dict() for k, v in sorted(self.kwargs.items())},
            "unpacked": self.unpacked,
            "mcp_servers": [s.to_dict() for s in self.mcp_servers],
            "mcp_servers_dynamic": self.mcp_servers_dynamic,
            "hooks": [h.to_dict() for h in self.hooks],
            "hooks_dynamic": self.hooks_dynamic,
            "agents": [a.to_dict() for a in self.agents],
            "agents_dynamic": self.agents_dynamic,
            "system_prompt_kind": self.system_prompt_kind,
            "system_prompt_append": self.system_prompt_append,
            "output_format": self.output_format.to_dict() if self.output_format else None,
        }


# ---------------------------------------------------------------------------
# module facts
# ---------------------------------------------------------------------------

@dataclass
class ModuleFacts:
    """Everything one Python file says about its agent."""

    path: str
    syntax_error: str | None = None
    imports_sdk: bool = False
    imports_legacy_sdk: bool = False
    imported_names: list[str] = field(default_factory=list)
    options_calls: list[OptionsCall] = field(default_factory=list)
    tools: list[ToolDef] = field(default_factory=list)
    sdk_servers: list[SdkServer] = field(default_factory=list)
    functions: list[FunctionFacts] = field(default_factory=list)
    query_calls: list[QueryCall] = field(default_factory=list)
    secrets: list[SecretLiteral] = field(default_factory=list)
    model_refs: list[ModelRef] = field(default_factory=list)
    deprecated_options: list[str] = field(default_factory=list)

    @property
    def has_build_options(self) -> bool:
        return any(f.name == BUILD_OPTIONS for f in self.functions)

    @property
    def option_builders(self) -> list[str]:
        """Named functions that construct options and are not `main()`."""
        return sorted({
            call.function for call in self.options_calls
            if call.function and not call.in_main
        })

    @property
    def builds_options(self) -> bool:
        return bool(self.options_calls)

    def function(self, name: str) -> FunctionFacts | None:
        for candidate in self.functions:
            if candidate.name == name:
                return candidate
        return None

    def tool_full_names(self, server: str) -> list[str]:
        return [f"mcp__{server}__{t.tool_name}" for t in self.tools if t.tool_name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "syntax_error": self.syntax_error,
            "imports_sdk": self.imports_sdk,
            "imports_legacy_sdk": self.imports_legacy_sdk,
            "imported_names": self.imported_names,
            "has_build_options": self.has_build_options,
            "option_builders": self.option_builders,
            "options_calls": [c.to_dict() for c in self.options_calls],
            "tools": [t.to_dict() for t in self.tools],
            "sdk_servers": [s.to_dict() for s in self.sdk_servers],
            "functions": [f.to_dict() for f in self.functions],
            "query_calls": [q.to_dict() for q in self.query_calls],
            "secrets": [s.to_dict() for s in self.secrets],
            "model_refs": [m.to_dict() for m in self.model_refs],
            "deprecated_options": self.deprecated_options,
        }


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------

def _hook_returns(node: ast.AST) -> list[ast.Dict]:
    """Dict literals returned by this function, not by nested functions."""
    found: list[ast.Dict] = []

    def walk(current: ast.AST) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                found.append(child.value)
            walk(child)

    walk(node)
    return found


def _dict_get(node: ast.Dict, key: str) -> ast.AST | None:
    for key_node, value_node in zip(node.keys, node.values):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            return value_node
    return None


def _dict_keys(node: ast.Dict) -> list[str]:
    return [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]


def _function_facts(node: ast.FunctionDef | ast.AsyncFunctionDef, path: str) -> FunctionFacts:
    args = node.args
    params = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg:
        params.append("*" + args.vararg.arg)
    if args.kwarg:
        params.append("**" + args.kwarg.arg)
    facts = FunctionFacts(
        name=node.name, lineno=node.lineno,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        params=params,
        decorators=[d for d in (_decorator_name(d) for d in node.decorator_list) if d],
        path=path,
    )
    facts.builds_options = any(
        _call_name(inner) in OPTIONS_CALLS
        for inner in ast.walk(node) if isinstance(inner, ast.Call)
    )
    for returned in _hook_returns(node):
        facts.returns_dict = True
        keys = _dict_keys(returned)
        keys = _dict_keys(returned)
        if returned.keys:
            facts.returns_nonempty_dict = True
            if any(key not in HOOK_COMMON_KEYS for key in keys) or not keys:
                # Nothing the SDK reads. A dict of only common fields is fine.
                facts.returns_unrecognised_dict = True
        else:
            facts.returns_empty_dict = True
        if "async_" in keys or "async" in keys:
            facts.returns_async_ack = True
        specific = _dict_get(returned, "hookSpecificOutput")
        if isinstance(specific, ast.Dict):
            facts.has_hook_specific_output = True
            event = _literal_or_none(_dict_get(specific, "hookEventName"))
            if isinstance(event, str) and event not in facts.hook_event_names:
                facts.hook_event_names.append(event)
            decision = _literal_or_none(_dict_get(specific, "permissionDecision"))
            if isinstance(decision, str):
                facts.permission_decisions.append(decision)
                if decision == "deny":
                    reason = _dict_get(specific, "permissionDecisionReason")
                    literal_reason = _literal_or_none(reason)
                    empty = reason is None or (isinstance(literal_reason, str) and not literal_reason.strip())
                    if empty:
                        facts.deny_without_reason = True
        elif specific is not None:
            facts.has_hook_specific_output = True
        if _literal_or_none(_dict_get(returned, "decision")) == "block":
            facts.permission_decisions.append("block")
    return facts


def _tool_def(node: ast.FunctionDef | ast.AsyncFunctionDef, path: str) -> ToolDef | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or _call_name(decorator) != TOOL_DECORATOR:
            continue
        positional = list(decorator.args)
        by_name = {k.arg: k.value for k in decorator.keywords if k.arg}
        name_node = positional[0] if positional else by_name.get("name")
        desc_node = positional[1] if len(positional) > 1 else by_name.get("description")
        schema_node = positional[2] if len(positional) > 2 else by_name.get("input_schema")
        tool = ToolDef(
            tool_name=_literal_or_none(name_node) if name_node is not None else None,
            func_name=node.name, lineno=node.lineno,
            description=_literal_or_none(desc_node) if desc_node is not None else None,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            path=path,
        )
        if schema_node is None:
            tool.schema_kind = "missing"
        elif isinstance(schema_node, ast.Dict):
            keys = _dict_keys(schema_node)
            tool.schema_keys = keys
            if "properties" in keys or "type" in keys:
                tool.schema_kind = "json_schema"
                properties = _dict_get(schema_node, "properties")
                if isinstance(properties, ast.Dict):
                    tool.schema_keys = _dict_keys(properties)
            else:
                tool.schema_kind = "types"
                for key_node, value_node in zip(schema_node.keys, schema_node.values):
                    key = _literal_or_none(key_node)
                    if isinstance(key, str):
                        tool.schema_types[key] = _unparse(value_node)
        elif isinstance(schema_node, ast.Name):
            tool.schema_kind = "typeddict"
            tool.schema_keys = [schema_node.id]
        else:
            tool.schema_kind = "dynamic"
        return tool
    return None


def _mcp_servers(node: ast.AST, sdk_server_vars: dict[str, str]) -> tuple[list[McpServerRef], bool]:
    """Unpack the `mcp_servers` value into one record per server key."""
    if not isinstance(node, ast.Dict):
        return [], True
    servers: list[McpServerRef] = []
    for key_node, value_node in zip(node.keys, node.values):
        key = _literal_or_none(key_node)
        if not isinstance(key, str):
            servers.append(McpServerRef(key=_unparse(key_node), kind="dynamic",
                                        expr=_unparse(value_node), lineno=getattr(node, "lineno", 0)))
            continue
        ref = McpServerRef(key=key, lineno=getattr(value_node, "lineno", 0), expr=_unparse(value_node))
        if isinstance(value_node, ast.Dict):
            command = _literal_or_none(_dict_get(value_node, "command"))
            url = _literal_or_none(_dict_get(value_node, "url"))
            declared = _literal_or_none(_dict_get(value_node, "type"))
            args = _literal_or_none(_dict_get(value_node, "args")) or []
            ref.command = command if isinstance(command, str) else None
            ref.url = url if isinstance(url, str) else None
            ref.args = [a for a in args if isinstance(a, str)] if isinstance(args, list) else []
            if isinstance(declared, str) and declared in ("stdio", "http", "sse", "streamable-http", "sdk"):
                ref.kind = "http" if declared == "streamable-http" else declared
            elif ref.command:
                ref.kind = "stdio"
            elif ref.url:
                ref.kind = "http"
        elif isinstance(value_node, ast.Name) and value_node.id in sdk_server_vars:
            ref.kind = "sdk"
        elif _call_name(value_node) == SERVER_FACTORY:
            ref.kind = "sdk"
        else:
            ref.kind = "dynamic"
        servers.append(ref)
    return servers, False


def _hook_registrations(node: ast.AST) -> tuple[list[HookRegistration], bool]:
    if not isinstance(node, ast.Dict):
        return [], True
    registrations: list[HookRegistration] = []
    dynamic = False
    for key_node, value_node in zip(node.keys, node.values):
        event = _literal_or_none(key_node)
        if not isinstance(event, str):
            dynamic = True
            continue
        matchers = value_node.elts if isinstance(value_node, (ast.List, ast.Tuple)) else [value_node]
        if not isinstance(value_node, (ast.List, ast.Tuple)):
            dynamic = True
        for matcher_node in matchers:
            registration = HookRegistration(event=event, lineno=getattr(matcher_node, "lineno", 0))
            matcher_value: ast.AST | None = None
            hooks_value: ast.AST | None = None
            if _call_name(matcher_node) == HOOK_MATCHER_CALL and isinstance(matcher_node, ast.Call):
                positional = list(matcher_node.args)
                by_name = {k.arg: k.value for k in matcher_node.keywords if k.arg}
                matcher_value = positional[0] if positional else by_name.get("matcher")
                hooks_value = positional[1] if len(positional) > 1 else by_name.get("hooks")
                timeout = _literal_or_none(by_name.get("timeout"))
                registration.timeout = timeout if isinstance(timeout, (int, float)) else None
            elif isinstance(matcher_node, ast.Dict):
                registration.uses_hook_matcher = False
                matcher_value = _dict_get(matcher_node, "matcher")
                hooks_value = _dict_get(matcher_node, "hooks")
            else:
                registration.uses_hook_matcher = False
                dynamic = True
            if matcher_value is not None:
                literal = _literal_or_none(matcher_value)
                if isinstance(literal, str):
                    registration.matcher = literal
                    try:
                        re.compile(literal)
                    except re.error as exc:
                        registration.matcher_regex_error = str(exc)
                elif literal is None and not isinstance(matcher_value, ast.Constant):
                    registration.matcher_dynamic = True
            if isinstance(hooks_value, (ast.List, ast.Tuple)):
                for callback in hooks_value.elts:
                    if isinstance(callback, ast.Name):
                        registration.callbacks.append(callback.id)
                    elif isinstance(callback, ast.Attribute):
                        registration.callbacks.append(callback.attr)
                    else:
                        registration.callbacks.append(_unparse(callback))
            elif hooks_value is not None:
                registration.callbacks.append(_unparse(hooks_value))
            registrations.append(registration)
    return registrations, dynamic


def _agent_defs(node: ast.AST) -> tuple[list[AgentDef], bool]:
    if not isinstance(node, ast.Dict):
        return [], True
    agents: list[AgentDef] = []
    dynamic = False
    for key_node, value_node in zip(node.keys, node.values):
        name = _literal_or_none(key_node)
        if not isinstance(name, str):
            dynamic = True
            continue
        definition = AgentDef(name=name, lineno=getattr(value_node, "lineno", 0))
        by_name: dict[str, ast.AST] = {}
        if isinstance(value_node, ast.Call) and _call_name(value_node) == AGENT_DEFINITION_CALL:
            by_name = {k.arg: k.value for k in value_node.keywords if k.arg}
        elif isinstance(value_node, ast.Dict):
            definition.call = "dict"
            by_name = {
                k.value: v for k, v in zip(value_node.keys, value_node.values)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
        else:
            definition.call = "dynamic"
            dynamic = True
        definition.keys = sorted(by_name)
        if "tools" in by_name:
            definition.tools = resolve(by_name["tools"])
        for turns_key in ("maxTurns", "max_turns"):
            if turns_key in by_name:
                definition.max_turns = resolve(by_name[turns_key])
                break
        if "model" in by_name:
            definition.model = resolve(by_name["model"])
        definition.description = bool(_literal_or_none(by_name.get("description")))
        definition.prompt = "prompt" in by_name
        agents.append(definition)
    return agents, dynamic


def _system_prompt(node: ast.AST) -> tuple[str, bool]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "string", False
    if isinstance(node, ast.JoinedStr):
        return "string", False
    if isinstance(node, ast.BinOp):
        return "string", False
    if isinstance(node, ast.Dict):
        declared = _literal_or_none(_dict_get(node, "type"))
        append = _dict_get(node, "append") is not None
        if declared in ("preset", "custom", "file"):
            return str(declared), append
        return "dynamic", append
    if isinstance(node, ast.Name):
        return "dynamic", False
    return "dynamic", False


def _output_format(node: ast.AST) -> OutputFormat:
    record = OutputFormat(lineno=getattr(node, "lineno", 0))
    if not isinstance(node, ast.Dict):
        record.dynamic = True
        return record
    declared = _literal_or_none(_dict_get(node, "type"))
    record.type_value = declared if isinstance(declared, str) else None
    schema = _dict_get(node, "schema")
    record.has_schema = schema is not None
    record.schema_is_dict = isinstance(schema, ast.Dict) or isinstance(_literal_or_none(schema), dict)
    if schema is not None and not record.schema_is_dict and isinstance(schema, ast.Name):
        # A schema held in a module constant is still a dict; look no further,
        # but do not claim it is malformed.
        record.schema_is_dict = True
        record.dynamic = True
    return record


def extract_module(path: Path | str) -> ModuleFacts:
    """Read one Python file. Returns partial facts on a syntax error."""
    file = Path(path)
    facts = ModuleFacts(path=str(file))
    try:
        source = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        facts.syntax_error = f"could not read: {exc}"
        return facts
    try:
        tree = ast.parse(source, filename=str(file))
    except (SyntaxError, ValueError) as exc:
        facts.syntax_error = str(exc)
        return facts

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "claude_agent_sdk":
                    facts.imports_sdk = True
                elif root == "claude_code_sdk":
                    facts.imports_legacy_sdk = True
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root == "claude_agent_sdk":
                facts.imports_sdk = True
            elif root == "claude_code_sdk":
                facts.imports_legacy_sdk = True
            if root in ("claude_agent_sdk", "claude_code_sdk"):
                facts.imported_names.extend(a.name for a in node.names)
    facts.imported_names = sorted(set(facts.imported_names))

    # Functions first: hook callbacks and tools are referenced by name later.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts.functions.append(_function_facts(node, str(file)))
            tool = _tool_def(node, str(file))
            if tool is not None:
                facts.tools.append(tool)

    sdk_server_vars: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != SERVER_FACTORY:
            continue
        positional = list(node.args)
        by_name = {k.arg: k.value for k in node.keywords if k.arg}
        name = _literal_or_none(positional[0] if positional else by_name.get("name"))
        version = _literal_or_none(by_name.get("version"))
        tools_node = by_name.get("tools")
        if tools_node is None and len(positional) > 2:
            tools_node = positional[2]
        refs: list[str] = []
        if isinstance(tools_node, (ast.List, ast.Tuple)):
            for element in tools_node.elts:
                if isinstance(element, ast.Name):
                    refs.append(element.id)
                elif isinstance(element, ast.Attribute):
                    refs.append(element.attr)
                else:
                    refs.append(_unparse(element))
        server = SdkServer(
            name=name if isinstance(name, str) else None, lineno=node.lineno,
            version=version if isinstance(version, str) else None,
            tool_refs=refs, path=str(file),
        )
        facts.sdk_servers.append(server)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _call_name(node.value) == SERVER_FACTORY:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    sdk_server_vars[target.id] = target.id
                    for server in facts.sdk_servers:
                        if server.lineno == getattr(node.value, "lineno", -1):
                            server.assigned_to = target.id

    facts.options_calls = _options_calls(tree, str(file), sdk_server_vars)
    facts.query_calls = _query_calls(tree, str(file))
    facts.secrets = _secret_literals(tree, str(file))
    facts.model_refs = _model_refs(tree, facts, str(file))
    facts.deprecated_options = sorted({
        name for call in facts.options_calls for name in call.kwargs
        if name in ("max_thinking_tokens", "debug_stderr")
    })
    return facts


def _module_constants(tree: ast.AST) -> dict[str, ast.AST]:
    """Module-level ``NAME = <expr>`` bindings, so `system_prompt=SYSTEM_PROMPT`
    can be graded as the string it is rather than written off as computed."""
    constants: dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    constants[target.id] = node.value
    return constants


def _deref(node: ast.AST | None, constants: dict[str, ast.AST]) -> ast.AST | None:
    """Follow one level of module-constant indirection."""
    seen = 0
    while isinstance(node, ast.Name) and node.id in constants and seen < 4:
        node = constants[node.id]
        seen += 1
    return node


def _options_calls(tree: ast.AST, path: str, sdk_server_vars: dict[str, str]) -> list[OptionsCall]:
    """Every options construction, with the function that encloses it."""
    calls: list[OptionsCall] = []
    constants = _module_constants(tree)

    def visit(node: ast.AST, function: str | None, in_main: bool, in_dunder_main: bool) -> None:
        for child in ast.iter_child_nodes(node):
            next_function, next_main = function, in_main
            next_dunder = in_dunder_main
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                next_function = child.name
                next_main = child.name in MAIN_NAMES
            elif isinstance(child, ast.If) and _is_dunder_main(child):
                next_dunder = True
            elif isinstance(child, ast.Call) and _call_name(child) in OPTIONS_CALLS:
                calls.append(_one_options_call(
                    child, path, function, in_main or (in_dunder_main and function is None),
                    sdk_server_vars, constants,
                ))
            visit(child, next_function, next_main, next_dunder)

    visit(tree, None, False, False)
    return calls


def _is_dunder_main(node: ast.If) -> bool:
    test = node.test
    return isinstance(test, ast.Compare) and _unparse(test.left) == "__name__"


def _one_options_call(
    node: ast.Call, path: str, function: str | None, in_main: bool,
    sdk_server_vars: dict[str, str], constants: dict[str, ast.AST] | None = None,
) -> OptionsCall:
    call = OptionsCall(
        call=_call_name(node) or OPTIONS_CALL, lineno=node.lineno, path=path,
        function=function, in_main=in_main,
        in_build_options=function == BUILD_OPTIONS,
    )
    for keyword in node.keywords:
        if keyword.arg is None:
            call.unpacked.append(_unparse(keyword.value))
            continue
        value_node = _deref(keyword.value, constants or {}) or keyword.value
        call.kwargs[keyword.arg] = resolve(value_node)
        if keyword.arg == "mcp_servers":
            call.mcp_servers, call.mcp_servers_dynamic = _mcp_servers(value_node, sdk_server_vars)
        elif keyword.arg == "hooks":
            call.hooks, call.hooks_dynamic = _hook_registrations(value_node)
        elif keyword.arg == "agents":
            call.agents, call.agents_dynamic = _agent_defs(value_node)
        elif keyword.arg == "system_prompt":
            call.system_prompt_kind, call.system_prompt_append = _system_prompt(value_node)
        elif keyword.arg == "output_format":
            call.output_format = _output_format(value_node)
    return call


def _query_calls(tree: ast.AST, path: str) -> list[QueryCall]:
    calls: list[QueryCall] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in (QUERY_CALL, CLIENT_CALL):
            continue
        # `client.query(prompt)` is a method on an already-configured session,
        # not the module-level `query()` that takes options. Only the bare name
        # is the one that can be called without any.
        if not isinstance(node.func, ast.Name):
            continue
        by_name = {k.arg: k.value for k in node.keywords if k.arg}
        options_node = by_name.get("options")
        if options_node is None and name == CLIENT_CALL and node.args:
            options_node = node.args[0]
        calls.append(QueryCall(
            call=name, lineno=node.lineno, path=path,
            has_options=options_node is not None,
            options_expr=_unparse(options_node) if options_node is not None else None,
        ))
    return calls


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in SECRET_PLACEHOLDERS:
        return True
    return lowered.startswith(("${", "$", "<", "your_", "your-", "example", "dummy", "fake"))


def _secret_literals(tree: ast.AST, path: str) -> list[SecretLiteral]:
    found: list[SecretLiteral] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(prefix in node.value for prefix in SECRET_PREFIXES):
                found.append(SecretLiteral(
                    kind="api_key_prefix", lineno=node.lineno, path=path,
                    preview=node.value[:12] + "…",
                ))
    for node in ast.walk(tree):
        pairs: list[tuple[str, ast.AST]] = []
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    pairs.append((target.id, node.value))
        elif isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                key = _literal_or_none(key_node)
                if isinstance(key, str):
                    pairs.append((key, value_node))
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg:
                    pairs.append((keyword.arg, keyword.value))
        for name, value_node in pairs:
            if name.upper() not in SECRET_NAMES:
                continue
            literal = _literal_or_none(value_node)
            if not isinstance(literal, str) or _looks_like_placeholder(literal):
                continue
            if any(existing.lineno == getattr(value_node, "lineno", 0)
                   and existing.kind == "api_key_prefix" for existing in found):
                continue
            found.append(SecretLiteral(
                kind="named_assignment", lineno=getattr(value_node, "lineno", 0),
                name=name, path=path, preview=literal[:6] + "…",
            ))
    return sorted(found, key=lambda s: (s.lineno, s.kind))


def _collect_model(value: Value, lineno: int, where: str, path: str) -> list[ModelRef]:
    refs: list[ModelRef] = []
    text = value.as_str()
    if isinstance(text, str) and text:
        refs.append(ModelRef(value=text, lineno=lineno, where=where,
                             env_var=value.env_var, path=path))
    elif value.is_env and value.value is None:
        refs.append(ModelRef(value="", lineno=lineno, where="env_default",
                             env_var=value.env_var, path=path))
    return refs


def _model_refs(tree: ast.AST, facts: ModuleFacts, path: str) -> list[ModelRef]:
    refs: list[ModelRef] = []
    seen: set[tuple[str, int, str]] = set()

    def add(ref: ModelRef) -> None:
        key = (ref.value, ref.lineno, ref.where)
        if key not in seen:
            seen.add(key)
            refs.append(ref)

    for call in facts.options_calls:
        for name in ("model", "fallback_model"):
            value = call.kwargs.get(name)
            if value is not None:
                for ref in _collect_model(value, call.lineno, "options", path):
                    add(ref)
        for definition in call.agents:
            if definition.model is not None:
                for ref in _collect_model(definition.model, definition.lineno, "agent", path):
                    add(ref)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _MODEL_RE.match(node.value.strip()):
                add(ModelRef(value=node.value.strip(), lineno=node.lineno,
                             where="literal", path=path))
    return refs


# ---------------------------------------------------------------------------
# project facts
# ---------------------------------------------------------------------------

@dataclass
class ProjectFacts:
    """Every agent module in a project, plus the aggregates checks need."""

    root: str
    modules: list[ModuleFacts] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # -- aggregates ---------------------------------------------------
    @property
    def options_calls(self) -> list[OptionsCall]:
        return [call for module in self.modules for call in module.options_calls]

    @property
    def primary(self) -> OptionsCall | None:
        """The options call a reviewer should judge the agent by.

        Preference: inside ``build_options()`` (the convention an eval runner
        loads), then any other named builder, then module level, then whatever
        exists. A project whose only construction is inside ``main()`` has no
        injectable options at all, which is itself a finding.
        """
        calls = self.options_calls
        if not calls:
            return None
        for predicate in (
            lambda c: c.in_build_options,
            lambda c: c.function is not None and not c.in_main,
            lambda c: c.function is None,
        ):
            matches = [c for c in calls if predicate(c)]
            if matches:
                return matches[0]
        return calls[0]

    @property
    def tools(self) -> list[ToolDef]:
        return [tool for module in self.modules for tool in module.tools]

    @property
    def sdk_servers(self) -> list[SdkServer]:
        return [server for module in self.modules for server in module.sdk_servers]

    @property
    def mcp_servers(self) -> list[McpServerRef]:
        return [server for call in self.options_calls for server in call.mcp_servers]

    @property
    def server_names(self) -> list[str]:
        names = {s.key for s in self.mcp_servers}
        names.update(s.name for s in self.sdk_servers if s.name)
        return sorted(names)

    @property
    def hooks(self) -> list[HookRegistration]:
        return [hook for call in self.options_calls for hook in call.hooks]

    @property
    def agents(self) -> list[AgentDef]:
        return [agent for call in self.options_calls for agent in call.agents]

    @property
    def secrets(self) -> list[SecretLiteral]:
        return [secret for module in self.modules for secret in module.secrets]

    @property
    def model_refs(self) -> list[ModelRef]:
        return [ref for module in self.modules for ref in module.model_refs]

    @property
    def query_calls(self) -> list[QueryCall]:
        return [call for module in self.modules for call in module.query_calls]

    @property
    def legacy_modules(self) -> list[str]:
        return [m.path for m in self.modules if m.imports_legacy_sdk] + [
            c.path or "" for c in self.options_calls if c.legacy
        ]

    @property
    def has_build_options(self) -> bool:
        return any(m.has_build_options for m in self.modules)

    @property
    def agent_module_count(self) -> int:
        return len(self.modules)

    def function(self, name: str) -> FunctionFacts | None:
        for module in self.modules:
            found = module.function(name)
            if found is not None:
                return found
        return None

    def tool_names(self) -> list[str]:
        """The `mcp__server__tool` names the model would actually see."""
        by_func = {tool.func_name: tool for tool in self.tools}
        names: list[str] = []
        for server in self.sdk_servers:
            if not server.name:
                continue
            for ref in server.tool_refs:
                tool = by_func.get(ref)
                if tool and tool.tool_name:
                    names.append(f"mcp__{server.name}__{tool.tool_name}")
        return sorted(set(names))

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "scanned": self.scanned,
            "notes": self.notes,
            "modules": [m.to_dict() for m in self.modules],
            "summary": {
                "agent_modules": self.agent_module_count,
                "options_calls": len(self.options_calls),
                "has_build_options": self.has_build_options,
                "primary_options": self.primary.to_dict() if self.primary else None,
                "server_names": self.server_names,
                "tool_names": self.tool_names(),
                "hook_events": sorted({h.event for h in self.hooks}),
                "agent_names": [a.name for a in self.agents],
                "model_ids": sorted({r.value for r in self.model_refs if r.value}),
                "secrets": len(self.secrets),
            },
        }


def extract_project(project_root: Path | str, *, max_depth: int = 4) -> ProjectFacts:
    """Read every module in the project that uses the SDK."""
    root = Path(project_root)
    facts = ProjectFacts(root=str(root.resolve() if root.exists() else root))
    if root.is_file():
        facts.scanned = [str(root)]
        facts.modules = [extract_module(root)]
        return facts
    if not root.is_dir():
        facts.notes.append("target does not exist")
        return facts
    for usage in find_agent_modules(root, max_depth=max_depth):
        facts.scanned.append(usage.path)
        facts.modules.append(extract_module(usage.path))
    if not facts.modules:
        facts.notes.append("no module imports claude_agent_sdk")
    return facts
