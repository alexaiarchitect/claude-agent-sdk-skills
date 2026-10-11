---
name: eval-ci
description: >-
  Puts a Claude Agent SDK project's eval suite behind a CI gate that means
  something, and says where the project's evaluation practice actually stands.
  Generates two GitHub Actions workflows that run the runner copy committed in
  the project as a plain step, so the exit code is the verdict and no agent
  decides what runs: a pull-request tier with free graders, one run per case,
  a cost ceiling and cancel-superseded concurrency, and a nightly tier with
  judge graders and repeated runs. Wires the credential as a repository secret
  (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token` by default, the
  ANTHROPIC_API_KEY line written commented out), uploads evals/results as an
  artifact, treats the runner's exit 3 as neutral rather than as a regression,
  lints existing workflows for the mistakes that make a gate vacuous, and
  reports an evaluation maturity level L0-L5 with the single next step. Use
  when asked to "add evals to CI", "gate merges on evals", "set up a nightly
  eval run", "which secret does CI need", "why is our eval workflow always
  green", or "how mature is our evaluation". Don't use to run evals locally
  (use `/agent-sdk:eval-run`), to pick graders or tiers (use
  `/agent-sdk:eval-criteria`), to interpret results (use
  `/agent-sdk:eval-analyze`), or to deploy the agent itself (use
  `/agent-sdk:agent-deploy`).
argument-hint: "[project-dir] [--tier pr|nightly|both] [--auth oauth|api-key]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, Bash(python3 *)
---

# Gate changes on Agent SDK evals

A CI eval gate has one job: turn "the evals pass" into something nobody has to
take on trust. Two facts shape every file this skill writes.

**The runner already lives in the repository.** `evals/runner/agent_sdk_evals`
is a version-stamped copy, so a workflow needs no registry install — only
Python, the project's dependencies, a credential, and `PYTHONPATH` pointing at
the copy. Get that path wrong and the job dies at `import agent_sdk_evals`,
which looks like a broken gate rather than a missing path.

**A session costs quota or money.** A judge grader on every pull request is
slow enough that people stop pushing and expensive enough that someone
eventually disables the workflow, which is worse than having no gate. Hence two
tiers, and `--concurrency 1` in both.

`${CLAUDE_SKILL_DIR}` is this skill's directory.

## Flow

1. **Discover.** What exists, and where the project stands:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../agent-sdk/scripts/discover.py <project> --focus ci,evals,results
   python3 ${CLAUDE_SKILL_DIR}/scripts/assess_maturity.py <project>
   python3 ${CLAUDE_SKILL_DIR}/scripts/lint_workflows.py <project>
   ```

   The linter runs even when no workflow exists: that is `CI001`.

2. **Report.** The maturity level with its evidence, the cases and config tiers,
   whether a runner copy is present, and every `CI0xx` finding on what is
   already there. Name the secret the project will need before offering to
   write anything.

3. **Options, with cost.** Writing workflows is tier `free` — nothing here
   starts a session. What the workflows will *later* spend is the number worth
   saying: cases x runs sessions per pull request, and cases x runs sessions
   plus judge calls per night (the arithmetic is in
   [tiered-pipeline.md](references/tiered-pipeline.md)). Usual options: the pr
   tier only (the right first step for most projects), both tiers, a pytest
   gate instead of or beside the workflows, or fixing an existing workflow that
   does not really gate.

4. **Confirm**, then act:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/gen_workflows.py <project> --tier both --dry-run
   python3 ${CLAUDE_SKILL_DIR}/scripts/gen_workflows.py <project> --tier both
   python3 ${CLAUDE_SKILL_DIR}/scripts/lint_workflows.py <project>
   ```

   Show the write plan before writing it. The `--dry-run` pass runs **even when
   the user has already approved writing**: its write plan is the record of what
   is about to change, and without it the plan and the change land in the same
   breath, so there is nothing to check the result against. Pre-approval skips
   the *confirmation*, never the dry run. Never hand-write a workflow file:
   `gen_workflows.py` is the only thing that knows the gate's shape. Existing
   files are skipped unless `--force`. Lint what was written: the generated
   files are expected to come back clean, and a finding means the project has
   something the template could not know about.

## The two tiers

| | `pr` | `nightly` |
|---|---|---|
| Trigger | `pull_request`, manual | `schedule` cron, manual |
| Graders | free only | free + judge |
| Runs per case | 1 | `--runs N` (3) |
| Superseded runs | cancelled | never cancelled |
| Ceiling | `--max-cost-usd X` | `X x runs`, longer timeout |
| Answers | did it break | how reliable is it |

## Decision rules

- **Never a judge grader in the per-pull-request job.** It is the single change
  most likely to get the gate switched off. `CI011` flags it from either side:
  the config's `pr` tier listing `judge`, or a per-change workflow running
  `--tier nightly`.
- **`--concurrency 1` on a subscription token.** Every case is a full CLI child
  on one credential; parallel sessions reach a rejected rate limit sooner and
  buy nothing (`CI022`).
- **A wrong `PYTHONPATH` fails at the wrong place.** `evals/runner:.` is not
  cosmetic; without it the job fails at import and everyone reads it as a broken
  suite (`CI050`, error).
- **Exit 3 is neutral, never red.** Inconclusive means nothing was scored, so
  nothing regressed. The workflow turns it into a warning annotation and leaves
  the job green; only 1 and 2 fail it. A gate that goes red for a quota problem
  is a gate people learn to ignore.
- **Never a credential literal.** Only `${{ secrets.* }}` (`CI020`, error). An
  OAuth token is tied to one person's plan: fine for a personal repository,
  wrong as an organization-wide secret, where an API key is the answer.
- **Always upload `evals/results/` with `if: always()`.** The run worth
  examining is the failing one (`CI040`).
- **Climb one rung.** A project at L1 that jumps straight to a nightly judged
  suite ends up with an expensive job nobody reads.

## References

| Question | File |
|---|---|
| What belongs in each tier, and what each can and cannot catch | [tiered-pipeline.md](references/tiered-pipeline.md) |
| The generated files line by line, the exit-3 mechanism, artifacts, concurrency | [workflows.md](references/workflows.md) |
| `claude setup-token`, secret names, expiry, the one-person caveat, `claude-code-action` | [subscription-and-secrets.md](references/subscription-and-secrets.md) |
| The L0-L5 ladder, its evidence and the next step at each rung | [maturity.md](references/maturity.md) |

Templates: `assets/templates/workflows/` plus `test_evals.py.tmpl` (the pytest
gate, also used by `/agent-sdk:agent-create`) and `ci-readme.md.tmpl`.

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/gen_workflows.py <project> [--tier pr\|nightly\|both] [--auth oauth\|api-key] [--python V] [--runs N] [--max-cost-usd X] [--cron EXPR] [--timeout-minutes N] [--out-dir D] [--pytest-gate] [--readme] [--force] [--dry-run] [--json]` | renders the workflows into a write plan; writes nothing on `--dry-run`, skips existing files without `--force` | 0 planned or written, 1 written with warnings to act on, 2 usage |
| `scripts/lint_workflows.py <project> [--strict] [--json]` | `CI0xx` findings on the workflows that exist, including their absence | 0 clean, 1 errors (with `--strict`, warnings too), 2 usage |
| `scripts/assess_maturity.py <project> [--json]` | the L0-L5 level, its evidence, and one next step | 0 always: a report, not a gate |

Findings: `CI001` nothing runs the runner, `CI010` no `--tier`, `CI011` judges
on the per-change path, `CI020` credential literal, `CI021` no credential
reaches the step, `CI022` concurrency above 1 on a token, `CI030` no ceiling and
no timeout, `CI031` no ceiling on a subscription, `CI040` results not persisted,
`CI050` `PYTHONPATH` without `evals/runner`, `CI060` `claude-code-action` as the
gate.

## Completion checklist

- [ ] The maturity level and its evidence were reported before anything was written.
- [ ] The write plan was shown and confirmed; nothing existing was replaced without `--force`.
- [ ] The pr tier runs free graders only; judges are on the schedule.
- [ ] The credential is a `${{ secrets.* }}` reference, and the user was told which secret to create and how.
- [ ] `PYTHONPATH: evals/runner:.` reaches every runner step.
- [ ] `evals/results/` is uploaded with `if: always()`.
- [ ] Exit 3 is neutral and only 1 or 2 fail the job.
- [ ] `lint_workflows.py` exits 0 on what was written.
