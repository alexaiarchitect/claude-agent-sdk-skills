# Calibration: checking that passes deserved to pass

Criteria that are too lenient produce a green suite and a bad agent, and
nothing in the system notices. A judge that agrees with everything, a `regex`
that matches too much, a `trajectory` grader with `IN_ORDER` where `EXACT` was
meant: each makes a wrong run look right. The only defence is a person reading
a sample of passing runs and asking "would I have passed this?".

## Cadence and sample size

| When | Sample |
|---|---|
| after writing or changing an `llm` grader | 5 passing runs of the cases it grades |
| before a release | 10 passing runs across the suite, judged cases first |
| after a model change | 10 passing runs, compared with the previous model's |
| routinely | 5 passing runs a week, rotating cases |

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/calibration_sample.py <project> --n 5 --seed 7
```

The sample prefers runs graded by an `llm` grader, because that is where
leniency hides, and prints the trace path with every grader's verdict and
reason beside it.

## What to do on disagreement

- **The judge passed something you would fail.** Tighten the criteria: add a
  FAIL clause naming the behaviour, raise `samples`, or add a free grader that
  pins the observable fact (`no_tool`, `trajectory`, `regex`).
- **A free grader passed something you would fail.** The assertion is too
  loose: `contains` where `exact` was meant, a lenient match type on a refusal
  case, a `budget` ceiling nobody can hit.
- **You would pass something the suite failed.** Usually Q2: the grader is
  measuring wording. Loosen the grader, not the agent.

Record disagreements as new cases or grader changes, never by editing the
trace or the result.

## Judge hygiene

- the judge model is fixed and different from the agent's model, so scores
  stay comparable across agent changes;
- `samples` of 3 with a majority vote; a 2-1 split is worth reading;
- the judge runs isolated (`setting_sources=[]`, no tools, low effort), so it
  judges the transcript and nothing else.

---

Sources: this plugin's `skills/eval-analyze/scripts/calibration_sample.py` and
`.dev/CONTRACTS.md` §9 (judge options); the grader-critique practice follows
the `skill-creator` grader in `https://github.com/anthropics/skills`.
