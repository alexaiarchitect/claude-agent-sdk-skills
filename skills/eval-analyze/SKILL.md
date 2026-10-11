---
name: eval-analyze
description: >-
  Explains Claude Agent SDK eval results and measures reliability. Reads the
  runner's result directories, reports per-case and per-grader status, places
  each failure in the trajectory-versus-answer quadrant, separates
  NOT_EVALUATED from failure and names its likely cause (judge unreachable,
  usage limit rejected, imported session without cost), reports efficiency
  (turns, tokens, cost) apart from verdicts and labels costs as estimates on a
  subscription, and computes pass@1, pass@k, pass^k and fragility across
  repeated runs. Use when asked "why did this eval fail", "show me the results",
  "what does inconclusive mean", "is my agent reliable", "compute pass@k", "how
  flaky is this case", "what did the suite cost", or "should I trust this
  suite". Don't use to run evals (use `/agent-sdk:eval-run`), to find the first
  divergence in a trace or fix the agent (use `/agent-sdk:agent-debug`), or to
  change graders and thresholds (use `/agent-sdk:eval-criteria`).
argument-hint: "[project-dir | results-dir] [--last n]"
allowed-tools: Read, Grep, Glob, AskUserQuestion, Skill, Bash(python3 *)
---

# Read Agent SDK eval results

A score is not a diagnosis. This skill turns result files into three things
someone can act on: **which quadrant** a failure is in, **why** a run was never
evaluated, and **how often** the case actually passes. Cost is reported beside
the verdicts, never as one of them.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own
directory. Use it verbatim in every command below; a sibling skill's scripts
are at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Read the results.**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/summarize_results.py <project>
   python3 ${CLAUDE_SKILL_DIR}/scripts/pass_at_k.py <project> --last 5
   ```

   `summarize_results.py` reads the **last** run directory only. When the
   question covers more than one — two runs the user wants compared, a run that
   never produced a verdict beside the one that failed — pass `--last N`, or the
   directory itself, so every run named is actually in the output. The reverse
   holds for `pass_at_k.py`: it pools whatever it is given, and pooling runs of
   different tiers or different case sets is not a reliability measurement. It
   warns when it had to, and the warning is the answer, not a footnote.

2. **Report.** Per case: statuses, the failed graders with their reasons, the
   quadrant, the never-evaluated cause, how the run ended. Lead with the count
   and the single most informative failure. Quote the cost line with its basis.

3. **Options.** Usually: triage the worst case with `/agent-sdk:agent-debug`
   (it finds the first divergence in the trace), re-run several times to see
   whether it is flaky, tighten a grader that let a wrong path through, or add a
   regression case now that the failure is understood.

4. **Confirm and hand off.** This skill does not edit anything.

## The quadrant

Trajectory-type graders (`trajectory`, `tool_used`, `tool_order`, `no_tool`,
`hook_event`) against answer-type graders (`llm`, `regex`, `final_text`,
`structured_output`). Q3 is why trajectory graders exist:

| | Answer good | Answer weak |
|---|---|---|
| **Path good** | Q1 — keep the case as a guard | Q2 — presentation, often the grader rather than the agent |
| **Path weak** | **Q3 — the dangerous one** | Q4 — a plain logic failure |

In Q3 the answer reads well, the agent skipped or reordered work to produce it,
and every answer-only grader passes it. Treat it as a real failure. A case with
graders of only one kind cannot be placed; the summary says so.

## NOT_EVALUATED

Not a regression. The run or grader never produced a verdict, and the usual
causes are: the judge call returned nothing (credential, quota, refusal); a
`rejected` rate-limit status stopped the suite (the aggregate shows
`resets_at`); an imported session has no cost or terminal fields; a
`hook_event` grader with no hook installed. The summary names the cause per
case. Full list: [result-schema.md](references/result-schema.md).

## Efficiency

Turns, input and output tokens, cache reads, cost and duration per case, as
means over the observed runs, lower is better, never a verdict. On a
subscription the cost is an API-equivalent estimate and the table says so.
`total_cost_usd` is a session running total and `model_usage` includes the
CLI's own Haiku calls; the summary reads the right fields.

## Reliability

`pass@1` is production behaviour: one attempt per request. `pass@k` is the
chance one of k attempts succeeds; `pass^k` the chance all k do. The gap
between pass@1 and pass@k is **fragility**.

| pass@1 | Verdict |
|---|---|
| ≥ 0.95 | reliable |
| ≥ 0.70 | marginal |
| below | unreliable |

A case that passes 2 runs in 5 is not "mostly working"; it fails three
requests in five. Report `pass@1` first. How many runs: 5 while iterating,
10-20 before a release, 50-100 to qualify something that spends money or
touches a person. Never-evaluated runs count as runs and not as passes, and
the report lists them.

## Decision rules

- **Read the first divergence, not the last symptom.** That is
  `/agent-sdk:agent-debug`'s job on the trace; this skill tells you which trace.
- **A flaky case and a broken case need different fixes.** Establish which
  first: `/agent-sdk:eval-run --runs 5`.
- **Never average away the variance.** Runs are kept separate on disk for this.
- **Calibrate occasionally.** Sample passing runs with `calibration_sample.py`
  and check you agree they deserved to pass; leniency hides in `llm` graders.

## References

| Question | File |
|---|---|
| The result and aggregate files' shape, every status and cause | [result-schema.md](references/result-schema.md) |
| Quadrant and divergence in depth | [diagnosis.md](references/diagnosis.md) |
| pass@k, pass^k, fragility, run counts | [reliability.md](references/reliability.md) |
| Human calibration: cadence, sample size, what to do on disagreement | [calibration.md](references/calibration.md) |
| Reading efficiency and cost honestly | [efficiency.md](references/efficiency.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/summarize_results.py <path> [--last N] [--case NAME] [--json]` | per-case diagnosis, never-evaluated causes, efficiency table | 0 passed, 1 failures, 3 only never-evaluated, 2 nothing to read |
| `scripts/pass_at_k.py <path> [--last N] [--case NAME] [--k 1,3,5] [--json]` | reliability across runs | 0 all reliable, 1 not, 2 nothing to read |
| `scripts/calibration_sample.py <path> [--n 5] [--seed 0] [--json]` | passing runs for human review, judged cases first | 0, 2 nothing to read |

## Completion checklist

- [ ] Every failing case has a quadrant, or the reason it cannot be placed.
- [ ] NOT_EVALUATED runs were reported separately, with a likely cause.
- [ ] Cost was reported with its basis, and as an estimate on a subscription.
- [ ] Failed graders were named with their reasons, not counted.
- [ ] Where reliability matters, `pass@1` was reported, not just `pass@k`.
- [ ] The user was pointed at the next skill rather than left with numbers.
