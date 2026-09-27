# Efficiency: turns, tokens, cost, and what they are not

Efficiency numbers describe how expensive a run was, not how good. They are
reported in their own table, lower is better, and none of them passes or
fails a case unless a `budget` grader says so.

## The columns

| Column | Source | Notes |
|---|---|---|
| turns | `result.num_turns` | a `max_turns` option is not a hard cap; assert on `terminal_reason` instead |
| input / output tokens | `result.usage.input_tokens`, `output_tokens` | main loop only; subagent tokens are in `model_usage` |
| cache read | `result.usage.cache_read_input_tokens` | high cache reads with low input tokens is the healthy shape |
| cost USD | `result.total_cost_usd` | a session running total; per-turn deltas are in the trace |
| duration | `result.duration_ms` | wall clock, noisy |

## Reading cost honestly

- **Basis.** `api_key` means an estimate of the bill; `subscription` means an
  API-equivalent estimate and the real limit is plan quota; `provider` means
  that cloud's price table. The table footer says which.
- **Running total.** `total_cost_usd` accumulates across turns of one session.
  A two-turn case's cost is the last value; the trace records `cost_delta_usd`
  per turn.
- **Models you did not ask for.** `model_usage` lists every model the CLI
  used, including its own Haiku calls for internal work. The model that
  answered is on each `assistant_text` event.
- **Isolation.** A run without `setting_sources=[]` carries the developer's
  settings and `CLAUDE.md` in every prompt; the measured difference was
  seventeen-fold. The trace's `init` event records what was applied.

## When a number should become a grader

Add a `budget` grader when a ceiling is a requirement: a support agent that
must answer within N turns, a batch job with a per-item cost. Mark it
`informational: true` while establishing the baseline, then set the ceiling
from the observed mean plus headroom. Compare runs of the same case, same
model, same isolation; anything else compares two different experiments.

---

Sources: `https://code.claude.com/docs/en/agent-sdk/cost-tracking` (`usage`,
`model_usage`, running totals), measurements in `.dev/VERIFIED-FACTS.md`; this
plugin's `lib/agent_sdk_skills/results.py` (`efficiency_rows`).
