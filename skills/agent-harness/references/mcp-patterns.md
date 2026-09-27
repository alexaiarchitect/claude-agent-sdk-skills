# MCP: in-process, stdio, HTTP — and what an eval needs

## The naming rule everything depends on

A tool from an MCP server reaches the model as **`mcp__<server>__<tool>`**,
where `<server>` is the key in the `mcp_servers` dict (or in `.mcp.json`) and
`<tool>` is the name the server advertises. Change the key and every
`allowed_tools` entry, every grader and every trajectory changes with it.

An `mcp__x__` prefix with no server `x` is `MCP001`: an allow rule that can
never match, so the tool it was meant to approve prompts or is denied instead.
Nothing warns at run time.

## Three transports

| Kind | You have | Config |
|---|---|---|
| **in-process** | `@tool` functions in your own code | `create_sdk_mcp_server(name=..., version=..., tools=[...])`, and the returned object goes in `mcp_servers` |
| **stdio** | a command to run | `{"command": "npx", "args": [...], "env": {...}}` |
| **http / sse** | a URL | `{"type": "http" \| "sse", "url": ..., "headers": {...}}` |

In `.mcp.json` and other JSON config, `"streamable-http"` is accepted as an
alias for `"http"`; the SDK's own `McpHttpServerConfig` declares only `"http"`,
so use that in code.

### In-process is the one to prefer

No subprocess, no port, no network, no install — and the handler is ordinary
Python your tests can call directly.

```python
@tool("reserve_book", "Reserve one copy of a title for a member",
      {"title": str, "member_id": str})
async def reserve_book(args: dict[str, Any]) -> dict[str, Any]:
    ...
    return {"content": [{"type": "text", "text": "Reserved Dune for member-42."}]}
```

- `tool(name, description, input_schema)` returns an `SdkMcpTool`. The schema
  may be a `{param: type}` dict, a `TypedDict` class, or a full JSON Schema
  dict; `Annotated[str, "..."]` adds a per-parameter description.
- The handler must be `async`, and returns
  `{"content": [{"type": "text", "text": ...}], "is_error"?: True}`. Content
  items may be `text`, `image` (`data` + `mimeType`), `resource_link` or a text
  `resource`; binary resources and unknown types are **dropped with a warning**.
- Arguments are validated against the schema before the handler runs. An
  invalid input and a raised exception both come back to Claude as an error
  result, and the loop continues — so how you report an error decides what
  Claude reads, not whether the query fails.
- Prefer returning `{"is_error": True}` with a sentence the model can act on
  over raising: an exception's message reaches Claude as raw text.

### Errors and status

`ToolResultBlock.is_error` is `None` on success, not `False` (measured). A
grader must test truthiness, never `is False`. For per-server connection state,
`ClaudeSDKClient.get_mcp_status()` is the source; `get_server_info()` does
**not** carry an `mcp_servers` key.

## Ambient servers, and why `strict_mcp_config` matters

Unless `strict_mcp_config=True`, a session also loads project `.mcp.json`, user
settings, plugin-provided servers and claude.ai connectors. Measured on the
build machine, a run with `setting_sources=[]` still had the managed
`claude.ai Claude Docs` MCP server attached; only `strict_mcp_config=True`
dropped it.

For an eval that means: **the agent's tool surface depends on the machine**
until you set it. Set both.

`tools=["Read"]` does not help here — measured, the init message listed `Read`
plus every `mcp__claude_ai_Claude_Docs__*` tool. `tools` governs built-ins only.

## Permission still applies

MCP tools need approval like any other. `acceptEdits` does **not** auto-approve
them. `bypassPermissions` does, but approves nearly everything else too. The
proportionate answer is a glob in `allowed_tools`:

```python
allowed_tools=["mcp__library__*"]        # one server, every tool
allowed_tools=["mcp__library__lookup"]   # one tool
```

A glob is only honoured after a literal, glob-free server segment.

## Mocks, for evals

An eval that calls a real external server is testing the server. Replace it:

- the runner substitutes any server named in a case's `mocks` list with an
  in-process server built from `evals/mocks/<server>/<tool>.md`, so the tool
  **names stay identical** (`mcp__library__reserve` is still
  `mcp__library__reserve`) and a trajectory grader written against the real
  agent keeps working;
- one file per tool, carrying the schema it advertises, an optional `expect`
  guard on the input, a canned result body, and optional `error` and
  `latency_ms`;
- because the names are unchanged, a mock for a server the agent no longer has
  is a finding (`MCP020` in the simulation skill), not a silent no-op.

Deriving the mocks is mechanical: for in-process servers the `@tool` schemas are
readable statically; for external servers the runner's `list-tools` subcommand
asks the server.

## Discovering what a server actually publishes

The `SystemMessage(subtype="init")` event lists the session's tools, including
`mcp__` names, but only for servers that connected in time or had a cached tool
list. A server that has not connected is simply absent from that list — read
`get_mcp_status()` rather than concluding the tools do not exist.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/mcp> (naming, transports,
allowing tools, connection timing, error handling),
<https://code.claude.com/docs/en/agent-sdk/custom-tools> (the `@tool`
contract, content types, error handling);
`claude-agent-sdk` 0.2.162 `__init__.py:241` (`SdkMcpTool`), `:251` (`tool`),
`:451-489` (content-item handling), `:491` (`create_sdk_mcp_server`),
`types.py:979` (`ToolResultBlock`), `:2010` (`mcp_servers`), `:2018`
(`strict_mcp_config`), `client.py:471` (`get_mcp_status`), `:540`
(`get_server_info`); this plugin's `.dev/CONTRACTS.md` §2 for the mock format.
The `is_error is None`, ambient-connector and `tools=["Read"]` observations were
measured by this plugin on 2026-09-30.
