# Reliability: pass@1, pass@k, pass^k and fragility

An LLM agent is not deterministic, so one green run is one sample. The suite
answers "how often does it work, and where is it fragile", and it can only
answer with repeated runs kept separate. The runner never averages: `--runs N`
writes N runs per case, and several result directories add up.

## The numbers

- **pass@1** — the pass rate: production behaviour, one attempt per request.
- **pass@k** — the probability that at least one of k attempts passes,
  estimated without bias from n runs of which c passed:
  `1 − C(n−c, k) / C(n, k)`.
- **pass^k** — the probability that all k attempts pass: `rate^k`. The number
  for anything that must not fail even once.
- **fragility** — pass@k(max) minus pass@1: how much the agent depends on
  retries.
- **suite pass@1** — the share of whole-suite runs in which every case passed.

| pass@1 | Verdict |
|---|---|
| ≥ 0.95 | RELIABLE |
| ≥ 0.70 | MARGINAL |
| below | UNRELIABLE |

A case that passes 2 runs in 5 is UNRELIABLE, whatever pass@5 says. Report
pass@1 first and treat a high pass@k as a statement about retries, not quality.

## How many runs

| Goal | Runs | What it can tell apart |
|---|---|---|
| iterating | 5 | "usually works" from "often fails" |
| pre-release | 10–20 | 95% from 90% |
| qualification | 50–100 | something that spends money or touches a person |

Fewer than 3 runs cannot measure reliability at all. On a subscription each
run draws on plan usage limits; the arithmetic in `/agent-sdk:eval-run`'s
cost-estimation reference applies, and a `rejected` rate limit mid-series
leaves never-evaluated runs, which count as runs and not as passes.

## Reading the table

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pass_at_k.py <project> --last 5 --k 1,3,5
```

- **Flaky** (some passes, some failures): the first thing to investigate, with
  `/agent-sdk:agent-debug` on a failing trace and a passing trace side by side.
- **Never-evaluated runs**: listed separately; fix the cause before reading
  the rate.
- **Missing from some runs**: a case was added between runs, or a run stopped
  early; the warning names them.

## Where the samples come from

`results.samples_by_case` merges the runs inside each result file with the runs
across directories, so `--runs 3` once and `--runs 1` three times are the same
three samples. `--last N` limits the directories read.

---

Sources: this plugin's `lib/agent_sdk_skills/passk.py`; the pass@k estimator is
the standard unbiased form; the pass@k versus pass^k distinction follows
`https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents`.
