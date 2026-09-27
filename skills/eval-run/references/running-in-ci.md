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
  `--max-cost-usd` ceiling then means money.
- **Cloud providers**: `CLAUDE_CODE_USE_BEDROCK=1` and friends with the
  cloud's OIDC credentials.
- Never pass a credential as a plain `env:` literal; the workflow linter flags it.

Anthropic's policy note applies: a subscription may not be offered to third
parties' use of a product. A personal CI on a personal plan is your own use.

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
(the third-party note); this plugin's `skills/eval-ci`.
