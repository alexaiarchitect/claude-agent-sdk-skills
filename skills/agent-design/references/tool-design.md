# Tool design

A tool is a contract between deterministic code and a model that reads it
fresh every time. *Writing effective tools for AI agents* (2025-09-11) argues
for designing tools for agents rather than wrapping APIs for developers — and
notes that agent-friendly tools usually turn out friendlier to people too.
*Building effective AI agents* (2024-12-19, Appendix 2) says to give tool
definitions as much care as the prompt.

## The DSG rules and why

`design_check.py` reports these. Thresholds are heuristics from the articles,
not SDK limits.

| Id | Trigger | Why it matters |
|---|---|---|
| DSG001 | a tool with no description, or under 40 characters | the model picks tools from descriptions; describe each as you would to a new hire — when to use it, what it returns, input formats, how it differs from its neighbours |
| DSG002 | a parameter named `id`, `user`, `data`, `input`, `value`, `item` or `obj` | the model fills arguments by name; article #4's example is `user_id`, not `user` |
| DSG003 | `list_*`, `get_all_*`, `fetch_*`, `dump_*` with no `limit`/`page`/`offset`/`query`/`filter`-like parameter | agents have little context and memory is cheap: prefer `search_contacts` to `list_contacts`; any large response needs pagination, filtering or truncation with a default |
| DSG004 | four or more tools on one server sharing no name part | namespacing by service and resource (`asana_search`, `asana_projects_search`) helps the model tell tools apart; the SDK's `mcp__<server>__` prefix separates servers, not resources |
| DSG005 | two tools with the same action on the same thing (`find_book`, `search_books`, a bare `lookup`) | overlapping tools split the model's choice; consolidate or make each purpose distinct |
| DSG006 | more than 30 tool definitions reachable | article #7: tool choice tends to degrade past 30–50 definitions in the system prompt |

DSG007 and DSG008 are about subagents and long runs: see
[subagent-decisions.md](subagent-decisions.md) and
[long-running-harness.md](long-running-harness.md).

Thirty is the low end of #7's range on purpose: it is a warning, not a limit.
Tool search defers MCP schemas by default, which removes their token cost; it
does not make overlapping tools distinct once loaded.

## Choosing tools

- **Fewer, higher-impact tools.** Do not wrap every endpoint. Build a few tools
  for the workflows your eval tasks need, then grow.
- **Consolidate.** One tool can do what three calls would: `schedule_event`
  instead of `list_users`, `list_events`, `create_event`; `get_customer_context`
  instead of three getters. Call patterns in transcripts show what to merge.
- **Group by user intent**, not one tool per API (article #7).

## Returning context

- Return **high-signal fields**: names over UUIDs, `file_type` over
  `mime_type`. Resolve opaque ids into something the model can reason about.
- Offer a **`response_format`** parameter (`"concise"` / `"detailed"`) when
  follow-up calls sometimes need ids. Article #4 measured a concise response at
  about a third of the detailed one's tokens.
- **Paginate, filter, truncate**, with sensible defaults. When you truncate,
  say how to narrow the search.
- **Make errors actionable.** Say what to change and give a correct example,
  not a code or a traceback. In the SDK, return `{"content": [...], "is_error":
  True}` with that message; an uncaught exception also reaches the model, but
  only as its raw message.

**The output cap, today.** The SDK applies Claude Code's MCP output limits: a
successful text result over 25,000 tokens is saved to a file and replaced by
an error naming the path, so the agent can read it back in parts; text over
50,000 characters is saved regardless; `MAX_MCP_OUTPUT_TOKENS` changes the
token limit. Article #4 states the same 25,000-token default as of 2025; cite
the docs for the current numbers. A `list_*` tool that can cross this line
turns a lookup into a recovery.

## Writing descriptions and schemas

- Make implicit context explicit: query syntax, niche terms, how resources
  relate.
- Use **unambiguous parameter names** and strict input types. Article #4
  reports state-of-the-art SWE-bench results from refining tool descriptions
  alone.
- **Poka-yoke** the arguments (article #2): change them so mistakes are
  harder — the SWE-bench agent was made to take absolute paths after relative
  ones caused errors.
- Pick formats a model writes easily: close to natural text, no line counts or
  escaped code inside JSON.

## `@tool` in the Python SDK

- `@tool(name, description, input_schema)` then `create_sdk_mcp_server(name=...,
  tools=[...])`; the model sees `mcp__<server>__<name>`.
- The schema is a `{"param": type}` dict or a full JSON Schema; use JSON Schema
  for enums, optional fields and descriptions per parameter. Make a parameter
  optional in the schema and default it in the handler.
- **Annotations** via `annotations=ToolAnnotations(...)`: `readOnlyHint` (default
  false) lets the tool run in parallel with other read-only calls;
  `destructiveHint` (default true), `idempotentHint` and `openWorldHint` are
  metadata. In Python they are informational: `destructiveHint` matters only
  for TypeScript's `always_ask` policy under `auto`/`plan`, and Python has no
  `permission_policy` — gate a destructive tool with `can_use_tool` or a
  `PreToolUse` hook. Annotations are not enforcement; keep them true to the
  handler.
- Return `structuredContent` for a machine-readable result.

## Evaluation-driven iteration

Article #4's loop: **prototype, evaluate, improve, repeat.**

1. Prototype quickly and try the tools yourself through the agent.
2. Generate many realistic eval tasks, some needing several — even dozens of —
   tool calls. A single obvious lookup is a weak task.
3. Pair each with a verifiable outcome; avoid verifiers so strict they reject a
   correct answer over formatting.
4. Collect more than accuracy: tool calls per task, tokens, runtime, tool
   errors. Redundant calls point at pagination; invalid-parameter errors point
   at descriptions.
5. Read the raw transcripts — what the agent leaves out of its own explanation
   often matters most.
6. Keep a **held-out set** so the tools are not tuned to the training tasks.

## In this plugin

- `design_check.py` and `design_brief.py` (this skill) for DSG001–DSG006.
- `/agent-sdk:agent-harness` for wiring: `mcp__` prefixes that name no server,
  `@tool` schemas that do not parse, stdio commands missing from PATH.
- `/agent-sdk:eval-create` and `/agent-sdk:eval-review` (`crosscheck_tools.py`)
  for tasks that exercise each tool; `/agent-sdk:eval-analyze` for tool-call
  counts and cost per task.

Sources: https://www.anthropic.com/research/writing-tools-for-agents ("Writing effective tools for AI agents", 2025-09-11, choosing and consolidating tools, namespacing, response_format, pagination and truncation, actionable errors, parameter names, evaluation-driven iteration with held-out tasks); https://www.anthropic.com/research/building-effective-agents ("Building effective AI agents", 2024-12-19, Appendix 2: tool definitions as prompts, formats, poka-yoke); https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop ("Building agents: When to fold subagents into your main agent loop", 2026-10-22, the 30–50 tool-definition range, grouping by intent); https://www.anthropic.com/research/code-execution-with-mcp ("Code execution with MCP for efficient agents", 2025-11-04, filtering large results in code); https://code.claude.com/docs/en/agent-sdk/custom-tools (read 2026-10-29, `@tool`, optional parameters, annotations, `is_error`, `structuredContent`, TypeScript-only `permission_policy`); https://code.claude.com/docs/en/agent-sdk/mcp (read 2026-10-29, tool naming and the 25,000-token / 50,000-character output limits); https://code.claude.com/docs/en/agent-sdk/tool-search (read 2026-10-29, deferred schemas). Written 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
