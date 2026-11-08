# Designing a subagent

## What a subagent is, exactly

A second agent instance with its own context window. The parent sends it **one prompt string** through a tool call and
receives the subagent's **final report** back — that is the docs' term for it, and it is one message. Nothing else
crosses in either direction.

That is the whole value: an exploration that would fill the main conversation happens somewhere else, and the parent
gets a summary instead of forty file reads. It is also the whole risk: the parent cannot see what the subagent did, so
whatever you need to verify has to be in the final report — or in a file, a mock call record, or `structured_output`.

| The subagent receives | The subagent does not receive |
|---|---|
| its own `prompt`, plus the Agent tool's prompt string | the parent's conversation history or tool results |
| project `CLAUDE.md`, when `setting_sources` loads it | preloaded skill content, unless listed in `skills` |
| tool definitions: inherited, or the subset in `tools` | the parent's system prompt |

So: **put every path, error message and decision the subagent needs into the prompt string.** There is no ambient
context to fall back on.

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

The **Agent tool itself** also takes an `effort` input (Claude Code **2.1.292+**), so Claude can ask for a cheaper or
harder-thinking subagent per call without the definition changing. Effort carries over across a model fallback: a
subagent started at `medium` stays at `medium` on the fallback model even when that model defaults to `high`. **With
no `effort` of its own** (docs `model-config`, "Effort level of subagents and teammates"), a subagent or teammate on
the main conversation's model runs at the session's level; on another model that level does not apply, and from
**2.1.317** it uses that model's saved level or its default (changelog). So set `effort` in the definition when it
matters. From **2.1.316** `CLAUDE_CODE_SUBAGENT_EFFORT` in `env` sets the level subagents run at when nothing else
names one (Claude Code `CHANGELOG.md` 2.1.316; the env-vars page read 2026-11-04 still does not list it). An
Agent-call `model` parameter "takes a model alias: `sonnet`, `opus`, `haiku`, or `fable`" — Claude cannot pass a full
model id or `inherit` on that call; the definition's `model` field still can. **`inherit` means the spawning agent's
model** (docs 2026-11-14): a nested subagent runs on its parent subagent's model, not the main conversation's, unless
its own `model` says otherwise; the model order is per-call alias, definition `model`, `CLAUDE_CODE_SUBAGENT_MODEL`,
then the parent's model. **The built-in Explore subagent runs on the parent conversation's model** (Fable → Opus on
the API; stays Fable on Bedrock, Vertex, Foundry and gateways), no longer always on Haiku — define your own `Explore`
with `model: haiku` to keep exploration cheap, and keep small models on work where a mistake is cheap to spot (finding
files, running tests, reading logs), never on edits or judgment calls (Osmani, 2026-11-09, article #42). From 2.1.325
a subagent with its own model is no longer moved to the plan-mode model under `opusplan`/`haiku`, and sizes file reads
with its own model.

In Python the multi-word names keep their **camelCase** spelling (`disallowedTools`, `mcpServers`, `maxTurns`) to
match the wire format. This catches people out constantly; a `max_turns=` keyword on an `AgentDefinition` is not the
same field, which is why the linter accepts both spellings and warns when neither is present.

## The tool is called two things

The docs and the SDK call it **`Agent`**; "the previous name `Task` is still accepted as an alias", and the init
`SystemMessage`'s `tools` list still reports **`Task`** for backward compatibility (measured again 2026-11-04 on
2.1.318). So:

- `allowed_tools` should carry both, or delegation may silently not happen (`OPT040`);
- a `tool_used` or `trajectory` grader naming either must match both;
- a `disallowed_tools` entry for one and not the other is a half-closed door.

A call to the Agent tool with no `subagent_type` gets the built-in `general-purpose` subagent, which Claude can spawn
even when you define none of your own. `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` removes that default. The same
renaming hit the background-stop tool: it is **`TaskStop`**, and the old names `KillShell`/`KillBash` are accepted
only in permission rules, hook matchers and the `tools`/`allowed_tools`/`disallowed_tools` options.

## Caps: depth, concurrency, spend

Claude decides on its own when to spawn a subagent and how many. A subagent can spawn subagents. One prompt can become
a tree.

