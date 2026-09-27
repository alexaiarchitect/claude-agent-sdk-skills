"""In-process MCP servers built from `evals/mocks/<server>/<tool>.md`.

A mock replaces one entry of the agent's `mcp_servers` with a deterministic
`create_sdk_mcp_server(...)`, so a case can assert on behaviour without a network
or a database. What a mock may return is narrower than it looks: only `text` and
`image` content items survive intact, `resource_link` and text `resource` are
flattened to text, and binary resources and unknown types are dropped with a
warning — so a mock emits text, and nothing else.

Input is validated against the declared `schema` *before* the handler runs, and
both a schema violation and a raised exception reach Claude as an error result.
A mock therefore cannot observe malformed input unless its schema is permissive
— which is why `expect` exists: it is the runner's own guard, checked inside the
handler, and a failed expectation is recorded as a mock call with an error.

`mock_calls` is recorded by this wrapper. The SDK records nothing about
in-process tools, so without this there is no evidence a mock was ever reached.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import EvalError
from . import frontmatter

_INPUT_REF = re.compile(r"\{\{\s*input\.([\w.]+)\s*(?:\|\s*([^}]*?))?\s*\}\}")
_FILE_REF = re.compile(r"\{\{\s*file\s*:\s*([^}]+?)\s*\}\}")

MOCK_KEYS = frozenset({"name", "description", "schema", "expect", "error", "latency_ms", "type"})


@dataclass
class MockTool:
    server: str
    name: str
    description: str
    schema: dict[str, Any]
    body: str
    expect: dict[str, Any] = field(default_factory=dict)
    error: Any = None
    latency_ms: int = 0
    kind: str = "canned"
    path: Path | None = None

    @property
    def qualified(self) -> str:
        return f"mcp__{self.server}__{self.name}"


def substitute(body: str, inputs: dict[str, Any], base_dir: Path) -> str:
    """Expand `{{input.x}}`, `{{input.x|fallback}}` and `{{file:fixtures/…}}`."""
    def _input(match: re.Match[str]) -> str:
        dotted, fallback = match.group(1), match.group(2)
        value: Any = inputs
        for part in dotted.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            return fallback if fallback is not None else ""
        return value if isinstance(value, str) else json.dumps(value, default=str)

    def _file(match: re.Match[str]) -> str:
        relative = match.group(1).strip()
        try:
            return (base_dir / relative).read_text(encoding="utf-8")
        except OSError:
            return f"<<missing mock fixture {relative}>>"

    return _INPUT_REF.sub(_input, _FILE_REF.sub(_file, body))


def _default_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict) and schema:
        return schema
    # A permissive schema is the only way a mock can observe malformed input.
    return {"type": "object", "additionalProperties": True}


def load_mock_tools(evals_dir: Path, server: str) -> list[MockTool]:
    root = Path(evals_dir) / "mocks" / server
    if not root.is_dir():
        raise EvalError(f"no mock server directory at {root}", code="MCP020")
    tools: list[MockTool] = []
    for path in sorted(root.glob("*.md")):
        try:
            doc = frontmatter.parse(path.read_text(encoding="utf-8"))
        except (OSError, frontmatter.FrontmatterError) as exc:
            raise EvalError(f"{path}: {exc}", code="MCP010") from exc
        meta = doc.meta or {}
        unknown = sorted(set(meta) - MOCK_KEYS)
        if unknown:
            raise EvalError(f"{path}: unknown mock key(s) {', '.join(unknown)}", code="MCP010")
        tools.append(MockTool(
            server=server,
            name=str(meta.get("name") or path.stem),
            description=str(meta.get("description") or f"mock {path.stem} for {server}"),
            schema=_default_schema(meta.get("schema")),
            body=doc.body,
            expect=dict(meta.get("expect") or {}),
            error=meta.get("error"),
            latency_ms=int(meta.get("latency_ms") or 0),
            kind=str(meta.get("type") or "canned"),
            path=path,
        ))
    if not tools:
        raise EvalError(f"{root}: no <tool>.md files", code="MCP010")
    return tools


class MockRecorder:
    """Collects `mock_calls` for the graders and the trace."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, tool: MockTool, inputs: dict[str, Any], output: str, *, is_error: bool,
               note: str = "") -> dict[str, Any]:
        entry = {
            "tool": tool.qualified,
            "server": tool.server,
            "name": tool.name,
            "input": inputs,
            "output_chars": len(output),
            "output": output[:2048],
            "is_error": is_error,
        }
        if note:
            entry["note"] = note
        self.calls.append(entry)
        return entry


def build_handler(mock: MockTool, recorder: MockRecorder, base_dir: Path):
    """The async handler `tool()` wraps. Returns the SDK's result shape."""

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        inputs = dict(args or {})
        if mock.latency_ms:
            await asyncio.sleep(mock.latency_ms / 1000.0)
        unmet = [
            f"{key}={inputs.get(key)!r} (expected {value!r})"
            for key, value in (mock.expect or {}).items()
            if inputs.get(key) != value
        ]
        if unmet:
            text = f"mock {mock.name}: unmet expectation(s): " + "; ".join(unmet)
            recorder.record(mock, inputs, text, is_error=True, note="expect")
            return {"content": [{"type": "text", "text": text}], "is_error": True}
        if mock.error:
            text = str(mock.error)
            recorder.record(mock, inputs, text, is_error=True, note="error")
            return {"content": [{"type": "text", "text": text}], "is_error": True}
        text = substitute(mock.body, inputs, base_dir).strip()
        recorder.record(mock, inputs, text, is_error=False)
        return {"content": [{"type": "text", "text": text}]}

    return handler


def build_servers(evals_dir: Path, names: list[str], recorder: MockRecorder, sdk: Any) -> dict[str, Any]:
    """`{server name: McpSdkServerConfig}` for every named mock server."""
    servers: dict[str, Any] = {}
    for server in names:
        mocks = load_mock_tools(evals_dir, server)
        built = []
        for mock in mocks:
            decorator = sdk.tool(mock.name, mock.description, mock.schema)
            built.append(decorator(build_handler(mock, recorder, mock.path.parent if mock.path else Path("."))))
        servers[server] = sdk.create_sdk_mcp_server(name=server, version="1.0.0", tools=built)
    return servers


def mock_tool_names(evals_dir: Path, names: list[str]) -> list[str]:
    return [mock.qualified for server in names for mock in load_mock_tools(evals_dir, server)]
