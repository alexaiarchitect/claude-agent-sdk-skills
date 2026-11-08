# Multi-turn cases: what a session actually carries

A session is a conversation with one CLI subprocess. What survives from one
turn to the next is the message history the CLI keeps, and nothing else: there
is no state store in the SDK, no key-value bag on the client, no field on
`ResultMessage` that carries "what the agent knows". Everything a memory case
asserts has to be visible in the trace, in a file, or in the final text.

That constraint is why there is no `session_state` grader. It was considered
and dropped: none of the 49 options and none of the seven message types carries
agent state.

## Two ways to write one

**Scripted** — you know both turns:

```yaml
turns:
  - "Reserve 'Dune' for member-42."
  - "Actually, make that two copies."
```

The body of `prompt.md` is ignored when `turns` is set, so write the case with
no body at all rather than leaving a prompt that never runs (`EVC002`, info).

**Persona-driven** — you know the pressure, not the words:

```yaml
simulated_user: personas/impatient.json
```

A persona is a small JSON document describing who the user is, what they want
and what they will do when they do not get it. The runner drives each user turn
through a `query()` call, which makes this a `judge`-tier case: it costs a
model call per user turn on top of the agent's own. `turns` and
`simulated_user` are mutually exclusive (`EVC006`).

## What to assert

Anthropic grades its own multi-turn safety evals conversation by conversation: **one bad
turn fails the whole conversation** (2026-11-13, article #44; no Agent SDK mention). A
`trajectory` or `regex` grader over the trace gives a multi-turn case the same rule.


| Claim | Grader | Note |
|---|---|---|
| turn two acted on turn one | `tool_order` with the two different tools | cheapest evidence that context survived |
| the agent did not repeat itself | `tool_used` with `max: 1` | catches an agent that re-looked-up what it already knew |
| the final reply refers back | `llm` or `final_text` | the expensive half: it needs the *content* to have survived |
| the session ended cleanly | `terminal` | a multi-turn case is more likely to hit `max_turns` |

The generated memory case ships `turns` plus a `tool_order` grader, with both
sides of the order as a TODO — the generator knows the shape, not which two
tools this agent has.

## The trap: a case that is not about memory

A two-turn case where the second turn repeats everything the first established
tests nothing about memory:

```yaml
turns:
  - "Reserve 'Dune' for member-42."
  - "Reserve a second copy of 'Dune' for member-42."   # no memory needed
```

The second turn has to *refer* to what the first established without naming it
again — "make that two copies", "cancel that one", "and the other title I
mentioned". That is what makes the case fail when context is lost.

## Cost and turn budgets

Multi-turn cases are the ones that hit ceilings:

* **`max_turns` is not a turn counter you can assert on.** `max_turns=1` was
  measured producing `num_turns=2`. A `budget` grader compares `num_turns`
  against its *own* ceiling; to assert that the limit actually fired, use
  `terminal` with `subtype: error_max_turns` or `terminal_reason: max_turns`.
* **Cost is the session total, not a sum of turns.** `total_cost_usd` on the
  result is a running total for the session; the runner records a per-turn
  delta, and a `budget` grader reads the case total.
* **Context grows.** Each turn re-sends the history, so cache-read tokens climb
  and a long case costs more per turn than a short one. That is what
  `max_cache_read_tokens` is for.

## Memory across sessions: a pair of cases and a consolidation case

Everything above is memory *within* one session. Memory *across* sessions —
notes a later session reads, as in *The components of agent memory* (2026-11-06,
article #30; design in `/agent-sdk:agent-design`, `memory-design.md`) — lives in
files, so it is tested through files and the trace, never a state store. One
case is one session, so "two runs" is two cases:

| Case | Setup | Assert |
|---|---|---|
| **write** | a task that teaches something worth keeping (a correction, a tested rule) | `file_exists` on `memory/*.md`; `regex` with `target: files` for the fact |
| **read** | `scaffold_script` seeds `memory/` with the note the write case should produce; a task that needs it | `regex` with `target: trace` for a read of the note's path; `tool_used` with `max: 0` on the lookup the note makes unnecessary; `final_text` or `regex` for the fact |
| **consolidate** | `scaffold_script` seeds a wrong note plus a log file that contradicts it; the prompt asks for one consolidation pass | `regex` with `target: files` for the corrected fact, and `match: not_contains` for the wrong one; `no_tool` on tools the pass must not use (`Bash`) |

Seed the read case from a note a real write run produced, so the pair tests the
same format. Add a **stale-note** variant (the seeded note contradicts what the
scaffolded files now say; the agent should trust the files and update the note)
when the agent's memory holds facts that change.

**Keep the memory folder inside the run's working directory.** The runner forces
`setting_sources=[]` but does not set `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, and
Claude Code's auto memory loads in SDK sessions regardless of `setting_sources`.
Its directory sits under the config directory, outside the run's working
directory, so a note saved there is invisible to `file_exists`; and since the
directory is keyed to the project path, a run in a fresh directory most likely
starts with an empty one (our reading of the memory docs). An agent whose memory
is app-designed should set the variable in its own `env`.

## Isolation still applies

Each *case* gets a fresh session and a fresh working directory; each *turn*
does not. A `scaffold_script` runs once per run, before turn one. If a case
needs state to change between turns, the change has to come from the agent's
own tool calls — which is usually the thing being tested anyway.

Sources: `.dev/CONTRACTS.md` §1 (`turns`, `simulated_user`, `EVC006`), §2.1
(`budget.max_turns` measurement, cost delta), §5.2 (`ResultMessage` fields) and
§1.2 (per-run isolation); `lib/agent_sdk_skills/evalcase.py`
(`is_multi_turn`, `EVC002`, `EVC040`);
https://code.claude.com/docs/en/agent-sdk/python (`ClaudeSDKClient`, the
message stream, `ResultMessage.num_turns`);
https://code.claude.com/docs/en/agent-sdk/sessions (what a session is);
https://www.anthropic.com/research/components-of-agent-memory ("The components of
agent memory", 2026-11-06, notes for later sessions, correcting notes against
transcripts; experiments on Claude Managed Agents, cited for the method);
https://code.claude.com/docs/en/memory (read 2026-11-08, the auto-memory
directory and what loads); https://code.claude.com/docs/en/agent-sdk/claude-code-features
(read 2026-11-08, auto memory loads regardless of `setting_sources`).
https://www.anthropic.com/research/building-strong-safety-evaluations ("Building strong safety
evaluations", 2026-11-13, one bad turn fails the conversation; no Agent SDK mention).
Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
