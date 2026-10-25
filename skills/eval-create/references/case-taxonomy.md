# Five categories, and what each one proves

`category:` is not a label for tidiness. It is the claim the case makes, and a
suite that is missing a category is missing that claim entirely.

| Category | The question it answers | What it cannot answer |
|---|---|---|
| `happy` | does the agent do its job when everything is available and the request is clear? | anything about pressure, ambiguity or restraint |
| `edge` | what happens at the boundary — nothing found, two matches, an unavailable item, a malformed argument? | whether the agent holds a rule it was *told* to hold |
| `adversarial` | does the agent hold the line when the request, the tool results or the user push against it? | whether the normal path still works |
| `memory` | does a session carry context from one turn to the next? | anything a single-turn case already covers |
| `regression` | does a bug someone actually saw stay fixed? | anything not yet observed |

## happy

The floor. Without one, every other case is measuring the failure modes of
something that may not work at all. One or two is usually enough: more happy
cases buy very little, because they fail together.

A happy case is the natural home for a `trajectory` grader under `IN_ORDER`:
you are proving the agent *can* take the path, and calls in between are not a
defect.

## edge

Boundaries are where a model improvises, and improvisation is what regresses on
a model upgrade. The edges worth a case are the ones with a *defined* answer:

* the lookup returns nothing — does it say so or invent a result?
* two records match — does it ask, or pick one silently?
* the tool returns an error — does it retry, report, or pretend it succeeded?
* an argument is missing — does it ask the user or guess?

An edge case rarely has one right trajectory, so state the expectation in words
with an `llm` grader and keep a `terminal` grader beside it.

## adversarial — the category that decays

Every refusal rule in the system prompt needs a case that *attempts the
forbidden thing*. This is the n+1 rule: n rules need n cases that exercise them
plus one per refusal that tries to break it.

The weight matters. The plugin's target is **adversarial cases at 20% of the
suite or more**, because happy cases are the easy ones to write and a suite
drifts towards them without anyone deciding to. `coverage_matrix.py` reports
the ratio; it is advice, not a gate.

An adversarial case is scored against the **trace**, never only the reply:
`no_tool`, or a `trajectory` under `EXACT`, or `tool_used` with `max: 0`. A
judge reading the final message grades the apology, and a model that calls the
tool and then apologizes passes. See
[adversarial-cases.md](adversarial-cases.md).

## memory

Multi-turn, via `turns:` (scripted) or `simulated_user:` (persona-driven). The
claim is that turn two acted on what turn one established — so the cheap
evidence is a `tool_order` grader across the two turns, and the expensive
evidence is an `llm` grader on whether the final reply refers to something only
turn one mentioned.

A single-turn case cannot distinguish a memory failure from a prompt failure,
which is why this is its own category rather than a tag on `edge`.

## regression

One case per bug that was actually observed. The prompt is the report; the
grader is the symptom. A regression case is the only kind that should be
written *after* a failure rather than before, and the only kind where a
`regex` `not_contains` on a literal string is the right first grader.

`trace_to_case.py` writes these from a saved trace, which is usually how a bug
arrives: someone has the run that went wrong.

## Choosing, in one line each

* Proving it works → `happy`.
* Proving it degrades gracefully → `edge`.
* Proving it holds a rule under pressure → `adversarial`.
* Proving the session remembers → `memory`.
* Proving a specific bug stays dead → `regression`.

A case that fits two categories is usually two cases. One behaviour per case is
what makes a failure readable: when the case fails, its name is the diagnosis.

## Where the first cases come from

From **real usage**, not invention. Anthropic's Agent SDK write-up (2025-09-29)
recommends building the test set from how customers actually use the agent and
reading failures first; the fold-subagents article (2026-10-22) says "Even a set
of 10 golden examples is enough to start". So: a handful of `happy` cases
frozen from real requests, an `edge` or `regression` case for every failure you
have read, then the restraint cases. Run each case more than once before
trusting it (`runs:` above 1, or `--runs`): that article's fold broke a
process in only one run out of two. Size is not the goal; a small set taken
from traffic beats a large invented one.

Sources: `lib/agent_sdk_skills/evalcase.py` (`CATEGORIES`, `EVC030`, `EVC031`,
the restraint checks behind `EVC041`); `lib/agent_sdk_skills/coverage.py`
(`shape`, the 20% adversarial target, `n_plus_one_gaps`); `.dev/CONTRACTS.md`
§1 (the `category` key) and §2 (grader types per target);
<https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk>
("Building agents with the Claude Agent SDK", 2025-09-29, the test set built from
customer usage, read failures first);
<https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop>
("Building agents: When to fold subagents into your main agent loop",
2026-10-22, ten golden examples to start, run each task more than once).
Re-read 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
