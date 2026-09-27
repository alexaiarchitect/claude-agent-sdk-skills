"""Mock MCP tools: `evals/mocks/<server>/<tool>.md`, one file per tool.

A mock replaces one in-process MCP server with a deterministic one, so a case can
assert on behaviour instead of on whatever a real backend happened to return
today. The runner builds it with `create_sdk_mcp_server(name=<server>, ...)` and
one `tool(name, description, input_schema)` per file, which means the directory
name *is* the server name and the file stem *is* the tool name. The model sees
them as `mcp__<server>__<tool>`.

Frontmatter:

===============  ==========================================================
`schema`         the input schema the server advertises — **required**
`expect`         an input guard: keys the call must carry to get the body
`error`          return an error result instead of the body
`latency_ms`     sleep before answering, to shake out timeout assumptions
`type`           `canned` (default) or `agent`
`description`    what the tool does, as the model will read it
===============  ==========================================================

The body is the canned result, with `{{input.x}}` and `{{file:fixtures/…}}`
substitution. It reaches Claude as
`{"content": [{"type": "text", "text": ...}], "is_error": True?}`.

Two measured constraints shape what a mock may say:

* **Input is validated against `schema` before the handler runs.** A schema
  violation and a raised exception both reach Claude as an error result, so a
  mock cannot observe malformed input unless its `schema` is permissive. If a
  case is *about* bad input, the mock needs a loose schema and an `expect` guard.
* **Only `text` and `image` content survives intact.** `resource_link` and text
  `resource` items are flattened to text; binary resources and unknown types are
  **dropped with a warning**. A mock that returns them returns nothing.

Findings: ``SIM010`` no `schema`, ``SIM011`` both `error` and a body,
``SIM012`` `latency_ms` not a non-negative number, ``SIM013`` unknown `type`,
``MCP020`` a mock for a server the agent does not have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import frontmatter
from .report import Finding

_SRC_MCP = "claude_agent_sdk __init__.py:451-489 create_sdk_mcp_server / tool result handling"
_SRC_FORMAT = "this plugin's mock format (CONTRACTS §4)"

MOCK_TYPES = ("canned", "agent")
MOCKS_DIR = "mocks"

#: `{{input.title}}` / `{{file:fixtures/catalog.json}}`
SUBSTITUTION = re.compile(r"\{\{\s*(input\.[A-Za-z_][A-Za-z0-9_.]*|file:[^}]+)\s*\}\}")


@dataclass
class LoadedMock:
    """One mock tool file, parsed."""

    path: str
    server: str
    tool: str
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        """The name the model sees."""
        return f"mcp__{self.server}__{self.tool}"

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def substitutions(self) -> list[str]:
        return SUBSTITUTION.findall(self.body)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "server": self.server, "tool": self.tool,
            "qualified_name": self.qualified_name, "meta": self.meta,
            "body_chars": len(self.body), "substitutions": self.substitutions,
            "errors": self.errors,
        }


def load_mock(path: Path | str) -> LoadedMock:
    """Parse one `evals/mocks/<server>/<tool>.md`.

    The server and tool names come from the path, not the frontmatter: the
    runner builds the server from the directory, so a `name:` key that disagreed
    with the filename would be a second source of truth that nothing reads.
    """
    file = Path(path)
    mock = LoadedMock(path=str(file), server=file.parent.name, tool=file.stem)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        mock.errors.append(f"unreadable: {exc}")
        return mock
    try:
        document = frontmatter.parse(text)
    except frontmatter.FrontmatterError as exc:
        mock.errors.append(str(exc))
        return mock
    if not document.has_frontmatter:
        mock.errors.append("no frontmatter: a mock needs at least a `schema`")
    mock.meta = document.meta
    mock.body = document.body
    return mock


def iter_mocks(evals_dir: Path | str) -> Iterator[LoadedMock]:
    """Every mock under `evals/mocks/`, server by server, tool by tool."""
    root = Path(evals_dir) / MOCKS_DIR
    if not root.is_dir():
        return
    for server_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for file in sorted(server_dir.glob("*.md")):
            yield load_mock(file)


def mocks_by_server(evals_dir: Path | str) -> dict[str, list[LoadedMock]]:
    """Mocks grouped by the server they belong to."""
    grouped: dict[str, list[LoadedMock]] = {}
    for mock in iter_mocks(evals_dir):
        grouped.setdefault(mock.server, []).append(mock)
    return grouped


def mock_server_names(evals_dir: Path | str) -> list[str]:
    root = Path(evals_dir) / MOCKS_DIR
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and any(p.glob("*.md")))


def mock_tool_names(evals_dir: Path | str) -> set[str]:
    """Every `mcp__<server>__<tool>` name the mocks provide.

    This is the second half of the tool cross-check: a grader may name a tool
    the agent itself does not expose, as long as a mock does (EVC020).
    """
    return {mock.qualified_name for mock in iter_mocks(evals_dir)}


def validate_mock(
    mock: LoadedMock,
    *,
    agent_servers: set[str] | None = None,
) -> list[Finding]:
    """Findings for one mock file.

    `agent_servers` is the set of MCP server names the agent actually builds,
    read statically from its source. Pass it only when it was determined — an
    empty set and "not determined" mean different things, and guessing would
    produce MCP020 on every project whose servers we failed to parse.
    """
    out: list[Finding] = []
    where = mock.path

    def add(fid: str, severity: str, message: str, *, fix: str = "",
            source: str = _SRC_FORMAT, locator: str | None = None) -> None:
        out.append(Finding(
            id=fid, severity=severity, area="mock",
            message=f"mock {mock.server}/{mock.tool}: {message}",
            path=where, locator=locator, fix=fix or None, source=source,
        ))

    for error in mock.errors:
        add("SIM010", "error", error, fix="fix the frontmatter; the runner cannot build this tool")
    if mock.errors:
        return out

    meta = mock.meta
    if not meta.get("schema"):
        add("SIM010", "error", "no `schema`",
            fix="add the input schema the server should advertise, e.g. "
                "`schema:\\n  title: str`. Input is validated against it before the "
                "handler runs, so without one the tool accepts nothing.",
            source=_SRC_MCP, locator="schema")
    elif not isinstance(meta.get("schema"), (dict, str)):
        add("SIM010", "error", f"`schema` must be a mapping, got {type(meta['schema']).__name__}",
            locator="schema")

    has_error = meta.get("error") not in (None, False, "")
    if has_error and mock.body.strip():
        add("SIM011", "error", "sets `error` and also has a body",
            fix="an error result replaces the body. Keep the message in `error:` and "
                "delete the body, or drop `error:` and prefix the body yourself.",
            source=_SRC_MCP, locator="error")

    latency = meta.get("latency_ms")
    if latency is not None:
        if isinstance(latency, bool) or not isinstance(latency, (int, float)) or latency < 0:
            add("SIM012", "error", f"`latency_ms` must be a non-negative number, got {latency!r}",
                fix="use milliseconds, e.g. `latency_ms: 250`", locator="latency_ms")

    mock_type = meta.get("type")
    if mock_type is not None and str(mock_type) not in MOCK_TYPES:
        add("SIM013", "error", f"unknown `type` {mock_type!r}",
            fix=f"use one of: {', '.join(MOCK_TYPES)} (`canned` returns the body verbatim; "
                "`agent` renders it through a model call and costs tokens)",
            locator="type")

    if not has_error and not mock.body.strip():
        add("SIM010", "warn", "no body and no `error`: the tool will return empty text",
            fix="write the canned result under the frontmatter, or set `error:`")

    if agent_servers is not None and mock.server not in agent_servers:
        known = ", ".join(sorted(agent_servers)) or "(none found)"
        add("MCP020", "warn", f"the agent has no MCP server named {mock.server!r}",
            fix=f"servers the agent builds: {known}. Rename the directory, or delete the "
                "mock if the server was removed — a mock for a server nobody mounts is "
                "never exercised and silently stops proving anything.",
            source="read from the agent's `mcp_servers` / create_sdk_mcp_server calls")

    out.extend(_check_substitutions(mock))
    return out


def _check_substitutions(mock: LoadedMock) -> list[Finding]:
    """`{{input.x}}` must name a key the schema declares."""
    schema = mock.meta.get("schema")
    if not isinstance(schema, dict):
        return []
    declared = set(schema)
    if "properties" in schema and isinstance(schema["properties"], dict):
        declared |= set(schema["properties"])
    out: list[Finding] = []
    for token in mock.substitutions:
        if not token.startswith("input."):
            continue
        key = token.split(".", 1)[1].split(".", 1)[0]
        if key not in declared:
            out.append(Finding(
                id="SIM010", severity="warn", area="mock",
                message=f"mock {mock.server}/{mock.tool}: body substitutes "
                        f"{{{{{token}}}}} but `schema` does not declare {key!r}",
                path=mock.path, locator="body",
                fix=f"add {key!r} to `schema`, or the substitution renders empty",
                source=_SRC_FORMAT,
            ))
    return out


def validate_mocks(
    evals_dir: Path | str,
    *,
    agent_servers: set[str] | None = None,
) -> list[Finding]:
    """Every mock in a suite, plus suite-level checks."""
    out: list[Finding] = []
    grouped = mocks_by_server(evals_dir)
    for mocks in grouped.values():
        for mock in mocks:
            out.extend(validate_mock(mock, agent_servers=agent_servers))
    return out


def mock_summary(evals_dir: Path | str) -> dict[str, Any]:
    """A short description of a suite's mocks, for a discovery report."""
    grouped = mocks_by_server(evals_dir)
    return {
        "servers": sorted(grouped),
        "tools": {server: sorted(m.tool for m in mocks) for server, mocks in sorted(grouped.items())},
        "tool_names": sorted(mock_tool_names(evals_dir)),
        "count": sum(len(mocks) for mocks in grouped.values()),
    }
