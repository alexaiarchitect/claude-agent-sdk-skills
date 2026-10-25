# Subagents: keep, fold, or never add

Two Anthropic articles pull in opposite directions, and both are right about
their own case.

- *How we built our multi-agent research system* (2025-06-13): an Opus 4 lead
  with Sonnet 4 subagents beat a single Opus 4 agent by 90.2 % on Anthropic's
  internal research eval. It also used about 15× the tokens of a chat, and on
  BrowseComp token usage alone explained 80 % of the performance variance.
  Multi-agent wins by spending tokens in parallel, on breadth-first problems
  whose material does not fit one window.
- *Building agents: When to fold subagents into your main agent loop*
  (2026-10-22): in enterprise deployments, a **single agent with skills** often
  beat both one giant prompt and a subagent design on quality, frequently at
  lower cost and latency. Routers, planners and per-domain subagents folded into
  one loop with progressive disclosure.

So the default is one loop. A subagent has to earn its place.

## When to keep a subagent

Keep one when any of these holds (article #7):

1. The single loop shows **measurable** degradation from context bloat — an eval
   says so, not a hunch.
2. Several tasks need **parallel, fresh, disposable** context windows.
3. One agent struggles to choose among its tools, or the merged system prompt
   would carry **conflicting instructions**.

And split **by context, not by problem type**: give each subagent work that
needs little from the rest of the conversation and returns a compact result —
an independent research path, a component with a clean interface, a black-box
verification. One subagent per team or topic mirrors the org chart, and every
handoff loses context.

Multi-agent fits (article #10): open-ended, breadth-first questions; material
larger than one window; many independent directions; a task valuable enough to
pay for the tokens. It fits badly when every agent needs the same context or
the parts depend on each other — most coding tasks.

## The fold procedure

From article #7, one subagent at a time:

1. **Evals first.** One shared end-to-end task-completion set, plus small sets
   per skill. The article says ten golden examples are enough to start. Run each
   task more than once: one break it describes showed up in only one run of two.
2. **Call the subagent as a tool** while it still exists: the main agent keeps
   the conversation, verifies the result against real data, and you get a
   baseline.
3. **Fold it.** Its prompt becomes a skill (procedure and judgment), its API
   calls become MCP tools (actions and live reads). Fold the most-used first,
   and fold together specialists that chain on each other's output or touch the
   same data.
4. **Compare per task**, with and without the subagent. Look at which tasks
   flipped, not only the score.
5. **Keep it as a subagent only if the folded version scores worse.** Then the
   next one.

The article also names Claude Platform tools for this (a migration kit of
`/claude-api` skills). They are not part of this plugin; here the eval loop is
`/agent-sdk:eval-create`, `/agent-sdk:eval-run` and `/agent-sdk:eval-analyze`.

## If you keep it: what it must be told

The subagent sees its own `prompt`, the Agent tool's prompt string and project
`CLAUDE.md` — never the parent's conversation or system prompt. Article #10:
"Each subagent needs an objective, an output format, guidance on the tools and
sources to use, and clear task boundaries." Vague one-line tasks produced
duplicated work and gaps.

- **Objective**: what question it answers.
- **Output format**: what the final message contains and its shape. The parent
  sees only that message; article #3 puts typical subagent summaries at 1,000–
  2,000 tokens.
- **Tools**: scope `tools` to what the job needs; otherwise it inherits every
  tool available to subagents.
- **Boundaries**: what is out of scope, and `maxTurns`.
- **Scale effort to complexity**: article #10 wrote explicit rules — one agent
  for simple fact-finding, a few for comparisons, many only for complex
  research — after early versions spawned far too many. Its lead agent ran 3–5
  subagents in parallel.

`design_check.py` reports DSG007 when a subagent's prompt and description
contain none of "return", "report", "output", "format", "only", "do not" or
"scope" — a heuristic, so it is a note, not a warning.

## Current mechanics (docs, 2026-10-29)

Article #10 described synchronous subagents in Anthropic's own product; the
SDK behaves differently today.

| Fact | Detail |
|---|---|
| Background by default | a subagent the main agent spawns runs in the background; the Agent tool result has `status: "async_launched"` and the report arrives in a later turn. Claude waits when its next step needs the report (`status: "completed"`); ask for that in the prompt, or set `background` in the definition |
| `run_in_background` | the Agent call's own field; omitted, the main agent's call backgrounds and a subagent's call waits |
| Forks | from Claude Code 2.1.302 Claude can start a fork (`subagent_type: "fork"`) that copies the conversation instead of starting fresh; deny it with `disallowed_tools=["Agent(fork)"]` |
| Depth | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` in `env`, default 3 layers below the main agent; `1` stops nesting |
| Concurrency | `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, default 20; beyond it the spawn returns `Concurrent subagent limit reached` |
| Spend | `max_budget_usd` covers subagents; at the cap new spawns fail with `Budget limit reached` and running background subagents stop |
| Model | `AgentDefinition.model` takes an alias or a full id; on an Agent **call**, Claude may pass only an alias (`sonnet`, `opus`, `haiku`, `fable`) |
| Naming | the tool is `Agent`; the CLI's init `tools` list still reports `Task` |

Parallel, disposable windows are exactly what background subagents give you;
that is the context-based reason to keep one. "This topic belongs to another
team" is not.

## Decision table

| Situation | Decision |
|---|---|
| a subagent per domain, called in sequence, each needing the last one's output | fold |
| a search that reads hundreds of results and returns ten lines | keep, if it runs in parallel or the parent never needs the raw results; otherwise try folding behind a search tool |
| a reviewer that must not see the generator's reasoning | keep (verification by a separate context) |
| a router that only picks a prompt | fold into skills; the main loop routes by reading skill descriptions |
| no subagents, and the agent does one thing at a time | do not add one |

## In this plugin

- `design_brief.py` prints this table per `AgentDefinition`, plus the fold
  procedure.
- `/agent-sdk:agent-harness` checks the wiring (`tools`, `maxTurns`, the Agent
  tool allowed) and generates definitions with `gen_subagent.py`.
- `/agent-sdk:eval-create` writes the task-completion cases the fold needs;
  `/agent-sdk:eval-analyze` compares the two arms.

Sources: https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop ("Building agents: When to fold subagents into your main agent loop", 2026-10-22, single loop with skills, keep conditions, split by context, the staged fold procedure, ten golden examples, running tasks more than once); https://www.anthropic.com/research/multi-agent-research-system ("How we built our multi-agent research system", 2025-06-13, the 90.2 % result, about 15× tokens, 80 % of variance from token usage, delegation rules, effort scaling, 3–5 parallel subagents); https://www.anthropic.com/research/effective-context-engineering-for-ai-agents ("Effective context engineering for AI agents", 2025-09-29, 1,000–2,000-token subagent summaries); https://code.claude.com/docs/en/agent-sdk/subagents (read 2026-10-29, `AgentDefinition` fields, inheritance, background default, forks, depth, concurrency and spend caps); https://code.claude.com/docs/en/agent-sdk/python (read 2026-10-29, `run_in_background`, `async_launched`, the `Agent`/`Task` naming); https://code.claude.com/docs/en/sub-agents (read 2026-10-29, Agent-call `model` aliases). Written 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
