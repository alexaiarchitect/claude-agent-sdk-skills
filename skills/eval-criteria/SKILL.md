---
name: eval-criteria
description: >-
  Chooses and writes the graders and the eval config for a Claude Agent SDK
  project. Prints the catalog of twelve grader types with what each proves and
  what it cannot; writes one grader file with the exact fields its type
  requires and a prose body; writes PASS/FAIL judge criteria and lints them for
  vague words, compound claims, unobservable assertions and a missing FAIL
  clause; writes evals/eval_config.json with the model pin, isolation defaults,
  judge block, tiers and budgets; and validates a config against the installed
  runner copy before a run costs anything. Use when the user says "which grader
  should I use", "write a rubric", "the judge keeps disagreeing", "add a budget
  check", "set up the eval config", "pick a judge model", "validate my config",
  or asks what a grader actually proves. Don't use to write cases (use
  `/agent-sdk:eval-create`), to validate whole suites and coverage (use
  `/agent-sdk:eval-review`), to run or score anything (use
  `/agent-sdk:eval-run`), or to interpret results (use
  `/agent-sdk:eval-analyze`).
argument-hint: "[project-dir] [--type grader-type]"
allowed-tools: Read, Write, Edit, Grep, Glob, AskUserQuestion, Skill, Bash(python3 *)
---

# Choose graders and write the eval config

A grader is an argument, not a checkbox: it proves one thing and leaves the
rest open, and a suite of graders that each prove something narrow with nothing
covering the gap between them passes a broken agent. So the question this skill
keeps asking is not "which grader checks this?" but "what would still be wrong
if this passed?".

`${CLAUDE_SKILL_DIR}` is this skill's directory; a sibling skill's scripts are
at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Discover.** What the config says and what the existing graders assert:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/validate_config.py <project>
   python3 ${CLAUDE_SKILL_DIR}/scripts/grader_info.py
   python3 ${CLAUDE_SKILL_DIR}/../eval-review/scripts/crosscheck_tools.py <project>
   ```

   The cross-check is what makes the recommendation this agent's rather than
   generic: it prints the agent's real tool names, read from its code, and a
   grader naming a tool the agent does not have asserts nothing. Never name a
   tool that no script output shows.

2. **Report.** The config's model pin, judge model and samples, tier split and
   budgets, plus any `CFG` findings. For a grader question, show the candidate
   types with their "does not prove" line **from the catalog, in the catalog's
   own terms** — that column is the decision, and a gap written from scratch is
   an opinion where the catalog had a fact. Carry the type's line first; then,
   if it helps, say what it means for this case.

3. **Options.** Two to four, all `free` to *write*. Say which of them adds a
   `judge`-tier cost when the suite next runs: one `llm` grader is
   samples x runs judge calls per case, every night.

4. **Confirm** with `AskUserQuestion`.

5. **Act.** `--dry-run`, show the plan, write. The dry run happens **even when
   the user has already approved writing**: its write plan is the record of what
   is about to change; pre-approval skips the *confirmation*, not the dry run.
   Graders come from `gen_grader.py` and the config from `gen_config.py`, never
   hand-written. Then fill in the placeholders with Edit: a grader left with
   `TODO-tool` or a TODO pattern asserts nothing, and the script exits 1 to say
   so.

6. **Verify.**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../eval-review/scripts/validate_cases.py <project>
   ```

## Choosing a grader

| The question | Grader | What still needs covering |
|---|---|---|
| did it call the right thing? | `tool_used`, `tool_order`, `trajectory` | whether the answer was right |
| did it hold back? | `no_tool`, `trajectory` EXACT, `tool_used` `max: 0` | whether it explained itself |
| did it end properly? | `terminal` | whether the work was done |
| what did it cost? | `budget` (usually `informational: true`) | nothing — this is a signal, not a gate |
| did it produce the artifact? | `file_exists`, `structured_output` | whether the values are true |
| did it say the right thing? | `regex`, `final_text` | whether it meant it |
| is the answer acceptable? | `llm` | whether another sample would agree |
A refusal case needs `no_tool` or an `EXACT` trajectory specifically, and not
`IN_ORDER` or `ANY_ORDER`: those two tolerate extra calls, so the forbidden call
can happen in between and the grader still passes. `no_tool` asserts the absence
itself; `EXACT` asserts the whole call list, so anything extra fails it. Pair
either with an `llm` grader on the explanation — restraint alone could also be
an agent that crashed or refused everything.

