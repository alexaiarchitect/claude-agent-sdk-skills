# Plugin eval cases

Behavioural tests for the **skills**, not for your agents. They live under
`plugin-evals/` (named in `plugin.json`'s `experimental.evals`) rather than `evals/`,
because `claude plugin eval` collects every `evals/<case>/prompt.md` it can see and
the test fixtures carry `evals/` directories of their own, in a different format. Each case runs a prompt
in a session with only this plugin loaded, and grades what the model did.

```bash
claude plugin eval . --scaffold --allow-tools Bash Write Edit
claude plugin eval . --scaffold --allow-tools Bash Write Edit --case routing-ambiguous --runs 1
claude plugin eval . --scaffold --allow-tools Bash Write Edit --json results.json --threshold 0.8 --max-cost-usd 5
```

**Both flags are required, and neither is a default.**

- `--scaffold` runs each case's `scaffold_script`. It is opt-in because a
  scaffold script is author-supplied bash that runs as you. Without it, every
  case that needs a project starts in an empty directory, and the
  `scaffold-intact` graders fail because the sentinel they look for was never
  written.
- `--allow-tools Bash Write Edit` is the operator grant for gated tools. Every
  case runs the plugin's scripts through `Bash`; the authoring cases also write
  files. Without the grant those calls are refused and the cases fail for the
  wrong reason.

Every run is a full `claude` child on your own credential; on a subscription
the cases draw on the same usage limits as your own work, so start with
`--runs 1` and a `--max-cost-usd` ceiling.

## What each case pins

| Case | Asserts |
|---|---|
| `routing-ambiguous` | a vague request goes to the router, which discovers before advising |
| `run-dry-run` | "show me, don't run" reaches `eval-run`, uses `--dry-run`, states the credential and the arithmetic, starts nothing |
| `analyze-results` | a failure is explained by grader and quadrant, not by score; never-evaluated runs are kept apart |
| `pass-at-k` | reliability comes from repeated runs, read as pass@1 |
| `agent-review-drift` | a review reports the drift and edits nothing, with `Write`/`Edit` available |
| `ci-setup` | CI gates on the runner's exit code with the OAuth secret; a workflow file actually lands |
| `runner-stale` | a stale runner copy is reported as `DEP001` and the upgrade is offered, not applied |
| `harness-hooks` | hook defects are reported by id from the linter, the correct shape is explained, nothing is written |
| `simulation` | simulated users bring their cost and the trajectory-grader constraint with them; the persona and mocks are validated |
| `case-validate` | a validation request reaches `eval-review`, runs the validator before pronouncing, and finds the planted `EVC003` |
| `criteria-choice` | grader advice comes with cost on a subscription, and nothing is written unasked |
| `create-edge-cases` | coverage is measured before cases are written, and no existing case is edited |

## Shared setup

Each case names `scaffold.sh` in its `case.yaml` (`context.scaffold_script`, the only
place the CLI accepts it); that one-line wrapper calls the shared `plugin-evals/scaffold.sh`
with the case's arguments. The shared script prepares the session's working directory
so nothing in the repository is touched:

```
scaffold.sh [<fixture>|none] [<mutation>] [stage-results] [stage-traces] [stage-sessions]
```

- **fixture** copies a project from `tests/fixtures/agents/` and a copy of the
  runner package into `evals/runner/`. `none` copies no project.
- **mutation** plants a specific defect the prompt describes (`bad-override`,
  `retiring-judge`, `stale-runner`).
- **stage-\*** directives copy fixture data into `./fixtures/` inside the
  sandbox, so prompts use sandbox-relative paths instead of reaching back into
  the plugin.

It also writes `.scaffold/manifest.txt` (what ran) and `.scaffold/protected.sha256`
(a checksum per file the case must not modify).

## How the "nothing happened" graders work

Some cases assert that something *did not* happen, which an llm judge cannot
see from a transcript summary. They use `regex` graders over `target: trace`
with `match: not_contains`: failing if any command in the execution trace
starts a session, or any `Edit`/`Write` names a protected file. Each grader
file says what it proves and what it does not.

## Grader types in use

`llm` (a judged rubric), `tool_used` (the skill fired), `tool_order` (the
validator ran before the verdict), `file_exists` (a deliverable landed), and
`regex` over the trace (something did or did not happen).
