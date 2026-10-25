# Plugin eval cases

Behavioural tests for the **skills**, not for your agents. They live under
`plugin-evals/` (named in `plugin.json`'s `experimental.evals`) rather than `evals/`,
because `claude plugin eval` collects every `evals/<case>/prompt.md` it can see and
the test fixtures carry `evals/` directories of their own, in a different format. Each case runs a prompt
in a session with only this plugin loaded, and grades what the model did.

```bash
claude plugin eval . --scaffold --allow-tools Bash Write Edit --judge-model claude-sonnet-5-5
claude plugin eval . --scaffold --allow-tools Bash Write Edit --judge-model claude-sonnet-5-5 \
  --case routing-ambiguous --runs 1
claude plugin eval . --scaffold --allow-tools Bash Write Edit --judge-model claude-sonnet-5-5 \
  --json results.json --threshold 0.8 --max-cost-usd 5
```

**Claude Code 2.1.293 or newer; 2.1.299 for honest scores.** Two `plugin eval`
fixes these cases depend on landed in 2.1.289 and 2.1.293; on an older CLI a
case can fail for a reason that is not in the plugin. From **2.1.299** a run that
ends on an API error scores 0 without grading and the suite exits 1 (before, such
a run was graded on whatever it had produced), and `--disallow-tools <tools...>`
keeps built-in tools such as `Agent` out of every case (listed in the 2.1.301
help, still in the 2.1.310 help on 2026-10-24, and in the 2.1.312 help on
2026-10-29, whose example now reads `Agent TaskStop`; nothing about `plugin
eval` changed in 2.1.311 or 2.1.312). The changelog also names a `disallowed_tools` case field; it is not in
the plugin-evals docs yet and no case here uses it until a local run has
accepted it.

**Run from a folder whose ancestors can all be examined (measured 2026-10-24).**
On 2.1.310 `--scaffold` stats every ancestor of the suite first and refuses the
whole suite if one fails: `✗ /Users/alex/Documents: Documents could not be
examined (EPERM) — refusing to treat that as the suite`, exit 1, `cases: []`.
Here the terminal lacked macOS Documents access; run from a copy outside the
protected folder or grant access. 2.1.302 did not do this; the changelog is silent.

**Three flags, and none of them is a default.**

- `--scaffold` runs each case's `scaffold_script`. It is opt-in because a
  scaffold script is author-supplied bash that runs as you. Without it, every
  case that needs a project starts in an empty directory, so each case that
  names a fixture fails for want of the project its prompt describes. No
  grader watches the scaffold's own sentinel: `file_exists` counts only files
  **Claude** created during the run, so a file a scaffold wrote is invisible to
  it ([plugin-evals docs](https://code.claude.com/docs/en/plugin-evals)). The
  sentinel is there for a human reading the sandbox afterwards with
  `--keep-temp`, not for a grader.
- `--allow-tools Bash Write Edit` is the operator grant for gated tools. Every
  case runs the plugin's scripts through `Bash`; the authoring cases also write
  files. Without the grant those calls are refused and the cases fail for the
  wrong reason.
- `--judge-model claude-sonnet-5-5` pins the judge. The default is no longer a
  named model: it is "the model Claude Code uses for background tasks", which
  moves with the CLI (on 2.1.294 that is `claude-haiku-5-5`). Unpinned, two runs
  weeks apart are not comparable, and the rubrics below are written for a judge
  that can hold a transcript and a script's output side by side.

Every run is a full `claude` child on your own credential; on a subscription
the cases draw on the same usage limits as your own work, so start with
`--runs 1` and a `--max-cost-usd` ceiling. `--max-cost-usd` is a soft cap: the
estimate it compares against can pass the value before the run stops, so leave
headroom.

Two upstream rules to know before editing a case, because both are now **load
errors** rather than warnings: a mock `expect:` pattern must stay inside the
documented `/regex/` dialect — literals, `.`, `\d`-style escapes, classes,
simple quantifiers, optional `^`/`$`, flags `i` and `s`, and **no groups, no
alternation, no lookaround** (write a list of literals instead of `a|b`) — and
all `type: agent` mocks in a run share **one call budget of 4 x the case's
`max_turns`**, 40 at the default, which aborts the run with score 0 when
exceeded.

## What each case pins

Thirteen cases. `design-review` arrived with the `agent-design` skill in 0.2.0;
the other twelve are unchanged.

| Case | Asserts |
|---|---|
| `routing-ambiguous` | a vague request goes to the router, which discovers before advising |
| `run-dry-run` | "show me, don't run" reaches `eval-run`, uses `--dry-run`, states the credential and the arithmetic, starts nothing |
| `analyze-results` | a failure is explained by grader and quadrant, not by score; never-evaluated runs are kept apart |
| `pass-at-k` | reliability comes from repeated runs, read as pass@1 |
| `agent-review-drift` | a review reports the drift and edits nothing, with `Write`/`Edit` available |
| `ci-setup` | CI gates on the runner's exit code with the OAuth secret; a workflow file actually lands |
| `runner-stale` | a stale runner copy is reported by id (`DEP001` from the runner check, or `CFG050` from the validator) and the upgrade is offered, not applied |
| `harness-hooks` | hook defects are reported by id from the linter, the correct shape is explained, nothing is written |
| `simulation` | simulated users bring their cost and the trajectory-grader constraint with them; the persona and mocks are validated |
| `case-validate` | a validation request reaches `eval-review`, runs the validator before pronouncing, and finds the planted `EVC003` |
| `criteria-choice` | grader advice comes with cost on a subscription, and nothing is written unasked |
| `create-edge-cases` | coverage is measured before cases are written, and no existing case is edited |
| `design-review` | a tool-design and "should this be a subagent" question reaches `agent-design`, which runs its checker, names the `DSG` findings, decides fold-versus-keep by context, cites an article and the subagents doc, and writes nothing; measured 2026-10-29 on 2.1.312: with 1.0, without 0.667, Δ +0.333, $0.76 |

## Shared setup

Each case names `scaffold.sh` in its `case.yaml` (`context.scaffold_script`, the only
place the CLI accepts it); that one-line wrapper calls the shared `plugin-evals/scaffold.sh`
with the case's arguments. The shared script prepares the session's working directory
so nothing in the repository is touched:

```
scaffold.sh [<fixture>|none] [<mutation>] [stage-results[=<dirs>]] [stage-traces] [stage-sessions]
```

- **fixture** copies a project from `tests/fixtures/agents/` and a copy of the
  runner package into `evals/runner/`. `none` copies no project.
- **mutation** plants a specific defect the prompt describes (`bad-override`,
  `retiring-judge`, `stale-runner`).
- **stage-\*** directives copy fixture data into `./fixtures/` inside the
  sandbox, so prompts use sandbox-relative paths instead of reaching back into
  the plugin. `stage-results` takes an optional comma-separated selector
  (`stage-results=failure_only,not_evaluated`) naming which run directories to
  copy; without one it stages them all. All four at once makes "the last run"
  ambiguous — their timestamps are identical — and makes `pass_at_k.py` pool
  unrelated series, so a case asking about one run names the run it means.

It also writes `.scaffold/manifest.txt` (what ran) and `.scaffold/protected.sha256`
(a checksum per file the case must not modify).

## What a tightened rubric asks for

Every `criteria.md` was tightened on 2026-10-11 so a PASS needs evidence **only
the plugin's scripts produce**: the discovery report's `## Found` and
`## Missing` blocks, a finding id the linter or validator actually printed
(`EVC003`, `AGT030`, `DEP001`, `HOK001`, …), the credential line with its
`cost basis:`, and a `cost:` tier on each option offered. What is asked for is
the **fact or the id** the script printed, not its wording: a response may put
a finding in its own words, but the id, the severity and the figures have to be
the script's. Every `criteria.md` carries `focus: trace`, because an `llm`
grader's default `focus` is `last_message` and a judge looking only at the
final answer cannot see the script output these rubrics rest on. `trace` shows
it the **first 12 and the last 12 messages** and nothing in between, and that
window is fixed — there is no flag that widens it. Measured on 2026-10-13, the
longer cases elide far more than they show (`simulation` elided 87 messages,
`runner-stale` 17), so the script output a rubric asks about is routinely
outside the judge's view. Every `criteria.md` therefore carries a *What the
judge can see* paragraph: an elided middle is not evidence that a script was
never run, and an item counts as evidenced when the script's call or output is
visible **or** the response states it with the specificity only that script's
output has (a finding id, a verbatim reason or `Fix:` string, an exact figure).
That test applies to the items the rubric names; the rest of an answer is
neither required nor penalised. Every `criteria.md` FAIL list ends with the same clause — advice or a verdict given without running
the plugin's script — so a model that answers correctly from its own knowledge
of the SDK still fails. That is deliberate: these cases measure whether the
skills fire and are followed, not whether the model knows the Agent SDK.

## How the "nothing happened" graders work

Some cases assert that something *did not* happen, which an llm judge cannot
reliably see. They use `regex` graders over `target: trace` with
`match: not_contains`: failing if any command in the execution trace starts a
session, or any `Edit`/`Write` names a protected file. Each grader file says
what it proves and what it does not. A `file_exists` grader cannot stand in for
one of these: it counts only files **Claude** created during the run, so the
checksums the scaffold writes to `.scaffold/protected.sha256` are invisible to
every grader — read them yourself with `--keep-temp`.

## Grader types in use

`llm` (a judged rubric), `tool_used` (the skill fired), `tool_order` (the
validator ran before the verdict), `file_exists` (a deliverable landed), and
`regex` over the trace (something did or did not happen).
