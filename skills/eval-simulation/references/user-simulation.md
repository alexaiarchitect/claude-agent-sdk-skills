# The simulated user: what it is, what it costs, what it can prove

A scripted multi-turn case (`turns:`) asks the agent exactly the questions its
author imagined, in the order the author imagined them. That is the right shape
for a memory test and the wrong shape for "does this hold up against a real
person", because a real person reacts to what the agent just said.

A **simulated user** replaces the script with a second model. The runner loads a
persona from `simulated_user: personas/<name>.json`, and then, turn by turn:

1. renders the persona and the transcript so far into one prompt;
2. calls `query()` on a **separate session** with `tools=[]`,
   `allowed_tools=[]`, `max_turns=1`, `permission_mode="dontAsk"`,
   `setting_sources=[]`, `strict_mcp_config=True`, `effort="low"`;
3. takes the last text block as the user's next turn;
4. sends that to the agent's own session and captures everything as usual.

It stops when the simulator answers with the persona's `stop_marker` alone
(default `DONE`, compared case-insensitively with trailing `.`/`!` stripped),
when the model returns nothing, or when `max_user_turns` user turns have been
spoken. An `opening` is used verbatim for turn 1 and costs no call.

The isolation is the point. The simulated user has no tools and never sees the
agent's options, so it cannot accidentally do the agent's work — it can only
talk.

## What it costs

Per run of one simulated case:

| Spend | Count |
|---|---|
| agent sessions | 1 (the case itself, all turns in one session) |
| judge-tier calls for the user's turns | up to `max_user_turns`, minus 1 if `opening` is set |
| judge-tier calls for the violation rubrics | one per rubric, at the end, `samples=1` |
| judge-tier calls for the case's own `llm` graders | as usual, `samples` each |

So a persona with `max_user_turns: 4`, an `opening` and three violation rubrics
costs one agent session plus six judge-tier calls, **before** the case's graders.
That is why simulated cases belong in their own tier, not in the per-PR gate.
`SimulatedUser` accumulates `cost_usd` and `calls` separately from the agent's,
and the result carries `simulated_user_turns`, so the arithmetic is auditable
rather than assumed.

Two ways to make that bill smaller without changing the case. The simulator is a
judge-tier call, so it can run on the **cheap judge**, `claude-haiku-5-5`
($0.10 / $0.50 per Mtok against Sonnet 5.5's $2 / $10, 1M context by default,
needs Claude Code 2.1.293+) — a persona's turns are short, which is exactly what
that model is good at. The suite default stays `claude-sonnet-5-5`, so set the
cheaper id on the simulator rather than globally, and keep Sonnet for the
violation rubrics, where the verdict has to be explained. Note the price is a
*from* price: above a 100K-token prompt it rises, so a long conversation saves
less than the headline. And the run's cost ceilings are **soft** —
`max_budget_usd` and `--max-cost-usd` compare against a running estimate that
can pass the value before the run stops, so a simulated tier needs headroom,
not an exact figure.

## Violation rubrics judge the simulator, not the agent

This is the single easiest thing to get backwards. The rubrics in a persona are
run against **the user's own turns**:

```
"The simulated user in this transcript must satisfy: <rubric>
 PASS when the statement holds for every user turn shown."
```

with the evidence being `User turn 1: …`, `User turn 2: …` and nothing else. A
violated rubric makes the case **NOT_EVALUATED**, not FAILED — because what
failed was the measuring instrument. A run where the simulator volunteered the
member id the persona was told to withhold does not show the agent passed; it
shows the test never happened.

Assertions about the agent go where every other assertion goes: the case's
`graders/` directory.

## Which graders make sense

| Grader | On a simulated case |
|---|---|
| `llm` (`target: last_message`) | **yes** — the natural fit; judge the final answer against a criterion |
| `llm` with `target: simulated_user` | **yes** — judge the user's turns, e.g. "the conversation actually reached a decision" |
| `regex` / `final_text` | yes, if the phrasing you care about is stable |
| `tool_used` / `no_tool` | yes for a *set* — "it looked the book up at least once", "it never cancelled" |
| `budget` / `terminal` | yes — a conversation that hit `max_turns` is inconclusive and should say so |
| `hook_event` | yes, paired with a faults file |
| `trajectory` | **no** — refused as `EVC040` |
| `tool_order` | technically allowed, practically fragile; the order depends on what the user happened to ask |

`trajectory` is refused because it asserts an exact or ordered tool sequence, and
the sequence is a function of turns nobody wrote. The same case would pass on
Monday and fail on Tuesday with no change to the agent — a flaky gate that
teaches the team to ignore red. If the sequence is what matters, the case wants
`turns:` and a script, not a persona.

`target: simulated_user` is the escape hatch for the case where you want a
judgement about the conversation rather than the final message: the grader is
handed the user's turns as evidence, exactly as the violation rubrics are.

## When a simulated case is the wrong tool

- The behaviour is deterministic and one prompt reaches it — use a normal case.
- You need the same conversation every time (a regression) — use `turns:`.
- You are testing tool wiring — use mocks; a persona adds cost and variance and
  proves nothing extra.
- The agent is not yet passing its single-turn cases. Multi-turn variance on top
  of a broken agent produces noise, not diagnosis.

## Reading the result

A simulated run records the user's turns in the trace as ordinary `user` events,
so `/agent-sdk:agent-debug` reads it like any other transcript. The first thing
to check when a simulated case fails is the user's turns, not the agent's: about
half of the "the agent did the wrong thing" reports on simulated cases turn out
to be a persona that asked for the wrong thing.

Sources: this plugin's runner —
`runner/agent_sdk_evals/simulate.py` (`Persona`, `build_options`,
`SimulatedUser.next_turn`, `check_rubrics`, `USER_PROMPT`),
`runner/agent_sdk_evals/loader.py` (`read_persona`, case keys),
`runner/agent_sdk_evals/cli.py` (per-case persona construction);
`.dev/CONTRACTS.md` §1 (case keys), §9 (judge), §12.7 (`target: simulated_user`);
`https://code.claude.com/docs/en/agent-sdk/python` (`query`,
`ClaudeAgentOptions`);
`https://platform.claude.com/docs/en/about-claude/models/overview` (Haiku 5.5's
price and context window),
`https://code.claude.com/docs/en/agent-sdk/agent-loop#budget-headroom` (the soft
cap). Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296
docs.
