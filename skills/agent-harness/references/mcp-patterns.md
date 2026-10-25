# MCP: in-process, stdio, HTTP — and what an eval needs

## The naming rule everything depends on

A tool from an MCP server reaches the model as **`mcp__<server>__<tool>`**,
where `<server>` is the key in the `mcp_servers` dict (or in `.mcp.json`) with
any `.` or space turned into `_`, and `<tool>` is the name the server
advertises. A plugin's server takes the scoped form `plugin_<plugin>_<server>`. Change the key and every
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

A server declared in a **plugin manifest** also accepts `requestTimeout` — a
positive integer in milliseconds, default **60000**, needing Claude Code
**2.1.288+**. It is a manifest field, not a `ClaudeAgentOptions` one: there is no
per-server timeout among the 49 options, so an SDK-configured server that is slow
has to be wrapped or replaced by a mock instead.

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
- Annotations: `readOnlyHint`/`idempotentHint` decide which HTTP calls are
  retried (2.1.307). `destructiveHint: true` matters to the TypeScript
  `permission_policy: "always_ask"` (TypeScript-only, v0.3.301+): under `auto`
  or `plan` set it explicitly so those calls still reach `canUseTool`, because
  unset counts as `false` there. In Python the hint is advisory; gate a
  destructive tool with `can_use_tool` or a `PreToolUse` hook.

### Writing the tools themselves

Anthropic's tool-writing guidance (2025-09-11) in brief, with the current
mechanics from the docs:

- **Few, deliberate tools.** Search over list (`search_contacts`, not
  `list_contacts`); consolidate a multi-step operation into one tool
  (`schedule_event` instead of list-users + list-events + create-event); give
  each tool one clear purpose — overlapping tools are the commonest failure.
- **Namespace by service and resource** (`library_books_search`,
  `library_loans_create`): the `mcp__<server>__` prefix separates servers, not
  resources within one.
- **Return high-signal fields** (names over opaque UUIDs) and offer a
  `response_format` enum (`"concise"`/`"detailed"`) when IDs are only sometimes
  needed. Claude Code limits MCP output to **25,000 tokens** by default
  (`MAX_MCP_OUTPUT_TOKENS`; text over 50,000 characters is saved to a file), so
  paginate, filter or truncate with defaults, and when you truncate say how to
  narrow the next call.
- **Actionable errors** (what to change, an example of valid input) and
  **unambiguous parameter names** (`user_id`, not `user`).

The code-execution alternative (2025-11-04): present servers as code APIs the
agent calls from scripts, so definitions load on demand and intermediate data
stays out of the window — the article cites one workflow dropping from 150,000
to 2,000 tokens — at the price of running agent-written code in a sandbox with
resource limits and monitoring (`secure-deployment.md`). The SDK's built-in
partial answer is tool search (`ToolSearch`, deferred tool loading). For a design
review of a tool set, `/agent-sdk:agent-design`.

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

A glob is only honoured after a literal, glob-free server segment. From Claude
Code **2.1.299** a rule reaches only the server it names: `mcp__a` no longer
allows a server called `a__b` or `a_`, and a server whose normalised name
contains `__` or ends in `_` must be written in the wildcard form with its whole
name (`mcp__reports__v2__*`). The same release scoped an agent's `tools:` list
to the named server's tools.

Two tools escape the allow list entirely. A tool whose server sets
`requiresUserInteraction`, and a connector tool an organisation has set to `ask`,
always reach the ask step however they are pre-approved — and in `dontAsk` they
are **denied** rather than prompted, because that mode never prompts. An
unattended suite that needs such a tool has to mock it; no allow rule will do.

Two transport details that changed recently. Claude Code trims MCP tool
descriptions and server instructions to **4096** characters (**16384** for a
tool loaded through tool search); `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`
replaces both limits, so a server whose description carries its usage rules
should keep them near the top. And cloud-session and Remote Control connectors
negotiate MCP protocol version **2026-07-28** by default on installs that fetch
no flags (2.1.299; `MCP_PROTOCOL_NEGOTIATION=legacy` opts out); a server that
negotiates it but omits `resultType`, `ttlMs` or `cacheScope` showed no tools
until the 2.1.302 fix. A `"failed"` HTTP or SSE server can now reconnect on its
own in the background.

