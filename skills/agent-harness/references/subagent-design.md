# Designing a subagent

## What a subagent is, exactly

A second agent instance with its own context window. The parent sends it **one
prompt string** through a tool call and receives the subagent's **final report**
back — that is the docs' term for it, and it is one message. Nothing else
crosses in either direction.

That is the whole value: an exploration that would fill the main conversation
happens somewhere else, and the parent gets a summary instead of forty file
reads. It is also the whole risk: the parent cannot see what the subagent did,
so whatever you need to verify has to be in the final report — or in a file, a
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
| `skills` | no | preloaded at startup — "at most the first 32 distinct names in the list"; unlisted skills stay invocable through the Skill tool |
| `memory` | no | `user` / `project` / `local` |
| `mcpServers` | no | by name, or inline config |
| `maxTurns` | no | the subagent's own ceiling (`SUB003`). At the limit its output is returned marked partial |
| `background` | no | force background execution |
| `effort`, `permissionMode`, `initialPrompt` | no | a `permissionMode` of `"auto"` is applied only when auto mode is available to that subagent |

The **Agent tool itself** also takes an `effort` input (Claude Code **2.1.292+**),
so Claude can ask for a cheaper or harder-thinking subagent per call without the
definition changing. Effort carries over across a model fallback: a subagent
started at `medium` stays at `medium` on the fallback model even when that model
defaults to `high`.

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
| background check-ins | `CLAUDE_CODE_WORKER_CHECKIN_SCHEDULE` in `env` | none | comma-separated whole seconds, `1`–`86400` (e.g. `600,1800,3600`), the last value repeating. Plain digits only, or it reads as unset. It **replaces** `CLAUDE_CODE_AUTO_BACKGROUND_WORKER_CHECKIN_SECONDS`, removed in 2.1.283 |
| concurrency | `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` in `env` | 20 at once | refuses to spawn, returning `Concurrent subagent limit reached` as the tool result |
| spend | `max_budget_usd` (a query option) | none | refuses new subagents, stops running background ones, ends the query with `error_max_budget_usd` |

In Python, `env` is **merged** into the inherited environment (in TypeScript it
replaces it). The parent's `max_turns` does **not** cap a subagent — that is
what `maxTurns` on the definition is for.

A long-running subagent also has a context window to manage: `autoCompactWindow`
lowers where auto-compaction kicks in (100000–1000000 tokens) — but only as
`.claude/agents/*.md` frontmatter (Claude Code **2.1.296+**) or on the
**TypeScript** SDK's agent definition (v0.3.296+); the Python `AgentDefinition`
has no such field, and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` overrides it. From
Claude Code **2.1.288** a value
given to `/autocompact` is saved **per model** under `modelSettings` rather than
as one global top-level setting (2.1.296 is the release the current wording
describes). Where a model-switching request would normally prompt, **in a
subagent no prompt is shown** — the flagged request simply re-runs on the
fallback model.

**Two defaults changed in 2.1.302** for `claude -p` and the Agent SDK; the
docs now describe both.

**Forked subagents.** "A fork is a subagent that copies the conversation so far
instead of starting fresh. From Claude Code v2.1.302, Claude can start forks in
your application with nothing configured, by calling the Agent tool with
`subagent_type: "fork"`." So an agent that defines no subagents can still
delegate, and an eval that asserts on the set of `subagent_type` values sees
`fork`. Deny forks only with `disallowed_tools=["Agent(fork)"]` (other subagents
still run); turn fork mode off entirely with `CLAUDE_CODE_FORK_SUBAGENT=0` in
`env`. From 2.1.307 forks launched together are each told which launch is
theirs, so they rarely start each other's work.

**Who waits.** With `run_in_background` omitted, "your main agent's call runs
the new agent in the background, and a subagent's call waits for it": from the
main agent the Agent tool result has `status: "async_launched"` and the report
arrives in a later turn (Claude still waits, `status: "completed"`, when its next
step needs it, or when the prompt asks it to); from a subagent the call blocks,
unless the definition sets `background=True` or fork mode is off. "Before Python
SDK v0.2.169, agents that your subagents started also ran in the background by
default. That release is the first to bundle Claude Code v2.1.302 or later."

Since 2.1.299 an agent's `tools:` list that names an MCP server takes only
**that server's** tools; list a server whose name contains `__` as
`mcp__<whole name>__*`. From 2.1.304 a plugin can no longer keep a headless run
going past `--max-turns`, Stop or ended input by spawning or re-running
subagents.

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

The **TypeScript** Agent SDK additionally puts `agent_id` on a subagent's
assistant and user messages from v0.3.292, equal to the `task_id` of that
subagent's task events, which is the reliable way to attribute interleaved
parallel subagents. **Python has no such field** on `AssistantMessage` or
`UserMessage` at 0.2.174 — `parent_tool_use_id` is what a Python reader
correlates on. (From 0.2.166, `agent_id` does appear on the four
tool-lifecycle *hook inputs*; that is a 0.2.166+ fact and a different surface.)
Subagent transcripts record real token usage and stop reasons for streamed
responses from 2.1.307 (before, placeholders and an empty stop reason), which
matters to anyone pricing or grading from the session files.

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
(subagent mode inheritance), <https://code.claude.com/docs/en/agent-sdk/subagents>
("Forked subagents", "Choose whether Claude waits for subagents"),
<https://code.claude.com/docs/en/agent-sdk/python> (Agent tool
`run_in_background`), <https://code.claude.com/docs/en/env-vars>;
<https://code.claude.com/docs/en/model-config> (effort after a fallback,
per-model `autoCompactWindow`),
<https://code.claude.com/docs/en/sub-agents#subagent-auto-compact-window>,
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.299 MCP
`tools:` scoping, 2.1.302 fork and foreground defaults, 2.1.304 headless
stop, 2.1.307 fork identity and transcript usage);
`claude-agent-sdk` 0.2.174 `types.py:2647` (`agents`), `:2563-2573`
(`parent_tool_use_id` and subagent text), `:1821` (`HookEventMessage`). The
`Task` / `Agent` naming difference was measured by this plugin on 2026-09-30
from the CLI's own `init.tools` list. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs; re-read 2026-10-24 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs.
