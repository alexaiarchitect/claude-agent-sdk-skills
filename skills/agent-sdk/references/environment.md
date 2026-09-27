# Environment: credentials, cost basis, `.env`, and picking a Python

## The credential is decided by the subprocess, not your code

`query()` and `ClaudeSDKClient` spawn a bundled `claude` binary and talk to it
over stdio. That process authenticates the way Claude Code does, in this
order:

| Credential | How it is set | What pays | What `total_cost_usd` means |
|---|---|---|---|
| API key | `ANTHROPIC_API_KEY` in the subprocess environment | the API, per token | an estimate of the bill |
| Subscription token | `CLAUDE_CODE_OAUTH_TOKEN`, minted with `claude setup-token` | the plan's usage limits | an API-equivalent estimate |
| Stored login | `claude login` once; kept in the keychain (or `CLAUDE_CONFIG_DIR`) | the plan's usage limits | an API-equivalent estimate |
| Cloud provider | `CLAUDE_CODE_USE_BEDROCK=1`, `_VERTEX=1`, `_FOUNDRY=1` or `_ANTHROPIC_AWS=1` plus that cloud's credentials | that provider | that provider's price table |

Two rules from the docs that surprise people:

- **The API key wins.** "When set, this key is used instead of your Claude
  Pro, Max, Team, or Enterprise subscription even if you are logged in. In
  non-interactive mode the key is always used when present." To run on the
  subscription, `unset ANTHROPIC_API_KEY`.
- **The SDK does not load `.env` files.** "The SDK reads the key from the
  environment of the process that runs your agent; it doesn't load `.env` files
  automatically." Your app must load it (for example with `python-dotenv`)
  before calling the SDK. `check_env.py` reads `.env` anyway, and says so, because
  that is where the value usually is.

`ANTHROPIC_BASE_URL` routes traffic through a gateway that can inject the key
outside the container; `agent-deploy` recommends that pattern for hosting.

## Subscription use: what it is for

The quickstart states: "Unless previously approved, Anthropic does not allow
third party developers to offer claude.ai login or rate limits for their
products, including agents built on the Claude Agent SDK." Your own agents and
evals on your own plan are personal use; an agent you host for other people is
not. `agent-deploy` therefore asks for an API key or a provider for anything
multi-tenant, and a `CLAUDE_CODE_OAUTH_TOKEN` in CI is fine for a personal
repository (the token is tied to the plan of whoever ran `claude setup-token`).

On a subscription the real ceiling is the plan's session and weekly usage
limits, which are distinct from HTTP 429 rate limits. The runner records
`RateLimitEvent`s and usage-limit errors in the trace, marks the affected runs
`NOT_EVALUATED`, and exits 3 rather than reporting them as failures.

## The model

This plugin's convention is `CLAUDE_MODEL` in `.env`, read by
`agent.py:build_options()` with `claude-sonnet-5-5` as the fallback. Claude Code
itself reads `ANTHROPIC_MODEL` and the `model` setting, and when nothing sets a
model a session starts on Claude Code's default for the account type (Opus 5.5
on the API and on Pro/Max). Pin the model in the agent and in
`evals/eval_config.json` so a run and its evals agree; the reviewer grades ids
against the deprecations page: `retired` is an error, `retiring` a warning,
aliases (`sonnet`, `opus`) are accepted but move.

## Which Python runs the SDK

The plugin's scripts are stdlib-only and never import `claude_agent_sdk`.
Anything that must (the runner copy in `evals/runner/`, the load probe) is run
through an interpreter resolved in this order:

1. `$AGENT_SDK_PYTHON`
2. a virtualenv (`.venv`, `venv`, `.env`) at or above the project that imports
   `claude_agent_sdk`
3. a `python3` on `PATH` that imports it
4. `uv run --with "claude-agent-sdk>=<minimum>" python`, when `uv` exists
5. none: the script prints the venv commands and exits 2

```bash
python3 -m venv .venv && .venv/bin/pip install claude-agent-sdk
export AGENT_SDK_PYTHON=.venv/bin/python
```

The runner's own `whoami` subcommand prints the credential kind the subprocess
will inherit, so a `--dry-run` shows the billing path before anything starts.

## Checking before a run

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/check_env.py <project-dir>
```

reports the credential and its source, the cost basis, the interpreter and SDK
version, and the model with its policy grade, and exits 1 with the blockers
listed when a run would fail.

---

Sources: `https://code.claude.com/docs/en/agent-sdk/quickstart` (setup, the
provider switches, the third-party note), `https://code.claude.com/docs/en/env-vars`
(`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`), `https://code.claude.com/docs/en/agent-sdk/configuration`
(model selection), `https://code.claude.com/docs/en/agent-sdk/cost-tracking`
(estimates, usage limits), `https://code.claude.com/docs/en/agent-sdk/hosting`
(auth and secrets), `https://code.claude.com/docs/en/model-config` (default model);
this plugin's `lib/agent_sdk_skills/env.py`.
