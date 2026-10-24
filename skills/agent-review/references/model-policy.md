# The model policy, and why it exists

## What the plugin grades

`lib/agent_sdk_skills/env.py:classify_model_id` puts every id it sees into one
of eight grades. The grade decides the finding, not the string.

| Grade | What it means | Finding |
|---|---|---|
| `pinned` | any other `claude-`/`*.anthropic.claude-` id: a dated snapshot, or a model newer than this plugin's lists | `AGT010` if it is a literal in the options |
| `alias` | `sonnet`, `opus`, `haiku`, `fable`, `best`, `default`, `opusplan` | none; the CLI resolves it at run time |
| `env` | read from the environment (`os.getenv`, `${VAR}`) | none for the pattern; the **default** is graded on its own |
| `current` | listed in `CURRENT_MODELS`: Sonnet 5.5, Opus 5.5, Fable 5.1, Haiku 5.5 | `AGT010` if it is a literal, nothing else |
| `deprecated` | listed in `DEPRECATED_MODELS`: deprecated upstream with a **committed** retirement date | `AGT011` warn with the date in the message (`SUB002` for a subagent) |
| `retiring` | listed in `RETIRING_MODELS`: past or within about 60 days of its "retirement not sooner than" date | `AGT011` warn (`SUB002` for a subagent) |
| `retired` | listed in `RETIRED_MODELS`, or a `claude-2`/`claude-3` id | `AGT012` error (`SUB002` error) |
| `unknown` | anything else: a string that is not a Claude id at all — a typo, or another provider's name | none, but the review says it could not grade it |

The lists live in `lib/agent_sdk_skills/__init__.py` and are re-pinned at each
upstream sync from the deprecations page. **As of 2026-10-24** (no id, price or
date changed since 2026-10-11):

| Id | Status |
|---|---|
| `claude-sonnet-5-5` | current; this plugin's default and judge default. $2 / $10 per Mtok, 1M context, default effort `high` |
| `claude-opus-5-5` | current. $4 / $20, 1M, `medium` |
| `claude-fable-5-1` | current. $10 / $50, 1M, `high` |
| `claude-haiku-5-5` | current, and the **cheap judge option**. From $0.10 / from $0.50, 1M by default on every plan (no `[1m]` suffix), default effort `medium`, adaptive reasoning that cannot be turned off. The `haiku` alias resolves to it on the Anthropic API from Claude Code **2.1.293** (Bedrock, Vertex, Foundry and Claude Platform on AWS still get Haiku 4.5). "From" is literal: **it costs more per token once a prompt passes 100K tokens** |
| `claude-sonnet-4-5-20250929` | **deprecated 2026-09-30, retires 2026-11-30**, replacement `claude-sonnet-5-5` → `deprecated` |
| `claude-haiku-4-5-20251001` | retirement "not sooner than" 2026-10-15 → `retiring`. The date passed nine days ago with no announcement: the deprecations page still lists it **Active** with that date, so it stays `retiring` rather than `retired` until the page says otherwise |
| `claude-opus-4-5-20251101` | retirement not sooner than 2026-11-24 → `retiring` |
| every `claude-3-*`, `claude-opus-4-*` (4.0/4.1), `claude-sonnet-4-20250514` | `retired` |

Haiku 5.5 is named as the cheap judge, not made the default: `DEFAULT_MODEL` and
`DEFAULT_JUDGE_MODEL` both stay `claude-sonnet-5-5`, so a suite's scores stay
comparable with the ones already recorded. Pick Haiku 5.5 per grader when the
rubric is a yes/no check on short output.

Whose policy is which matters. **Deprecations and retirement dates are
Anthropic's**, published on the deprecations page; a `deprecated` grade therefore
carries a real date. **The 60-day warning window is this plugin's**, so a
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

`ResultMessage.model_usage` carries a row per model the session billed, and the
CLI bills its own background work there. On the 2026-09-30 runs (bundled CLI
2.1.285) the second row was `claude-haiku-4-5-20251001` — a **retiring** id, and
not something the agent asked for. Re-measured 2026-10-11 on SDK 0.2.165 with
bundled CLI **2.1.294**, the second row is `claude-haiku-5-5`: 1192 input and 26
output tokens, `costUSD` $0.0001322, which is exactly $0.10 and $0.50 per Mtok.
So 2.1.294 already routes background work to Haiku 5.5, and 2.1.301 and 2.1.310
do too (measured 2026-10-17 and 2026-10-24: 1179 in / 19 out, again exactly $0.10
and $0.50 per Mtok). The agent's own Sonnet 5.5 cache reads are priced at the list
**$0.10/Mtok** by the 2.1.301 and 2.1.310 estimates; 2.1.294 charged $0.20 (history, see
`agent-deploy/references/cost-controls.md`). Consequences for a review and for
graders:

- a retiring or deprecated id appearing in `model_usage` is **not** a finding;
  only an explicitly configured one is;
- "which model actually answered" is `AssistantMessage.model`, not
  `model_usage.keys()`;
- `model_usage` routinely holds **more than one model**, so read it with a loop,
  never `next(iter(...))`, and a per-model budget assertion has to allow the
  background model;
- each row also carries `costBasis` (`list` | `managed` | `unknown`, Claude Code
  2.1.246+) and `thinkingTokens`, neither of which is on the 0.2.174
  `ModelUsage` TypedDict — read both with `.get()`.

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
spend cap instead. Calling the Messages API directly is no longer an escape for
the sampling knobs: the deprecations page says `temperature`, `top_p` and
`top_k` are "Removed in API version `2026-10-21`" (a 400 error; earlier API
versions return it for a non-default value on Claude 4.7 and later models), so
code that still sends them — a hand-written judge, say — must drop them.

The models overview adds a capability to read before turning thinking off:
each model's `capabilities` includes `thinking.types.between_tools` (whether it
accepts `thinking: {type: "between_tools"}`); for Sonnet 5.5 the Models API
reports it `true` and `thinking.types.disabled.supported` `false`. The SDK's
`ThinkingConfig` has no `between_tools` variant at 0.2.174.

---

Sources:
<https://platform.claude.com/docs/en/about-claude/model-deprecations> (lifecycle
table; the parameter table for API version `2026-10-21`),
<https://platform.claude.com/docs/en/about-claude/models/overview>
(`thinking.types.between_tools`),
<https://code.claude.com/docs/en/agent-sdk/configuration#choose-a-model>,
<https://code.claude.com/docs/en/model-config#default-model-setting>,
<https://code.claude.com/docs/en/agent-sdk/subagents#agentdefinition-configuration>,
<https://code.claude.com/docs/en/agent-sdk/cost-tracking#break-down-usage-per-model>;
<https://code.claude.com/docs/en/model-config#haiku-5-5-context-window-and-pricing>;
`claude-agent-sdk` 0.2.174 `types.py:2425` (`model`), `:2431`
(`fallback_model`), `:2728` (`effort`), `:1669` (`ModelUsage`), `:2172-2185`
(`ThinkingConfig`). The cost table
was measured by this plugin on 2026-09-30 against SDK 0.2.162 (bundled CLI
2.1.285) and system CLI 2.1.274, on a Claude Max subscription with no API key
set; the two-model `model_usage` figures were measured 2026-10-11 on SDK 0.2.165
(bundled CLI 2.1.294) with `ANTHROPIC_API_KEY` set, again on 2026-10-17 on SDK
0.2.168 (bundled CLI 2.1.301) and on 2026-10-24 on SDK 0.2.174 (bundled CLI
2.1.310). Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code
2.1.296 docs; re-read 2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code
2.1.310 docs.