Fixes since then that an SDK agent can feel (Claude Code 2.1.305–2.1.311):

- a server passed with the SDK's `setMcpServers` (TypeScript; the Python
  client has no such call at 0.2.174) is no longer replaced later in the session
  by a same-named server from the user's settings (2.1.305);
- an HTTP MCP tool call is no longer sent twice when the connection closes
  mid-call: only read-only or idempotent tools are retried (2.1.307), so mark a
  tool's annotations honestly; and a turn no longer starts without an SDK MCP
  server's latest tools while a background task runs (2.1.307);
- a disabled MCP server is no longer reconnected by a later permission prompt in
  print and SDK sessions (2.1.309);
- a call that times out in a non-interactive session while the server's
  elicitation goes unanswered now tells Claude "that no answer came and not to
  repeat the call" (2.1.310) — an unattended agent cannot answer elicitations,
  so mock such a tool rather than wait;
- subagents can use MCP tools from servers that finish connecting after the
  subagent started (2.1.311).

**Skipped servers are reported.** An `--mcp-config` entry that fails config
validation is absent from `mcp_servers` and listed in `mcp_server_errors`
(`name`, `type` such as `unknown_type`/`invalid_config`/`reserved_name`,
`message`) in `-p --output-format json` output — the key is omitted when empty,
so a CI gate can fail on a non-empty array — and in stream-json runs in the
`system/init` event's `mcp_server_errors` field.

A `claude -p` run does not wait for MCP work in the background when it ends: a
remote MCP task goes on (resume the session to follow it), and the result of a
call that automatic backgrounding moved is lost.

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
contract, content types, error handling, annotations, TypeScript-only
`permission_policy` and `destructiveHint`),
<https://code.claude.com/docs/en/mcp> (output limits, `mcp_server_errors` in
`system/init`), <https://code.claude.com/docs/en/headless> (`mcp_server_errors`);
<https://www.anthropic.com/research/writing-tools-for-agents> ("Writing effective
tools for AI agents", 2025-09-11, search over list, consolidation, namespacing,
`response_format`, truncation, actionable errors, parameter names);
<https://www.anthropic.com/research/code-execution-with-mcp> ("Code execution
with MCP for efficient agents", 2025-11-04, the code-API trade-off and its
150,000→2,000-token example);
`claude-agent-sdk` 0.2.174 `__init__.py:267` (`SdkMcpTool`), `:277` (`tool`),
`:477-515` (content-item handling), `:517` (`create_sdk_mcp_server`),
`types.py:1218` (`ToolResultBlock`), `:2365` (`mcp_servers`), `:2373`
(`strict_mcp_config`), `client.py:471` (`get_mcp_status`), `:540`
(`get_server_info`); this plugin's `.dev/CONTRACTS.md` §2 for the mock format.
<https://code.claude.com/docs/en/plugins/manifest-reference#mcpservers>
(`requestTimeout`), <https://code.claude.com/docs/en/permission-modes>
(`dontAsk`'s always-denied list), <https://code.claude.com/docs/en/permissions#mcp>
(rule syntax, `_` normalisation, plugin form), <https://code.claude.com/docs/en/env-vars>
(`CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.299 rule
scoping and protocol negotiation, 2.1.302 fix, 2.1.305, 2.1.307, 2.1.309 and
2.1.310 MCP entries, 2.1.311 late-connecting servers),
<https://code.claude.com/docs/en/headless> ("MCP work when a non-interactive run
ends").
The `is_error is None`, ambient-connector and `tools=["Read"]` observations were
measured by this plugin on 2026-09-30. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs; re-read 2026-10-24 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs. Re-read 2026-10-29 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
