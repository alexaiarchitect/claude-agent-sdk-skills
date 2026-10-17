# The credential CI uses, and what it costs

The runner starts a real Claude Code CLI child per case. That child needs a
credential, and which one you pick decides what a nightly run spends, who it is
billed to, and whether the secret can be shared across an organization.

## The two secrets

| Secret | Minted by | What a run spends | Scope |
|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token`, locally | the usage limits of that person's Claude plan | one person |
| `ANTHROPIC_API_KEY` | the Claude Console | money, per token | an organization |

Both are plain repository secrets passed as `env:` on the step. The generated
workflows write the OAuth line active and the API-key line commented, so the
switch is a two-line edit in either direction, and `--auth api-key` generates
the reverse.

## `claude setup-token`

Run it on a machine where you are already logged in:

```bash
claude setup-token
```

It opens the same browser authorization flow as `/login` and prints a
long-lived token to the terminal. It does **not** save the token anywhere —
copy it straight into the repository secret. Available on Pro, Max, Team and
Enterprise plans.

The token is long-lived, not permanent (the documented lifetime is a year), and
it can be revoked. When the gate starts failing at the credential — every case
`NOT_EVALUATED`, exit 2, or an auth error in the step log — the first thing to
check is whether the token expired. Re-run `claude setup-token` and replace the
secret; nothing else in the workflow changes.

## The one-person caveat

An OAuth token authenticates *as the person who minted it*. Every eval run in CI
draws on that person's plan usage limits, appears in their usage, and stops
working when they leave or change plan. For a personal repository that is fine
and is the cheapest way to run evals in CI at all.

For an organization-wide secret it is the wrong shape, and Anthropic's own
guidance says so: for a secret shared across repositories, authenticate with an
API key from the Console rather than an OAuth token, precisely because the token
is tied to one subscription. The same applies to a repository several people
merge into — the gate's cost lands on one of them.

A third option avoids storing a long-lived secret at all: workload identity
federation, where the workflow's GitHub OIDC token is exchanged for Claude API
access through a Console service account. That is an input shape of
`claude-code-action` (`anthropic_federation_rule_id`,
`anthropic_organization_id`, and optionally `anthropic_service_account_id` and
`anthropic_workspace_id`, with `id-token: write` on the job), not something a
plain `env:` step can use today.

## The policy note

Anthropic's terms do not allow a Claude subscription to be offered to third
parties' use of a product. Running your own evals in your own CI on your own
plan is your own use. Wiring a subscription token into a service other people
call is not, and that is the line `/agent-sdk:agent-deploy` restates for hosted
and multi-tenant deployments: those need an API key or a cloud provider.

## Quota, not dollars

On a subscription the runner's dollar figure is an **API-equivalent estimate**;
the binding limit is quota. The runner records rate-limit events: `allowed` and
`allowed_warning` are informational and the suite continues, and only `rejected`
stops it — marking the remaining runs `NOT_EVALUATED` and exiting 3, which the
workflow treats as neutral. `--max-cost-usd` is still worth passing: on a
subscription it is an estimate-based ceiling on quota rather than on a bill
(`CI031`).

Keep `--concurrency 1` on a token. Parallel sessions share one plan's limits, so
they reach `rejected` sooner and buy nothing (`CI022`).

## Cloud providers

`CLAUDE_CODE_USE_BEDROCK=1`, `CLAUDE_CODE_USE_VERTEX=1` and
`CLAUDE_CODE_USE_FOUNDRY=1` switch the backend; the credential is then that
cloud's, usually minted from the job's OIDC token. `lint_workflows.py` accepts
one of these instead of a Claude credential and does not raise `CI021`, but it
cannot verify the provider's own wiring. Export the **provider's own variables**
into the job as well — the AWS, Google Cloud or Azure credentials the backend
needs — because a suite inherits them through `env` and `claude plugin eval` now
says the same for its CI credentials. A missing provider variable surfaces as an
auth failure inside the first session, not as a configuration error.

A provider switch has a second effect worth knowing in CI: a session on a
third-party provider, or one holding a gateway token, never receives the
interactive feature flags, so on Claude Code **2.1.285–2.1.301** it starts in
**`auto`** permission mode when `permission_mode` is unset — and `auto` drops
broad allow rules (2.1.302 starts it in `default`). Set the mode explicitly in the agent's options (`dontAsk` for
an unattended suite); this plugin's runner forces `"dontAsk"` when the options
leave it unset, and the lint reports the omission as `OPT013`.

## The other shape: `claude-code-action`

`anthropics/claude-code-action@v1` runs Claude Code itself in a job and accepts
`claude_code_oauth_token` or `anthropic_api_key` as inputs (with `id-token:
write` on the job for its default GitHub App authentication, and `actions: read`
to let it read CI results). It can install this plugin through
`plugin_marketplaces` and `plugins`, and run `/agent-sdk:eval-run` as its
`prompt` in automation mode.

That is genuinely useful for a written summary on a pull request. It is not a
gate: an agent decides what to run, so the verdict is not reproducible and a
prompt change silently changes what is checked. `lint_workflows.py` reports
`CI060` (info) when it is the only eval-shaped job. Use the plain step for the
gate, and the action, if at all, for the narrative.

---

Sources: `https://code.claude.com/docs/en/github-actions` (secret names, the
`claude_code_oauth_token` and `anthropic_api_key` inputs, the organization
guidance that an OAuth token is tied to one subscription, federation inputs,
`id-token: write`); `https://code.claude.com/docs/en/authentication`
(`claude setup-token`, the one-year token, which plans have it);
`https://code.claude.com/docs/en/env-vars` (the backend switches);
`https://code.claude.com/docs/en/agent-sdk/quickstart` (the third-party note);
`https://code.claude.com/docs/en/permission-modes` (the headless starting-mode
table); `https://code.claude.com/docs/en/plugin-evals` (cloud-provider
variables in CI). Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude
Code 2.1.296 docs. The 2.1.302 unset-mode change is from
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md>; re-read
2026-10-17 against claude-agent-sdk 0.2.168 / Claude Code 2.1.302 docs.
