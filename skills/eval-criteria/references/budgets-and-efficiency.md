# Budgets: what to cap, what to measure, and what not to assert

A `budget` grader is the cheapest way to notice an agent getting slower or more
expensive, and the easiest grader to write wrongly — because three of its
fields do not mean what their names suggest.

## The ceilings

| Field | Compares against | Note |
|---|---|---|
| `max_cost_usd` | the session's final `total_cost_usd` | a running total, not a per-turn sum |
| `max_turns` | `result.num_turns` | **not** the `max_turns` option |
| `max_input_tokens` | `usage.input_tokens` | |
| `max_output_tokens` | `usage.output_tokens` | |
| `max_cache_read_tokens` | `usage.cache_read_input_tokens` | grows with turns |
| `max_cache_creation_tokens` | `usage.cache_creation_input_tokens` | |
| `max_duration_ms` | `result.duration_ms` | wall clock, includes tool latency |

At least one is required; several may be set.

## `max_turns` is not a hard cap

`ClaudeAgentOptions.max_turns=1` was measured producing `num_turns=2`. The
option limits the *agent loop*; `num_turns` counts messages, and the two do not
line up. So:

* a `budget` grader with `max_turns` asserts "this run stayed within N turns",
  against its own number;
* to assert that the limit actually fired, use `terminal` with
  `subtype: error_max_turns` or `terminal_reason: max_turns`.

Writing `max_turns: 1` in a budget grader because the option says 1 produces a
grader that fails every time.

## Cost is a delta, and on a subscription it is an estimate

`ResultMessage.total_cost_usd` is computed client-side from a bundled price
table. Two consequences:

* **It is a session running total.** In a multi-turn case the runner records
  `cost_delta` per turn; the grader reads the case total, which is the last
  `total_cost_usd` of the session.
* **On a subscription nothing is billed.** The figure is an API-equivalent
  estimate; what the run actually spends is plan usage. Reports label the
  basis, and a budget grader still works — it is comparing runs against each
  other, which is what you want either way.

## `informational: true`

A budget grader with `informational: true` records the number and never fails
the case. That is the right default for most suites:

* cost drifts for reasons outside the agent — a price-table update, a model
  change, a longer tool result;
* a hard cost gate that fires on a 5% drift trains people to raise the ceiling
  rather than look at the cause.

Use a *failing* budget grader when the ceiling is a product requirement ("this
must answer in under ten seconds") rather than a health signal. Use an
informational one to build the series that `/agent-sdk:eval-analyze` turns into
an efficiency table.

There is a second ceiling that is not a grader at all:
`max_budget_usd` in the agent's own options, and `--max-cost-usd` on the
runner. Those stop a run. A grader scores one that finished.

## The efficiency table

Lower is better, and the comparison is between runs of the same case rather
than between cases:

| Signal | Reading it |
|---|---|
| `num_turns` climbing | the agent is looping, or the tool results are unhelpful |
| `output_tokens` climbing | the replies are getting longer, not better |
| `cache_read_input_tokens` climbing | the context is growing — expected in multi-turn, a smell in single-turn |
| `duration_api_ms` ≫ `duration_ms` | time is going into model calls, not tools |
| `duration_ms` ≫ `duration_api_ms` | time is going into tools; a mock's `latency_ms`, or a slow backend |

`usage.cache_creation` in the raw payload is a nested dict of ephemeral TTL
buckets, never a number — read `cache_creation_input_tokens` instead.

## Where budgets belong

* **Per case**, as an informational grader, on the two or three cases that
  represent normal use. Putting one on every case adds noise.
* **Per run**, as `budget.max_cost_usd_per_run` in the config — a guard against
  a loop, not a quality gate.
* **Per suite**, as `budget.max_cost_usd_total` — the number that stops a
  nightly run from spending a week's quota because one case started looping.

`on_not_evaluated: warn` keeps a usage limit from reading as a regression:
nothing was scored, so nothing regressed, and the suite exits 3.

Sources: `lib/agent_sdk_skills/graders.py` (`BUDGET_CEILINGS`,
`BUDGET_USAGE_KEYS`); `lib/agent_sdk_skills/budget.py` (the efficiency table
and the cost basis labels); `.dev/CONTRACTS.md` §2.1 (the `max_turns`
measurement, the usage-key mapping, the cost delta) and §5.2 (`ResultMessage`
fields as measured); https://code.claude.com/docs/en/agent-sdk/python
(`ResultMessage.usage`, `total_cost_usd`, `max_budget_usd`);
https://code.claude.com/docs/en/agent-sdk/cost-tracking (what the figure
counts).