## Decision rules

- **Prefer the cheapest grader that can fail for the right reason.** A judge
  call to check that a number appears in the reply is a judge call wasted, and
  less stable than the regex would have been.
- **A judge grader is half a case.** It reads text, so it can never prove what
  the agent did. Pair it with a trace-level grader and say so in the body.
- **A refusal needs `no_tool` or `EXACT`, never `IN_ORDER`/`ANY_ORDER`.** The
  looser matches tolerate extra calls, so the call the case forbids can happen
  in between and still pass; `no_tool` asserts the absence itself and `EXACT`
  asserts the whole call list, so anything extra fails it. State that in the
  reply for **every refusal case you touch**, including one that already has
  the right grader — "already correct" without the reason teaches the reader
  nothing, and the reader is deciding. Say the other half too: pair it with an
  `llm` grader on the explanation, because restraint alone could also be an
  agent that crashed or refused everything.
- **One claim per criterion.** If it needs "and", it is two graders — a
  compound verdict does not say which half failed.
- **Always write a FAIL clause.** "Otherwise FAIL" leaves the near-misses
  (agreeing to do it later, asking the user to confirm, declining without a
  reason) to the judge's imagination, which is where sample disagreement
  comes from.
- **Keep `samples` odd.** Majority voting over an even number can tie.
- **No judge graders in the `pr` tier.** Every pull request would pay
  (`CFG030`).
- **`budget.max_turns` is not the option.** `max_turns=1` was measured
  producing `num_turns=2`. To assert a limit fired, use `terminal`.
- **Write the model pin as `${CLAUDE_MODEL:-…}`.** A literal id goes stale when
  a model retires; inheriting the CLI's default is worse.
- **A retired judge model is an error, not a warning** (`CFG011`): every judge
  call fails and every judged case reports `NOT_EVALUATED`.

## References

| Question | File |
|---|---|
| All twelve types and the measured semantics | [grader-catalog.md](references/grader-catalog.md) |
| Writing criteria a judge can answer; the lint rules | [rubric-authoring.md](references/rubric-authoring.md) |
| Cost, turns, tokens, and what not to assert | [budgets-and-efficiency.md](references/budgets-and-efficiency.md) |
| `output_format`, the synthetic call, `equals`/`contains` | [structured-output-graders.md](references/structured-output-graders.md) |
| The judge call, samples, judge model, cost | [judge-options.md](references/judge-options.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/grader_info.py [--type T] [--json]` | the catalog: tier, required and optional fields, targets, and what each type does not prove | 0 always, 2 unknown type |
| `scripts/gen_grader.py <case-dir> --type T [--name N] [--tool X] [--pattern P] [--reference R] [--max-cost-usd X] [--max-turns N] [--criteria "…"] [--force] [--dry-run] [--json]` | writes one grader with the right fields and a prose body; lints `llm` criteria | 0 complete, 1 findings or TODO placeholders left, 2 usage |
| `scripts/gen_config.py <project> [--model M] [--judge-model M] [--samples N] [--pr-threshold X] [--nightly-runs N] [--force] [--dry-run] [--json]` | writes `evals/eval_config.json` and validates what it wrote | 0 clean, 1 warnings or errors, 2 usage |
| `scripts/validate_config.py <project\|config> [--strict] [--no-cli] [--json]` | every `CFG` finding, against the installed runner copy and the active credential | 0 valid, 1 findings (warnings too under `--strict`), 2 missing or unparseable |

## Completion checklist

- [ ] The config or the existing graders were read before anything was proposed.
- [ ] Each grader offered carried **that type's own** "does not prove" line
      from `grader_info.py`, in the option where it is offered. A limit quoted
      for a different type does not count.
- [ ] The judge-call arithmetic (samples x runs x cases) was stated before an `llm` grader was added.
- [ ] `--dry-run` was shown and confirmed before writing.
- [ ] Every TODO placeholder in a generated grader was filled in.
- [ ] `validate_config.py` and `validate_cases.py` were run afterwards and their findings shown.
