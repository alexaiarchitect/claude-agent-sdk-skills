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
https://code.claude.com/docs/en/agent-sdk/sessions (what a session is).