| Limit | Set with | Default | At the limit |
|---|---|---|---|
| depth | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` in `env` | 3 layers (`1` stops your subagents from spawning any) | the bottom layer does the work itself |
| background check-ins | `CLAUDE_CODE_WORKER_CHECKIN_SCHEDULE` in `env` | none | comma-separated whole seconds, `1`–`86400` (e.g. `600,1800,3600`), the last value repeating. Plain digits only, or it reads as unset. It **replaces** `CLAUDE_CODE_AUTO_BACKGROUND_WORKER_CHECKIN_SECONDS`, removed in 2.1.283 |
| concurrency | `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` in `env` | 20 at once | refuses to spawn, returning `Concurrent subagent limit reached` as the tool result |
| spend | `max_budget_usd` (a query option) | none | refuses new subagents, stops running background ones, ends the query with `error_max_budget_usd` |

In Python, `env` is **merged** into the inherited environment (in TypeScript it replaces it). The parent's `max_turns`
does **not** cap a subagent — that is what `maxTurns` on the definition is for.

A long-running subagent also has a context window to manage: `autoCompactWindow` lowers where auto-compaction kicks in
(100000–1000000 tokens) — but only as `.claude/agents/*.md` frontmatter (Claude Code **2.1.296+**) or on the
**TypeScript** SDK's agent definition (v0.3.296+); the Python `AgentDefinition` has no such field. From **2.1.312** a
subagent's `autoCompactWindow` can **lower** the window set by `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, never raise it.

**A flagged request in a subagent** (docs `model-config`, read 2026-11-08): "In a subagent that Claude starts with the
Agent tool, Claude Code doesn't pause to ask, and the subagent fails instead of switching models": with "Switch models
when a message is flagged" set to "Ask each time" the subagent **stops** instead: it fails with `Agent terminated
early due to an API error` plus the refusal message, and Claude decides what to do about the unfinished task (2.1.318;
before, it always re-ran on a fallback). Under "Switch automatically", or with no choice made, the request re-runs on
the fallback model and the session model is unchanged; with no fallback available it fails either way.

**Forked subagents.** "A fork is a subagent that copies the conversation so far instead of starting fresh. From Claude
Code v2.1.302, Claude can start forks in your application with nothing configured, by calling the Agent tool with
`subagent_type: "fork"`." So an agent that defines no subagents can still delegate, and an eval that asserts on the
set of `subagent_type` values sees `fork`. Deny forks only with `disallowed_tools=["Agent(fork)"]` (other subagents
still run); turn fork mode off entirely with `CLAUDE_CODE_FORK_SUBAGENT=0` in `env`. From 2.1.307 forks launched
together are each told which launch is theirs, so they rarely start each other's work.

**Who waits.** With `run_in_background` omitted, "your main agent's call runs the new agent in the background, and a
subagent's call waits for it": from the main agent the Agent tool result has `status: "async_launched"` and the report
arrives in a later turn (Claude still waits, `status: "completed"`, when its next step needs it, or when the prompt
asks it to); from a subagent the call blocks, unless the definition sets `background=True` or fork mode is off.
"Before Python SDK v0.2.169, agents that your subagents started also ran in the background by default. That release is
the first to bundle Claude Code v2.1.302 or later." With `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` in `env`, "Claude
waits for subagents to finish before it continues" (background shell commands are off too).

Since 2.1.299 an agent's `tools:` list that names an MCP server takes only **that server's** tools (`mcp__<whole
name>__*` when the name contains `__`). From 2.1.304 a plugin can no longer keep a headless run going past
`--max-turns`, Stop or ended input by spawning or re-running subagents. From 2.1.311 subagents can use MCP tools from
servers that finish connecting after the subagent started (before, those tools were missing). From 2.1.314 the parent
of a long headless or SDK turn no longer keeps each subagent's tool results until the turn ends; from 2.1.316 a
subagent that inherited a parent subagent's model keeps it when a background job or message wakes it (before, it moved
to the main model). From 2.1.317 auto mode shows a notice when its check has no answer for a subagent's tool call.
From 2.1.318 background subagents move a shell command to the background after 3 minutes on all providers. From
2.1.321 queued subagent reports in auto mode are answered in one model call (headless and SDK sessions too); `-p` can
exit 0 before a subagent's backgrounded command finishes (`headless`, 2026-11-14: raise `BASH_DEFAULT_TIMEOUT_MS`).

Opus 5 delegates more readily than earlier models, so these matter most there. With the `claude_code` system-prompt
preset, Claude Code adds a line telling Claude not to call the Agent tool unless asked; with a custom prompt or no
system prompt, it does not, and you have to add that instruction yourself. Both only steer — the limits are what
enforce.

## Filesystem subagents

`.claude/agents/<name>.md` files are the alternative. They load only when `setting_sources` includes `project`, so an
eval with `setting_sources=[]` will not see them (`SUB010`). Programmatic `agents` entries take precedence over files
of the same name.

Rule of thumb: **programmatic for anything an eval must reproduce, files for anything a human also uses
interactively.** `gen_subagent.py` writes either.

## Seeing that it happened

There is no `SubagentStartMessage`. Subagent activity arrives as:

- `HookEventMessage` with `hook_event_name` `SubagentStart` / `SubagentStop`,
  when `include_hook_events=True` **and** a hook is registered;
- `AssistantMessage` / `UserMessage` whose `parent_tool_use_id` is the spawning tool-use id.

The **TypeScript** Agent SDK additionally puts `agent_id` on a subagent's assistant and user messages from v0.3.292,
equal to the `task_id` of that subagent's task events, which is the reliable way to attribute interleaved parallel
subagents. **Python has no such field** on `AssistantMessage` or `UserMessage` at 0.2.182 — `parent_tool_use_id` is
what a Python reader correlates on. (From 0.2.166, `agent_id` does appear on the four tool-lifecycle *hook inputs*;
that is a 0.2.166+ fact and a different surface.) Subagent transcripts record real token usage and stop reasons for
streamed responses from 2.1.307 (before, placeholders and an empty stop reason), which matters to anyone pricing or
grading from the session files.

Since v2.1.210 Claude Code scans a subagent's final message for instruction-shaped patterns and neutralises them in
place (sometimes prepending a `[harness: ...]` line), which an exact-match grader on that message should know.

## When not to delegate: fold first

Anthropic's Applied AI team found that enterprise agents often improved when routers, planners and domain subagents
were **folded into one loop** with skills and tools (article of 2026-10-22). Keep a subagent only for one of three
reasons: the single loop shows **measurable** degradation from context bloat; several tasks need parallel, fresh,
disposable context windows; or one agent struggles to choose tools, or its prompt carries conflicting instructions.
When you do split, "divide by context", not by problem type or team — a split per team mirrors the org chart and turns
every handoff into a lossy summary. Fold **one subagent at a time**: call it as a tool first, then move its prompt
into a skill and its API calls into MCP tools, compare per task (which tasks flipped, not just the score), run each
task more than once, and keep it a subagent only when the folded version scores worse. Tool choice tends to degrade
past 30–50 tool definitions in the prompt, which is what tool search and skills avoid.

The case for multi-agent comes from the research system (2025-06-13): an orchestrator-worker setup beat a single agent
by 90.2 % on Anthropic's internal research eval, at roughly 15× the tokens of a chat, and "token usage by itself
explains 80% of the variance" in their browsing eval — breadth-first, parallel, high-value work pays for it; tightly
coupled work such as most coding does not. Each delegated task needs an objective, an output format, tool guidance and
a boundary. For the decision itself use `/agent-sdk:agent-design`.

A reviewer is the clearest case for fresh context. In the Claude Code team's own process the author agent first shows
its change working, "Then a subagent reviews the diff with fresh context" (Osmani, Westlee Lunt, Wang, 2026-10-15,
about Claude Code, not the SDK). In the SDK that reviewer is an `AgentDefinition` whose prompt carries the diff and
the acceptance criteria but none of the author's reasoning (our mapping).

A third shape has no orchestrator at all. In Anthropic's C-compiler project (2026-02-05) 16 `claude -p` loops, each in
its own container with permissions skipped only there, shared one git repository; an agent claimed a task by writing a
lock file, and a push conflict sent a second claimant to another task. It held together because the test suite was a
near-perfect oracle — without one, the author warns, "Claude will solve the wrong problem". Lock files are a harness
convention, not something the SDK provides; the SDK's own subagents are orchestrated by the parent.

**A harness written per task.** Claude Code's dynamic workflows (Shihipar, Bidasaria, 2026-06-02) let Claude write a
multi-agent harness for the task in front of it, as a script run by Claude Code's Workflow tool outside the
conversation context, to counter three failure modes of one long context: declaring done after partial progress,
preferring its own findings when judging, and drifting from the goal. The Workflow tool is Claude Code's, not an SDK
API (it appears in the SDK `init` tool list, but no SDK page documents it), and the article calls an SDK harness
"static". In an SDK app its patterns — classify-and-act, fan-out-and-synthesize, adversarial verification,
generate-and-filter, tournament, loop until done — are built from `agents` and the Agent tool or from several
`query()` calls; keep agents that read untrusted content away from high-privilege tools, and keep the fold rules
above: "most traditional coding tasks do not need a panel of 5 reviewers".

---

Sources: <https://code.claude.com/docs/en/agent-sdk/subagents> (AgentDefinition configuration, what subagents inherit,
tool restrictions, caps, Opus 5, output scanning), <https://code.claude.com/docs/en/sub-agents> (filesystem
definitions, available tools, concurrent limit),
<https://code.claude.com/docs/en/agent-sdk/permissions#available-modes> (subagent mode inheritance), the same
subagents page ("Forked subagents", "Choose whether Claude waits for subagents"),
<https://code.claude.com/docs/en/agent-sdk/python> (Agent tool `run_in_background`, `Task` alias, `TaskStop`),
<https://code.claude.com/docs/en/env-vars> (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`);
<https://code.claude.com/docs/en/sub-agents> (Agent-call `model` aliases);
<https://code.claude.com/docs/en/model-config> (effort after a fallback, "Effort level of subagents and teammates",
per-model `autoCompactWindow`, "Subagents switch or fail without asking"),
<https://code.claude.com/docs/en/sub-agents#subagent-auto-compact-window>,
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.299–2.1.314 as named above, 2.1.316
`CLAUDE_CODE_SUBAGENT_EFFORT`, 2.1.317 subagent effort on another model and the no-answer notice, 2.1.318 "Ask each
time" stop and 3-minute shell backgrounding); <https://www.anthropic.com/research/building-c-compiler> ("Building a C
compiler with parallel Claudes", 2026-02-05, lock-file task claiming without an orchestrator, tests as a near-perfect
oracle, containers);
<https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop> ("Building
agents: When to fold subagents into your main agent loop", 2026-10-22, when to keep a subagent, split by context, fold
one at a time, the 30–50 tool threshold); <https://www.anthropic.com/research/multi-agent-research-system> ("How we
built our multi-agent research system", 2025-06-13, the 90.2 % / 15× / 80 % figures and delegation rules; its
synchronous subagents describe Anthropic's Research product, not the SDK's background default);
<https://claude.dev/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code/> ("A harness for every task:
dynamic workflows in Claude Code", 2026-06-02, a per-task harness, three failure modes, orchestration patterns,
quarantine, cost); <https://claude.dev/blog/which-claude-model-should-you-build-with/> ("Which Claude model should you
build with? Fable, Opus, Sonnet, or Haiku", 2026-11-09, Explore on the session's model, `CLAUDE_CODE_SUBAGENT_MODEL`,
small models for cheap-to-check work); <https://code.claude.com/docs/en/sub-agents> ("Which model a nested subagent
runs on", the model order, read 2026-11-14); `claude-agent-sdk` 0.2.182 `types.py:2664` (`agents`), `:2580-2590`
(`parent_tool_use_id` and subagent text), `:1834` (`HookEventMessage`). The `Task` / `Agent` naming difference was
measured by this plugin on 2026-09-30 from the CLI's own `init.tools` list;
<https://claude.dev/blog/solving-code-review-at-anthropic/> ("How the Claude Code team does code review", 2026-10-15,
a fresh-context reviewer subagent). Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
