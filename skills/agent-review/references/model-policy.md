# The model policy, and why it exists

## What the plugin grades

`lib/agent_sdk_skills/env.py:classify_model_id` puts every id it sees into one
of six grades. The grade decides the finding, not the string.

| Grade | What it means | Finding |
|---|---|---|
| `pinned` | a current id, dated or dateless | `AGT010` if it is a literal in the options |
| `alias` | `sonnet`, `opus`, `haiku`, `fable`, `best`, `default`, `opusplan` | none; the CLI resolves it at run time |
| `env` | read from the environment (`os.getenv`, `${VAR}`) | none for the pattern; the **default** is graded on its own |
| `retiring` | listed in `RETIRING_MODELS`: past or within about 60 days of its "retirement not sooner than" date | `AGT011` warn (`SUB002` for a subagent) |
| `retired` | listed in `RETIRED_MODELS`, or a `claude-2`/`claude-3` id | `AGT012` error (`SUB002` error) |
| `unknown` | anything else: a typo, or a model newer than this plugin | none, but the review says it could not grade it |

The lists live in `lib/agent_sdk_skills/__init__.py` and are re-pinned at each
upstream sync from the deprecations page. As of the 2026-09-30 snapshot:

| Id | Status |
|---|---|
| `claude-sonnet-5-5` | current; this plugin's default and judge default |
| `claude-opus-5-5`, `claude-fable-5-1` | current |
| `claude-sonnet-4-5-20250929` | retirement not sooner than 2026-09-29 → `retiring` |
| `claude-haiku-4-5-20251001` | retirement not sooner than 2026-10-15 → `retiring` |
| `claude-opus-4-5-20251101` | retirement not sooner than 2026-11-24 → `retiring` |
| every `claude-3-*`, `claude-opus-4-*` (4.0/4.1), `claude-sonnet-4-20250514` | `retired` |

Whose policy is which matters. **Retirement dates are Anthropic's**, published
on the deprecations page. **The 60-day warning window is this plugin's**, so a
`retiring` finding is advice with a date attached, not a defect.

## Why a hardcoded id is a warning and not a style note

A dated id is a promise with an expiry. When it passes, requests fail and the
agent stops working on a date nobody wrote down in the project. The fix is one
line:

```python
model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
```

That makes the id a deployment decision instead of a source constant, and it
lets an eval run pin the same model the production agent uses without editing
code. The reviewer treats the env default as the id to grade, so a stale default
is still caught.

## Why "no model at all" is worse than a hardcoded one

Nothing in the Agent SDK defaults the model. With `model` unset, the session
starts on **Claude Code's default for the account**, which can change under you
without any change in your repository.

Measured on the build machine, with no `--model` and no `model` option:

| Run | Model reported | Cost for "reply with exactly: ready" |
|---|---|---|
| `claude -p` (no `--model`) | `claude-fable-5-1` | $0.3397 |
| SDK `query()`, `model="claude-sonnet-5-5"`, default `setting_sources` | `claude-sonnet-5-5` | $0.0870 |
| SDK `query()`, `model="claude-sonnet-5-5"`, `setting_sources=[]`, `tools=[]`, `strict_mcp_config=True` | `claude-sonnet-5-5` | $0.0050 |

About 4x between the inherited default and an explicit Sonnet, and 17x again
between an unisolated and an isolated run. That is why `OPT012` is a warning
rather than a note: an unpinned model costs more, and two runs of the same eval
may not even be comparable.

## The model you asked for is not the only model billed

`ResultMessage.model_usage` on every measured run also carried
`claude-haiku-4-5-20251001`, about 900 input and 10 output tokens (≈ $0.0009)
for CLI-internal work. Consequences for a review and for graders:

- a retiring id appearing in `model_usage` is **not** a finding; only an
  explicitly configured retiring id is;
- "which model actually answered" is `AssistantMessage.model`, not
  `model_usage.keys()`;
- a per-model budget assertion has to allow the internal model.

## Subagent models

An `AgentDefinition.model` takes an alias, a full id, or `'inherit'`. Omitted,
Claude Code picks from the subagent model order. `'inherit'` is usually the
right answer for an eval: it keeps one variable in the experiment instead of
two. A pinned dated id in a subagent is the same clock as `AGT011`, reported as
`SUB002`.

## Fallbacks

`fallback_model` (a single id, or a comma-separated chain) switches when the
primary is overloaded. The primary is retried at the start of each user turn, so
a session returns to it once an outage passes. For evals, a fallback makes a run
less likely to fail and less likely to be comparable — record which model
answered, or leave `fallback_model` unset in the eval configuration.

## What the SDK does not have

`temperature`, `top_p` and `max_tokens` have no fields on `ClaudeAgentOptions`
in either language. Use `effort` (`low`, `medium`, `high`, `xhigh`, `max`) or a
spend cap instead, or call the Messages API directly when you need those
parameters.

---

Sources:
<https://platform.claude.com/docs/en/about-claude/model-deprecations>,
<https://platform.claude.com/docs/en/about-claude/models/overview>,
<https://code.claude.com/docs/en/agent-sdk/configuration#choose-a-model>,
<https://code.claude.com/docs/en/model-config#default-model-setting>,
<https://code.claude.com/docs/en/agent-sdk/subagents#agentdefinition-configuration>,
<https://code.claude.com/docs/en/agent-sdk/cost-tracking#break-down-usage-per-model>;
`claude-agent-sdk` 0.2.162 `types.py:2070` (`model`), `:2076`
(`fallback_model`), `:2372` (`effort`). The cost table and the `model_usage`
observation were measured by this plugin on 2026-09-30 against SDK 0.2.162
(bundled CLI 2.1.285) and system CLI 2.1.274, on a Claude Max subscription with
no API key set.
