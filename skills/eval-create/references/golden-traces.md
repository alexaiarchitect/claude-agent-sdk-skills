# A reviewed trace is a specification

The cheapest good case is one you have already watched work. Run the agent,
read the trace, decide that the path it took is the path you want defended,
and freeze it. `trace_to_case.py` does the freezing; the review is the part
that matters and it is not automatable.

## The workflow

```bash
# 1. get a trace: a run you watched, or one already in evals/results/
python3 ${CLAUDE_SKILL_DIR}/../eval-run/scripts/run_evals.py <project> --tier pr

# 2. read it before freezing it
python3 ${CLAUDE_SKILL_DIR}/../agent-debug/scripts/analyze_trace.py --trace <trace>

# 3. freeze
python3 ${CLAUDE_SKILL_DIR}/scripts/trace_to_case.py <trace> --name reserve-available \
        --project <project> --match IN_ORDER
```

The script writes three files: `prompt.md` (the first user event, or every user
event as `turns` when there are several), a `trajectory` grader carrying the
call sequence, and a `terminal` grader carrying how the run ended.

## Read it before you commit it

Everything in the trace becomes a requirement. The things to delete:

* **A redundant lookup.** The agent checked twice because the first result
  scrolled out of its attention. Freeze it and every future run must also do it
  twice.
* **A retry after an error.** The mock was slow that day. The retry is now
  mandatory.
* **A tool called with a value the model invented.** Under `args_match: subset`
  that invented value is part of the expectation.
* **Calls in an order that happened to work.** If the order does not matter,
  say so: `ANY_ORDER`, or drop the trajectory grader and assert the two calls
  separately with `tool_used`.

A trace that passes is not the same as a path worth defending. The question to
ask about each call is: *would I argue for this in code review?*

## EXACT versus IN_ORDER

| Mode | Allows | Use it when |
|---|---|---|
| `EXACT` | nothing else, in no other order | the case is about restraint: these calls and no others |
| `IN_ORDER` | other calls in between | the case is about capability: the agent can do the job |
| `ANY_ORDER` | any order, other calls allowed | the calls are independent and order is not the claim |

`IN_ORDER` is the default because it is the tolerance a capability case wants.
`EXACT` over a long path is brittle — every future run must reproduce it
exactly — so `trace_to_case.py` warns when you ask for `EXACT` over more than
six calls.

For an adversarial case, `EXACT` is often right precisely *because* it is
strict: "looked up, then answered, and called nothing else" is the claim.

## Synthetic calls are excluded

Two tool names in a trace are not decisions the agent made:

* **`StructuredOutput`** — how the CLI delivers an `output_format` result. It
  appears as a `ToolUseBlock` on every structured-output run.
* **`ToolSearch`** — deferred MCP tool loading. Measured as a real, first call
  on every MCP-tool case.

Both are infrastructure, and both vary with how the CLI is configured on the
machine. A trajectory that includes them fails elsewhere for reasons that have
nothing to do with the agent. `trajectory.calls_from_events` drops them, so
`trace_to_case.py` never writes them, and `tool_used` / `no_tool` /
`tool_order` skip them too — unless a grader names one explicitly, which is how
a case asserts that structured output *was* produced.

## Imported sessions

`/agent-sdk:agent-debug` can import a Claude Code session JSONL into the same
trace shape, so a real conversation can become a case. Two caveats:

* A session from `claude -p` carries no `result` event, so a `terminal` or
  `budget` grader over it reports `NOT_EVALUATED` rather than passing. Sessions
  the SDK itself produced do carry a cost line.
* Session transcripts contain whatever the user typed. Read before committing.

## When not to freeze

If the run you have is the *bug*, do not freeze its trajectory — freeze its
prompt. Write the case by hand with the expectation you want, watch it fail,
then fix the agent. A golden trace of a broken run is a test that asserts the
bug.

## How many, and from where

Start small and real. Anthropic's fold-subagents article (2026-10-22) says
"Even a set of 10 golden examples is enough to start" and adds two habits worth
copying. **Run each task more than once**: failures are intermittent, and the
break it describes appeared in one run out of two, so freeze a trace only after
the case passes repeatedly. **Timestamp the important events** in production
(a handoff, a tool failure, a user correction) so an interaction that is hard
to reproduce can be found later and replayed as a targeted eval — here, a
production session converted with `agent-debug/scripts/import_session.py` and
frozen with `trace_to_case.py`.
The Agent SDK write-up (2025-09-29) adds the source: build the set from real
customer usage, and read the failures before the passes.

Sources: `lib/agent_sdk_skills/trajectory.py` (`calls_from_events`, the match
modes, `Call` normalization); `lib/agent_sdk_skills/trace.py` (`load_trace`,
`load_session`, the `synthetic` flag); `.dev/CONTRACTS.md` §2.1, §5, §5.3 and
§12.1 (`SYNTHETIC_TOOLS` including `ToolSearch`, and what an imported session
carries); https://code.claude.com/docs/en/agent-sdk/python (`ToolUseBlock`,
`ResultMessage`);
<https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop>
("Building agents: When to fold subagents into your main agent loop",
2026-10-22, ten golden examples, repeated runs, timestamped events replayed as
targeted evals);
<https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk>
("Building agents with the Claude Agent SDK", 2025-09-29, evals from customer
usage). Re-read 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312
docs.
