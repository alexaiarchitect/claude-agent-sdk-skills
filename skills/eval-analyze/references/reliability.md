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

## Before you believe a small difference

Run-to-run variance is not only the model. Anthropic's infrastructure-noise
study (2026-02-05) moved a benchmark 6 points by changing resource limits
alone, and saw pass rates drift with the time of day. So, before calling a
change an improvement or a regression:

- the two result sets must share a **documented resource configuration**
  (machine or container limits, concurrency, model id, SDK and CLI versions);
- the samples should come from **several times and days**, not one burst
  (`--last N` over a week of nightlies);
- a difference **below 3 percentage points** is noise until both of the above
  hold — the study's words: "leaderboard differences below 3 percentage points
  deserve skepticism until the eval configuration is documented and matched".
  With 10 runs a single flip is 10 points, so small suites need more runs, not
  finer reading.

**Hold `effort` fixed.** `effort` (`low` to `max`) is a variable, not a
setting to leave to chance. *Using Claude Code: Spending your effort*
(2026-09-25, article #38, about Claude Code's `/effort`) found that higher
effort mostly buys more verification and edge-case testing — it helped
edge-case-heavy tasks and did not fix a wrong approach — and that on a loosely
specified task it changed the scope of the work. Two result sets run at
different effort levels are two experiments. Set `effort` explicitly in the
agent's options (and in `overrides` when a case needs its own), and record it
with the resource configuration above; the result file's `config` does not
carry it.

## Keeping a change: train and held-out both improve

Hillclimbing on an eval (edit, re-run, keep or revert) overfits unless the method
guards against it. Lance Martin's write-up (2026-09-28; the `claude-api` skill's
`hillclimb` command, not the SDK) sets the rules this plugin follows:

- first check that run-to-run noise is smaller than the smallest improvement worth
  acting on; if not, add repeats or cases before changing anything;
- change **one attributable surface per round** (a prompt section, a tool
  description, the model or effort), so the score moves because of that surface;
- split the cases into a train set the person or agent editing may read and a
  **held-out (test) set** it never sees (`/agent-sdk:eval-create`, `case-taxonomy.md`);
- **keep a change only when train and held-out both improve**; revert on a
  regression, and treat train up with held-out flat as overfitting;
- a gain within noise is not a gain: do not merge it.

## Where the samples come from

`results.samples_by_case` merges the runs inside each result file with the runs
across directories, so `--runs 3` once and `--runs 1` three times are the same
three samples. `--last N` limits the directories read.

---

Sources: this plugin's `lib/agent_sdk_skills/passk.py`; the pass@k estimator is
the standard unbiased form; the pass@k versus pass^k distinction follows
<https://www.anthropic.com/research/demystifying-evals-for-ai-agents>
("Demystifying evals for AI agents", 2026-01-09, pass@k versus pass^k);
<https://www.anthropic.com/research/infrastructure-noise> ("Infrastructure noise
in agentic coding evals", 2026-02-05, resource configuration, repeats across
times and days, the 3-point threshold);
<https://claude.dev/blog/automating-eval-design-and-hillclimbing/> ("Automating eval
design and hillclimbing with Claude", 2026-09-28, one attributable surface per change, keep a change only when train and held-out both improve, noise below the smallest worthwhile gain; written for the `claude-api`
skill's `hillclimb` command, cited for its method).
<https://claude.dev/blog/spending-your-effort/> ("Using Claude Code: Spending
your effort", 2026-09-25, effort as how much verification and edge-case testing
Claude does, scope changes on loose specs; Claude Code's `/effort`, mapped to the
SDK's `effort`).
Re-read 2026-11-08 against claude-agent-sdk 0.2.179 / Claude Code 2.1.319 docs.
