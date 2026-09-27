# The maturity ladder, and how to climb one rung

`assess_maturity.py` reports a level from L0 to L5. Every level is defined by a
file on disk, never by intent, so it is a measurement rather than an opinion.

| Level | Name | Evidence the script looks for |
|---|---|---|
| L0 | Vibe checks | no cases under `evals/` |
| L1 | Cases exist | one or more `evals/<case>/prompt.md` |
| L2 | Run at least once | a `evals/results/<timestamp>/` directory **and** a runner copy under `evals/runner/` |
| L3 | Gated automatically | a workflow whose step runs the runner, or `tests/test_evals.py` |
| L4 | Judged and repeated | `eval_config.json` has both `pr` and `nightly` tiers, the nightly tier lists `judge`, and either a scheduled workflow exists or a result directory holds 3+ runs per case |
| L5 | Reliability tracked | 3+ result directories and 5+ samples for at least one case, so pass@1 per case is a measurement |

## The ladder is not strictly cumulative

`evals/results/` is gitignored in any sane project, and CI uploads it as an
artifact rather than committing it. So a repository with a real gate normally
shows **no local results at all**: L3 with no evidence for L2 is the healthy
state, not a contradiction. The script reports the highest level whose own
evidence is present and lists anything missing below it as an observation,
saying which absences are expected.

This matters when reading the report: "no evidence for L2" next to a passing CI
badge means results are gitignored, not that the suite has never run.

## What each rung buys

**L0 to L1** — the first case turns "it looked right" into a claim someone else
can check. Two cases is the real floor: one happy path and one refusal, because
a suite that can only pass is not a suite.

**L1 to L2** — running it once is where most surprises live: the entry point is
not importable, the model was never set, the grader matches nothing. None of
that is visible until the runner has actually executed.

**L2 to L3** — a gate nobody has to remember. This is the largest single jump in
value on the ladder, and the cheapest: the pr tier costs one session per case
and no judge calls. A project that stops here has most of the benefit.

**L3 to L4** — judges and repetition. Until a case has run more than once, "it
passes" means "it passed once". The nightly tier is where quality judgements and
variance both become visible.

**L4 to L5** — time. Three result directories with five samples each is the
point at which a pass rate moving from 1.0 to 0.8 is a signal rather than noise,
and reliability regressions become findable before users find them.

## The next step, per level

| At | Do this next |
|---|---|
| L0 | `/agent-sdk:eval-create` — one happy path and one refusal |
| L1 | `/agent-sdk:eval-run --tier pr`, then `/agent-sdk:eval-analyze` |
| L2 | `gen_workflows.py <project> --tier pr`, or the pytest gate if the project already runs pytest in CI |
| L3 | `gen_workflows.py <project> --tier nightly`, plus a `nightly` tier listing `judge` (`/agent-sdk:eval-criteria`) |
| L4 | let the nightly tier accumulate, then read pass@k with `/agent-sdk:eval-analyze` |
| L5 | close the loop: every production failure becomes a case (`/agent-sdk:agent-debug` imports the session) |

Take one rung at a time. A project that jumps from L1 to a nightly judged suite
usually ends up with an expensive job nobody reads, because the cheap gate that
would have caught the mechanical regressions was never built.

## What the level does not say

It says nothing about **coverage**. A project can reach L5 with two cases that
both test the happy path, and the number will look excellent. Coverage is
`/agent-sdk:eval-review`'s question (`coverage_matrix.py`), and it is worth
asking at every level, not just at the top.

---

Sources: `.dev/CONTRACTS.md` §3 (tiers) and §6–§7 (result and aggregate shapes
the script reads); this plugin's `lib/agent_sdk_skills/results.py`
(`load_all`, `samples_by_case`) and `lib/agent_sdk_skills/layout.py`
(`detect_layout`, which finds the cases, workflows and pytest gate).
