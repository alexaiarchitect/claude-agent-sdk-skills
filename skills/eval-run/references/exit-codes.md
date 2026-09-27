# Exit codes, and how a gate should treat them

The runner and every plugin script share one contract:

| Code | Meaning | A CI gate should |
|---|---|---|
| 0 | every selected case reached the tier's threshold | pass |
| 1 | at least one case below threshold (or never evaluated, under `--not-evaluated fail`) | fail |
| 2 | the environment could not run it: no runner copy, no interpreter with the SDK, the agent failed to import, no credential, no model | fail, and fix the environment rather than the agent |
| 3 | inconclusive: only never-evaluated runs, a cost ceiling reached, or a `rejected` rate-limit status | neither: mark the job as needing a retry after the reset, or fail if the pipeline cannot express "retry" |

## Why three is not one

"The judge could not be reached" and "the plan's usage limit was hit" are
different problems from "the agent regressed", and a gate that turns them into
red makes people stop trusting red. The aggregate carries the reason
(`stopped.reason`, the last `rate_limit` status and `resets_at`), and the
summary script prints it.

## Where the verdict comes from

`run_evals.py` reads the results directory it asked the runner to write, not
the runner's stdout. The order it decides in:

1. runner exit 2, or no directory and no JSON → 2;
2. any `FAILED` run → 1;
3. the runner stopped early (`stopped` in the aggregate) or exited 3 → 3;
4. any `NOT_EVALUATED` run → 1 under `--not-evaluated fail`, else 3;
5. passed runs and nothing else → 0.

`INFORMATIONAL` runs (a budget grader marked informational) never move the
code.

## Status vocabulary

`PASSED`, `FAILED`, `NOT_EVALUATED`, `INFORMATIONAL`, always counted
separately. A never-evaluated run names its cause in the summary: judge
unreachable, usage limit rejected, imported session without cost fields, a
`hook_event` grader with no hook installed.

---

Sources: this plugin's `lib/agent_sdk_skills/report.py` and
`skills/eval-run/scripts/run_evals.py`; rate-limit semantics from the measured
`RateLimitEvent` in `.dev/VERIFIED-FACTS.md` and
`https://code.claude.com/docs/en/agent-sdk/cost-tracking`.
