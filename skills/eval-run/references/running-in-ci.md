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

## Test the build you ship, on every prompt change

*An update on Claude Code quality reports* (2026-04-23) traced weeks of reported
quality loss to three harness changes — a lower default effort, a cache
optimisation that dropped earlier reasoning every turn, and one verbosity line
in the system prompt — not to the model or the API. Each hit a different slice
of traffic on a different schedule, so together they looked like vague,
inconsistent degradation. Anthropic's fixes translate directly to a CI gate:

- run the suite on **every system-prompt change**, per model if the agent can
  run on more than one (a matrix over `CLAUDE_MODEL`), not only on code
  changes;
- run it on the **exact build that ships**: the SDK version from the lockfile
  and the CLI it bundles, which the run's `init` event records as
  `claude_code_version`; a gate that runs a newer or older `claude` (through
  `cli_path` or `PATH`) tests something else;
- keep `effort` explicit in the options, since a changed default moves scores
  without a line of your code changing. The article's effort figures are April
  2026 history; current defaults are in the `model-config` docs.

A run whose CLI cannot start is not a failed case. The Claude Code
`CHANGELOG.md` (2.1.314) says `claude -p` used to exit 0 with no output when
startup failed and now prints the error and exits 1. Separately, this plugin
measured on 2026-11-02 six bad flags or configs that exited 1 with the error on
stderr on both 2.1.310 and 2.1.316; through the SDK the same failure raises
`ProcessError` (`exit_code=1`), which the runner records as a
`NOT_EVALUATED` run with the reason, never as a pass or a regression.

Three later changes for a CI job (changelog): from **2.1.317** `claude -p` also
exits 1 (text and json output) when a full disk or quota lost its transcript or
`~/.claude.json` writes, so a runner short of disk now fails loudly; a `claude -p`
started inside a cloud or self-hosted runner session gets its own session id
instead of writing into that session's transcript
(`CLAUDE_CODE_DISABLE_NESTED_SESSION_ID=1` restores the old sharing). From
**2.1.318**, with a stored claude.ai sign-in, `claude -p` warns on stderr 10 days
before it ends and its JSON carries `credential_expires_at` — grep the step log
for it. `CLAUDE_CODE_OAUTH_TOKEN` belongs in the job's environment: project and
local settings files ignore it (docs read 2026-11-04).

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
3-point threshold).
<https://www.anthropic.com/research/april-23-postmortem> ("An update on Claude
Code quality reports", 2026-04-23, three harness changes that looked like model
drift, per-model evals on every system-prompt change, testing the exact public
build); the `-p` startup exit code per the Claude Code `CHANGELOG.md` (2.1.314)
and measured by this plugin on 2026-11-02 (2.1.310 and 2.1.316); the 2.1.317 and
2.1.318 entries per the same changelog.
Re-read 2026-11-08 against claude-agent-sdk 0.2.179 / Claude Code 2.1.319 docs.
