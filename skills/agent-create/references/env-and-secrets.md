# `.env`, credentials and what actually pays for a run

Two facts surprise people, and between them they cause most of the confusion
about cost in an Agent SDK project.

## 1. The SDK does not read `.env`

There is no dotenv loading anywhere in `claude-agent-sdk`. A `.env` file next to
your agent does nothing until something loads it:

```python
from dotenv import load_dotenv      # python-dotenv, a separate dependency
load_dotenv()                        # before build_options()
```

...or the variables are exported by the shell, the workflow, or the process
manager. So `.env.example` in a scaffolded project is **documentation**: it
names the variables that matter and shows their shape. It is not configuration
that takes effect on its own.

`ClaudeAgentOptions.env` passes variables down to the CLI subprocess, but it
can only *override* an inherited variable, never remove one. If the parent
shell exported `ANTHROPIC_API_KEY`, the child sees it. That is why the runner
scrubs the names listed in `trace.redact_env` from its own environment copy
before spawning, and why the trace records what the child actually resolved
rather than what the config asked for.

## 2. The credential is resolved by the CLI, not by your code

Your agent never mentions a credential. The bundled CLI picks one, in this
order:

| Order | Mechanism | What it means for cost |
|---|---|---|
| 1 | `ANTHROPIC_API_KEY` | bills the API. **Wins even when you are logged in.** |
| 2 | `CLAUDE_CODE_OAUTH_TOKEN` | draws on the plan of whoever ran `claude setup-token` |
| 3 | stored login (macOS Keychain) | draws on your Claude subscription |
| 4 | `apiKeyHelper` in user settings | whatever the helper returns |
| — | none of the above | the run fails before the first turn (`ENV010`) |

`CLAUDE_CODE_USE_BEDROCK`, `_VERTEX` and `_FOUNDRY` switch the backend
entirely; two of them set at once is `ENV011`.

The practical trap is order 1: developers set a key months ago, forget, and
wonder why their subscription plan is not being drawn down. `check_env.py`
reports the active credential by name, and the reports here always repeat it
before anything runs.

## What `total_cost_usd` means on a subscription

`ResultMessage.total_cost_usd` is computed client-side from a bundled price
table. On an API key it is an estimate of the bill. On a subscription **nothing
is billed at all** — the real ceiling is the plan's session and weekly usage
limits, which are separate from HTTP 429 rate limits. The figure is still
useful (it is the only comparable number across runs) but the reports label it
"est. API-equivalent USD" and say the basis.

When a usage limit is hit mid-suite the runner marks the affected runs
`NOT_EVALUATED` and exits 3. That is the honest outcome: nothing regressed,
nothing was measured.

## What belongs in `.env.example`

```bash
CLAUDE_MODEL=claude-sonnet-5-5
# ANTHROPIC_API_KEY=sk-ant-...
# CLAUDE_CODE_OAUTH_TOKEN=...
# AGENT_ENTRY=agent:build_options
```

Both credentials commented out, on purpose. An uncommented placeholder invites
someone to paste a real key into a tracked file, and a real key in
`.env.example` is the single most common way a secret reaches a public
repository.

## `.gitignore`

Two lines, and the scaffold merges them into whatever is already there:

```
.env
evals/results/
```

`.env` is obvious. `evals/results/` is less so: result directories contain
`*.trace.jsonl`, and a trace carries prompt text, tool inputs and up to 2 KB of
each tool result. For a library agent that is book titles; for a support agent
it is customer messages. Traces are evidence, and evidence is not something to
commit by reflex — CI uploads them as build artifacts instead.

A `.env` that is already tracked is worse than one that is ignored, because the
ignore rule does not untrack it. `ENV020` reports the file; removing it needs
`git rm --cached .env` and, if it ever held a real key, rotating that key.

## CI

Use a repository secret, never a literal:

```yaml
env:
  CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

An OAuth token from `claude setup-token` is tied to one person's plan and
expires. That suits a personal repository. For an organization-wide gate, use
an API key: it belongs to the organization, not to whoever happened to mint the
token. `/agent-sdk:eval-ci` generates both shapes.

Sources: `lib/agent_sdk_skills/env.py` (the resolution order and
`CredentialInfo`); `.dev/CONTRACTS.md` §3 (credential `auto` resolution, the
four mechanisms) and §5.2 (`total_cost_usd` as a client-side estimate);
https://code.claude.com/docs/en/agent-sdk/python (`ClaudeAgentOptions.env`,
`ResultMessage`); https://code.claude.com/docs/en/claude-code/settings
(`apiKeyHelper`, environment variables);
https://code.claude.com/docs/en/agent-sdk/secure-deployment (keeping
credentials out of the repository).
