# Two tiers, because one gate cannot be both cheap and thorough

A gate that runs on every pull request must be fast and nearly free, or people
stop pushing and someone eventually disables it. A suite thorough enough to
trust before a release has to pay judges and repeat each case. Those are
different jobs, so they are different workflows.

| | `pr` tier | `nightly` tier |
|---|---|---|
| Triggers | `pull_request`, manual | `schedule` cron, manual |
| Graders | `free` only (deterministic) | `free` + `judge` |
| Runs per case | 1 | 3 (`--runs`) |
| Concurrency | 1 | 1 |
| Superseded runs | cancelled | never cancelled |
| Cost | no judge calls; one session per case | sessions x runs, plus judge calls |
| Verdict | pass/fail per case | a pass *rate* per case, and pass@k |

The split is about cost and speed, not importance. The pr tier is not the
"unimportant" checks; it is the checks that can be made to cost nothing.

## What each tier can catch

The pr tier scores what is mechanically true about a run: which tools were
called and in what order, what the final text matched, whether the structured
output validated, whether the session ended for the right reason, whether the
turn and cost budgets held. That covers most regressions, because most
regressions are mechanical — a tool that stopped being called, a refusal that
stopped happening, a prompt edit that doubled the turn count.

It cannot catch quality. "Did it explain the refusal in a way a member would
understand", "did it invent a due date", "was the tone right" are judgements,
and a judgement needs a judge.

The nightly tier adds those, and adds the thing a single run can never show:
**variance**. An agent that passes four times in five is not the same agent as
one that passes five times in five, and one run cannot tell them apart. That is
why `--runs` lives here and why the nightly threshold (0.8 in the generated
config) is a rate rather than a pass/fail.

Neither tier catches what no case describes. Coverage is
`/agent-sdk:eval-review`'s question, not CI's.

## The arithmetic before you choose

From `../eval-run/references/cost-estimation.md`:

```
sessions    = cases x runs
judge calls = SUM over cases of (llm graders x judge samples) x runs
```

Twelve cases on the pr tier: 12 sessions, 0 judge calls, per pull request. The
same twelve on the nightly tier with `--runs 3`, two `llm` graders per case and
`judge.samples: 3`: 36 sessions and 216 judge calls, once a night. Say both
numbers out loud before someone commits to a schedule — 216 judge calls a night
is a different conversation from "add a nightly job".

Cost ceilings follow the same shape. `gen_workflows.py` gives the pr tier
`--max-cost-usd X` and the nightly tier `X * runs`, because the nightly tier
legitimately spends more and a ceiling that fires every night is a ceiling
nobody reads.

## What stops a tier

- **Exit 3 is neutral in both tiers.** A rejected rate limit, a cost ceiling or
  an unreachable judge means nothing was scored; nothing was scored means
  nothing regressed. Both generated workflows turn 3 into a warning annotation
  and leave the job green.
- **`--concurrency 1` in both.** Every case is a full CLI child on one
  credential; parallel sessions on a subscription token reach a rejected rate
  limit sooner, and a rejected limit costs the whole suite its verdict.
- **Only the nightly tier cancels nothing.** Two scheduled runs do not race, and
  a manual run should not kill the scheduled one whose results someone wants.

## A third tier, when it earns itself

Some projects add a `release` tier: the nightly graders with more runs, gated on
a tag. It is worth it once the nightly pass rates are stable enough that a drop
means something. Before then it is the nightly tier with a different trigger.

---

Sources: `.dev/CONTRACTS.md` §3 (tier shapes in `eval_config.json`) and §8
(exit codes); this plugin's `skills/eval-run/references/cost-estimation.md`
(the session and judge-call arithmetic, measured);
`https://code.claude.com/docs/en/agent-sdk/cost-tracking` (what a session's
cost figure is and is not).
