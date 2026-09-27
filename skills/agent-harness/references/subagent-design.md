# Designing a subagent

## What a subagent is, exactly

A second agent instance with its own context window. The parent sends it **one
prompt string** through a tool call and receives **one final message** back.
Nothing else crosses in either direction.

That is the whole value: an exploration that would fill the main conversation
happens somewhere else, and the parent gets a summary instead of forty file
reads. It is also the whole risk: the parent cannot see what the subagent did,
so whatever you need to verify has to be in the final message — or in a file, a
mock call record, or `structured_output`.

| The subagent receives | The subagent does not receive |
|---|---|
| its own `prompt`, plus the Agent tool's prompt string | the parent's conversation history or tool results |
| project `CLAUDE.md`, when `setting_sources` loads it | preloaded skill content, unless listed in `skills` |
| tool definitions: inherited, or the subset in `tools` | the parent's system prompt |

So: **put every path, error message and decision the subagent needs into the
prompt string.** There is no ambient context to fall back on.

## `AgentDefinition`, field by field

| Field | Required | Note |
|---|---|---|
| `description` | yes | Claude reads this to decide when to delegate. Write it for Claude — "use for X" — not as a label |
| `prompt` | yes | the subagent's system prompt |
| `tools` | no | omitted, it inherits **every** tool available to subagents (`SUB001`) |
| `disallowedTools` | no | accepts `mcp__server`, `mcp__server__*`, `mcp__*` |
| `model` | no | an alias, a full id, or `'inherit'`. Omitted, Claude Code picks from the subagent model order |
| `skills` | no | preloaded at startup; unlisted skills stay invocable through the Skill tool |
| `memory` | no | `user` / `project` / `local` |
| `mcpServers` | no | by name, or inline config |
| `maxTurns` | no | the subagent's own ceiling (`SUB003`). At the limit its output is returned marked partial |
| `background` | no | force background execution |
| `effort`, `permissionMode`, `initialPrompt` | no | |

In Python the multi-word names keep their **camelCase** spelling
(`disallowedTools`, `mcpServers`, `maxTurns`) to match the wire format. This
catches people out constantly; a `max_turns=` keyword on an `AgentDefinition` is
not the same field, which is why the linter accepts both spellings and warns
when neither is present.

## The tool is called two things

The docs and the SDK call it **`Agent`**. The CLI's own `init.tools` list
reports **`Task`** (measured). Both names refer to the same tool, so:

- `allowed_tools` should carry both, or delegation may silently not happen
  (`OPT040`);
- a `tool_used` or `trajectory` grader naming either must match both;
- a `disallowed_tools` entry for one and not the other is a half-closed door.

A call to the Agent tool with no `subagent_type` gets the built-in
`general-purpose` subagent, which Claude can spawn even when you define none of
your own. `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` removes that default.

## Caps: depth, concurrency, spend

Claude decides on its own when to spawn a subagent and how many. A subagent can
spawn subagents. One prompt can become a tree.

| Limit | Set with | Default | At the limit |
|---|---|---|---|
| depth | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` in `env` | 3 layers (`1` stops your subagents from spawning any) | the bottom layer does the work itself |
| concurrency | `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` in `env` | 20 at once | refuses to spawn, returning `Concurrent subagent limit reached` as the tool result |
| spend | `max_budget_usd` (a query option) | none | refuses new subagents, stops running background ones, ends the query with `error_max_budget_usd` |

In Python, `env` is **merged** into the inherited environment (in TypeScript it
replaces it). The parent's `max_turns` does **not** cap a subagent — that is
what `maxTurns` on the definition is for.

Opus 5 delegates more readily than earlier models, so these matter most there.
With the `claude_code` system-prompt preset, Claude Code adds a line telling
Claude not to call the Agent tool unless asked; with a custom prompt or no
system prompt, it does not, and you have to add that instruction yourself. Both
only steer — the limits are what enforce.

## Filesystem subagents

`.claude/agents/<name>.md` files are the alternative. They load only when
`setting_sources` includes `project`, so an eval with `setting_sources=[]` will
not see them (`SUB010`). Programmatic `agents` entries take precedence over
files of the same name.

Rule of thumb: **programmatic for anything an eval must reproduce, files for
anything a human also uses interactively.** `gen_subagent.py` writes either.

## Seeing that it happened

There is no `SubagentStartMessage`. Subagent activity arrives as:

- `HookEventMessage` with `hook_event_name` `SubagentStart` / `SubagentStop`,
  when `include_hook_events=True` **and** a hook is registered;
- `AssistantMessage` / `UserMessage` whose `parent_tool_use_id` is the spawning
  tool-use id.

Before v2.1.210 the parent read the subagent's final message verbatim; since
then Claude Code scans it for instruction-shaped patterns (control tags, turn
markers) and neutralises them in place, prepending a `[harness: ...]` line for
the first two kinds. It never removes or rewords the text, but a grader doing an
exact-match on a subagent's final message should know the scan exists.

## When not to delegate

For dozens to hundreds of agents, the `Workflow` tool moves orchestration into a
script run outside the conversation context. Subagents are for a few delegated
tasks per turn.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/subagents>
(AgentDefinition configuration, what subagents inherit, tool restrictions, caps,
Opus 5, output scanning), <https://code.claude.com/docs/en/sub-agents>
(filesystem definitions, available tools, concurrent limit),
<https://code.claude.com/docs/en/agent-sdk/permissions#available-modes>
(subagent mode inheritance), <https://code.claude.com/docs/en/env-vars>;
`claude-agent-sdk` 0.2.162 `types.py:2291` (`agents`), `:2207-2217`
(`parent_tool_use_id` and subagent text), `:1466` (`HookEventMessage`). The
`Task` / `Agent` naming difference was measured by this plugin on 2026-09-30
from the CLI's own `init.tools` list.
