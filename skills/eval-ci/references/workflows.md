# The generated workflows, line by line

`gen_workflows.py` renders two files into `.github/workflows/`:
`agent-evals-pr.yml` and `agent-evals-nightly.yml`. They differ in trigger,
tier, run count and concurrency policy; everything else below is shared.

## The shape

```yaml
on:
  pull_request:          # nightly: schedule.cron + workflow_dispatch inputs
  workflow_dispatch:

concurrency:
  group: agent-evals-pr-${{ github.ref }}
  cancel-in-progress: true          # nightly: false, and a fixed group

permissions:
  contents: read                    # nothing writes to the repository

jobs:
  pr-tier:
    timeout-minutes: 30             # nightly: 30 x runs
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: python -m pip install -r requirements.txt
      - name: Run the pr tier        # the gate; see below
      - name: Upload results         # if: always()
      - name: Gate on the eval outcome
```

`cache: pip` is written only when a `requirements*.txt` exists, because
`setup-python` fails the job when its cache has nothing to key on. With no
requirements file the install step becomes `pip install claude-agent-sdk`
unpinned, and the generator warns: a gate whose dependency floats is a gate
whose behaviour changes without a commit.

## The gate step

```yaml
      - name: Run the pr tier
        id: evals
        continue-on-error: true
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          # ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          CLAUDE_MODEL: "claude-sonnet-5-5"
          PYTHONPATH: evals/runner:.
        run: |
          set +e
          python -m agent_sdk_evals run evals --tier pr --concurrency 1 \
            --max-cost-usd 5 --json
          code=$?
          set -e
          echo "exit_code=$code" >> "$GITHUB_OUTPUT"
          if [ "$code" -eq 3 ]; then
            echo "::warning title=Evals inconclusive::..."
            exit 0
          fi
          exit "$code"
```

Three details are load-bearing.

**`PYTHONPATH: evals/runner:.`** The runner is not installed from a registry; it
is the copy committed in the repository under `evals/runner/agent_sdk_evals`.
Without the first entry the step dies at `import agent_sdk_evals`, which reads
like a broken gate rather than a missing path — which is why `lint_workflows.py`
makes that `CI050`, an error. The trailing `.` keeps the project's own agent
module importable beside it.

**The credential is a secret reference.** Exactly one of the two lines is
active and the other is written commented, so switching is a two-line edit.
`CI020` is an error for a literal, because a credential in a workflow file is in
the repository history for good.

**`--concurrency 1`.** Each case is a full CLI child process on one credential.
On a subscription token, parallel sessions reach a rejected rate limit sooner,
and a rejected limit costs the whole suite its verdict rather than speeding it
up (`CI022`).

A job that switches backend (`CLAUDE_CODE_USE_BEDROCK=1` and friends) has to
carry **the provider's own variables** in the same `env:` block — the AWS,
Google Cloud or Azure credentials the backend mints from the job's OIDC token —
because the suite inherits them from the job environment and nothing else
supplies them. And because such a job never receives the interactive feature
flags, a session whose `permission_mode` is unset starts in **`auto`** on
Claude Code **2.1.285–2.1.301** (in `default` from 2.1.302), where broad allow
rules are dropped; the agent should
pass `permission_mode="dontAsk"`, and the runner forces it when the options do
not.

`--max-cost-usd` and the agent's `max_budget_usd` are both **soft**: the
estimate they compare against can pass the value before the run or the query
stops, so leave headroom in the number the workflow passes rather than setting
the exact figure the repository can afford.

## The exit-3 mechanism

The runner's exit codes are 0 pass, 1 a case below threshold, 2 it could not run
at all, 3 inconclusive — nothing could be scored, because a usage limit was
rejected, the cost ceiling was hit, or a judge was unreachable.

Three is neutral on purpose: nothing was scored, so nothing regressed, and a
gate that goes red for a quota problem is a gate people learn to ignore. GitHub
has no neutral conclusion for an ordinary `run:` step, so the workflow builds
one out of three parts:

1. the step traps the code (`set +e`, `code=$?`), publishes it with
   `echo "exit_code=$code" >> "$GITHUB_OUTPUT"`, and for 3 emits a `::warning`
   annotation and exits 0 itself;
2. `continue-on-error: true` keeps exit 1 or 2 from aborting the job before the
   results are uploaded — the step's *outcome* is recorded as failed while its
   *conclusion* stays success, so the job continues;
3. a final `if: always()` step reads `${{ steps.evals.outputs.exit_code }}` from
   an env var and exits 1 for codes 1 and 2 only, writing an `::error`
   annotation that says which of the two it was.

The result: green with no annotation (passed), green with a warning
(inconclusive), red with "Eval failures" (a case below threshold), red with
"Eval runner error" (it never scored anything). Those four states are what a
reviewer needs, and they are distinguishable at a glance in the checks list.

## Artifacts

```yaml
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: agent-evals-pr-${{ github.run_id }}
          path: evals/results/
          if-no-files-found: warn
          retention-days: 14        # nightly: 90
```

`if: always()` matters more than the upload itself: the run worth examining is
the failing one. `evals/results/<timestamp>/` holds one `*.result.json` per
case, the `*.trace.jsonl` per run and `aggregate.json` — enough for
`/agent-sdk:eval-analyze` to explain the failure without anyone re-running the
suite locally. The nightly tier keeps them longer because reliability is read
over weeks. Not persisting them is `CI040`.

## Regenerating

`gen_workflows.py` never overwrites: an existing file is planned as `skip`
unless `--force` is passed, and `--dry-run` prints the plan and writes nothing.
After writing, run `lint_workflows.py <project>` on the result — the generated
files are expected to lint clean, and a finding means the project has something
the template could not know about.

---

Sources: `https://code.claude.com/docs/en/github-actions` (secret names, the
OAuth-token input, the action alternative); `https://code.claude.com/docs/en/env-vars`
(`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, the backend switches);
`.dev/CONTRACTS.md` §8 (the four exit codes);
`https://code.claude.com/docs/en/permission-modes` ("Tool calls denied in `claude -p` and Agent SDK runs"); `https://code.claude.com/docs/en/agent-sdk/agent-loop#budget-headroom`
(the soft budget cap); this plugin's
`skills/eval-run/references/running-in-ci.md` and `assets/templates/workflows/`.
Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs.
The 2.1.302 unset-mode rule is stated at
<https://code.claude.com/docs/en/permission-modes#which-mode-a-non-interactive-run-starts-in>
(and in the CHANGELOG); re-read 2026-10-24 against claude-agent-sdk 0.2.174 /
Claude Code 2.1.310 docs.
