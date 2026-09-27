# Result files

The runner writes one directory per invocation, `evals/results/<timestamp>/`:

```
<case>.<n>.trace.jsonl     one per run: the event record
<case>.result.json         one per case: verdicts per run
aggregate.json             one per invocation: totals, versions, credential, rate limit
```

## `<case>.result.json` (schema `agent-sdk-skills.result/1`)

| Key | Meaning |
|---|---|
| `case`, `category` | the case directory name and its frontmatter category |
| `config` | `tier`, `model`, `judge`, `isolation`, `cost_basis`, `sdk_version`, `cli_version` |
| `runs[]` | `run`, `trace`, `status`, `graders[]`, `result`, `rate_limit` |
| `runs[].graders[]` | `name`, `type`, `status`, `score`, `votes` (llm), `reason` |
| `runs[].result` | `subtype`, `terminal_reason`, `num_turns`, `duration_ms`, `total_cost_usd`, `cost_delta_usd`, `usage{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, ...}` |
| `summary` | `passed`, `failed`, `not_evaluated`, `informational`, `pass_rate`, `cost_usd` |

## `aggregate.json` (schema `agent-sdk-skills.aggregate/1`)

`tier`, `started`, `finished`, `cases[]` (name, pass_rate, pass_at_k, cost,
not_evaluated), `totals` (cases, runs, passed, failed, not_evaluated,
cost_usd, cost_basis, duration_ms), `exit_code`, `runner_version`,
`sdk_version`, `cli_version` (the bundled CLI, which may differ from the one on
PATH), `credential` (kind, auth_method, subscription_type, api_provider,
api_key_source; never an email or org id), `rate_limit` (last status and the
five-hour and seven-day windows), and `stopped` when the run ended early
(`reason`: `usage_limit`, `cost_ceiling`; `resets_at`).

## Statuses

| Status | Meaning | Counted as |
|---|---|---|
| `PASSED` | every grader in the tier met its threshold | a pass |
| `FAILED` | at least one grader failed | a failure |
| `NOT_EVALUATED` | a grader or the run could not produce a verdict | neither; listed with its cause |
| `INFORMATIONAL` | a `budget` grader marked `informational` reported a value | nothing |

## Causes of NOT_EVALUATED

| Cause | Where to look | Fix |
|---|---|---|
| judge call returned no verdict | `graders[].type == llm`, `reason` | credential, judge model, quota |
| rate limit `rejected` | `runs[].rate_limit.status`, aggregate `stopped` | wait for `resets_at`; `--wait-for-reset` |
| API 429 | `result.api_error_status` | as above |
| imported session | no `result` event in the trace | run the case under the runner to get cost and terminal fields |
| `hook_event` grader with no hook | grader reason | name an event the runner installs a hook for |
| run error before any grader | `runs[].error` | read the trace's last `system` event |

## Terminal fields

`subtype`: `success`, `error_max_turns`, `error_during_execution`,
`error_max_budget_usd`. `terminal_reason`: `completed`, `max_turns`,
`aborted_streaming`, `aborted_tools`, `api_error`, or null. `max_turns` is not
a hard cap on `num_turns` (a cap of 1 measured two turns); assert on
`terminal_reason`, not on the count.

---

Sources: this plugin's `.dev/CONTRACTS.md` §5–§7 and
`lib/agent_sdk_skills/results.py`; SDK fields per
`https://code.claude.com/docs/en/agent-sdk/python` (`ResultMessage`) and
`https://code.claude.com/docs/en/agent-sdk/cost-tracking`.
