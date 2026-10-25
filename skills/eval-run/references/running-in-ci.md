# Running the suite in CI

The runner needs three things a CI job must provide: the project's interpreter
with `claude-agent-sdk` installed, a credential the bundled CLI accepts, and
the runner copy, which is already in the repository under `evals/runner/`.
`/agent-sdk:eval-ci` writes the workflow; this page explains what it contains.

## The step

```yaml
- run: python -m pip install -r requirements.txt
- name: Agent evals (pr tier)
  env:
    CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    # ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}   # API billing instead
    CLAUDE_MODEL: claude-sonnet-5-5
    PYTHONPATH: evals/runner:.
  run: python -m agent_sdk_evals run evals --tier pr --concurrency 1 --max-cost-usd 5 --json
```

The step's exit code is the gate. `3` (inconclusive) should not be read as a
regression: the generated workflow marks it as neutral where the platform
allows, and fails otherwise.

## Credentials in CI

- **Subscription token**: `claude setup-token` locally mints a long-lived
  `CLAUDE_CODE_OAUTH_TOKEN`; store it as a repository secret. It is tied to
  the plan of whoever ran the command, which suits a personal repository and
  not an organization-wide secret. Runs draw on that plan's usage limits, and
  a `rejected` status marks the rest of the suite `NOT_EVALUATED`.
- **API key**: `ANTHROPIC_API_KEY` as a secret; bills the API; the
  `--max-cost-usd` ceiling then means money. Expect one stderr notice per run
  ("claude.ai connectors are disabled because ANTHROPIC_API_KEY … takes
  precedence over your claude.ai login") — measured, informational, **not a
  failure**, so do not let a log scan fail the job on it.
- **Cloud providers**: `CLAUDE_CODE_USE_BEDROCK=1` and friends with the
  cloud's OIDC credentials — and the provider's own variables in the same
  `env:` block, since the suite inherits them from the job.
- Never pass a credential as a plain `env:` literal; the workflow linter flags it.

A gateway token, a third-party provider and telemetry turned off each stop a
session from receiving the interactive feature flags, and on Claude Code
**2.1.285–2.1.301** such a session starts in **`auto`** permission mode when
`permission_mode` is unset — where a classifier reviews each call and broad
allow rules are dropped; 2.1.302 starts it in `default`. The agent should pass the mode explicitly (`dontAsk`
for CI); the runner forces `"dontAsk"` when it is unset, and `lint_agent.py`
reports the omission as `OPT013`. Both cost ceilings are **soft**: the estimate
can pass `--max-cost-usd` or `max_budget_usd` before the run stops, so leave
headroom.

Anthropic's policy note applies: a subscription may not be offered to third
parties' use of a product. A personal CI on a personal plan is your own use.

## Record the machine, not just the score

An agent eval is an end-to-end test of the run's environment too. Anthropic's
infrastructure-noise study (2026-02-05) found that resource limits alone moved
a coding benchmark by 6 percentage points, that tight limits kill runs that
would have passed, and (anecdotally) that pass rates shift with the time of day.
For a CI gate that means:

- **write the resource configuration down and keep it fixed**: runner image,
  CPU and memory limits, concurrency, model id, SDK version and bundled CLI
  (the run's `init` event and `results/*/aggregate.json` carry the last three);
- **repeat runs across different times and days** before trusting a small
  movement — a nightly schedule does this for free, so compare a week of
  nightlies, not two runs;
- compare scores only between runs with matched configuration: the article
  says "leaderboard differences below 3 percentage points deserve skepticism
  until the eval configuration is documented and matched", and a suite of
  twenty cases moves 5 points when one case flips.

## The other shape: `claude-code-action`

`anthropics/claude-code-action@v1` runs Claude Code itself in a job and accepts
`claude_code_oauth_token` or `anthropic_api_key`. It can install this plugin
(`plugin_marketplaces`, `plugins`) and run `/agent-sdk:eval-run` as its
prompt, which is useful for a written summary; it is not a deterministic gate,
because an agent decides what to run. Use the plain step for the gate and the
action, if at all, for the narrative.

---

Sources: `https://code.claude.com/docs/en/github-actions` (secrets, the OAuth
token, `claude-code-action` inputs), `https://code.claude.com/docs/en/env-vars`
(`CLAUDE_CODE_OAUTH_TOKEN`), `https://code.claude.com/docs/en/agent-sdk/quickstart`
(the third-party note), `https://code.claude.com/docs/en/permission-modes`
("Tool calls denied in `claude -p` and Agent SDK runs"); this plugin's `skills/eval-ci`. The API-key
stderr notice was measured by this plugin on 2026-10-11 against SDK 0.2.165 with
bundled CLI 2.1.294. Re-read 2026-10-11 against claude-agent-sdk 0.2.165 /
Claude Code 2.1.296 docs. The 2.1.302 unset-mode rule is stated at
<https://code.claude.com/docs/en/permission-modes#which-mode-a-non-interactive-run-starts-in>
(and in the CHANGELOG); re-read 2026-10-24 against claude-agent-sdk 0.2.174 /
Claude Code 2.1.310 docs. <https://www.anthropic.com/research/infrastructure-noise>
("Infrastructure noise in agentic coding evals", 2026-02-05, resource
configuration as an experimental variable, repeats across times and days, the
3-point threshold). Re-read 2026-10-29 against claude-agent-sdk 0.2.174 / Claude
Code 2.1.312 docs.
