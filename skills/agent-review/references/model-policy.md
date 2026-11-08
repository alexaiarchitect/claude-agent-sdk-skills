# The model policy, and why it exists

## What the plugin grades

`lib/agent_sdk_skills/env.py:classify_model_id` puts every id it sees into one
of eight grades. The grade decides the finding, not the string.

| Grade | What it means | Finding |
|---|---|---|
| `pinned` | any other `claude-`/`*.anthropic.claude-` id: a dated snapshot, or a model newer than this plugin's lists | `AGT010` if it is a literal in the options |
| `alias` | `sonnet`, `opus`, `haiku`, `fable`, `best`, `default`, `opusplan` | none; the CLI resolves it at run time |
| `env` | read from the environment (`os.getenv`, `${VAR}`) | none for the pattern; the **default** is graded on its own |
| `current` | listed in `CURRENT_MODELS`: Sonnet 5.5, Opus 5.5, Fable 5.2, Fable 5.1 (legacy, still available), Haiku 5.5 | `AGT010` if it is a literal, nothing else |
| `deprecated` | listed in `DEPRECATED_MODELS`: deprecated upstream with a **committed** retirement date | `AGT011` warn with the date in the message (`SUB002` for a subagent) |
| `retiring` | listed in `RETIRING_MODELS`: past or within about 60 days of its "retirement not sooner than" date | `AGT011` warn (`SUB002` for a subagent) |
| `retired` | listed in `RETIRED_MODELS`, or a `claude-2`/`claude-3` id | `AGT012` error (`SUB002` error) |
| `unknown` | anything else: a string that is not a Claude id at all — a typo, or another provider's name | none, but the review says it could not grade it |

The lists live in `lib/agent_sdk_skills/__init__.py` and are re-pinned at each
upstream sync from the deprecations page. **As of 2026-11-14**: Claude Fable 5.2
launched on 2026-11-09 and joins the list; Fable 5.1 is now a **legacy** model on the models page
("still available", no deprecation, retirement not sooner than 2027-09-01), so it stays `current`;
nothing else moved since 2026-10-11. "Default effort" below is the Claude API's
default from the models overview; Claude Code's own default differs for the 5.5
family (next section):

| Id | Status |
|---|---|
| `claude-sonnet-5-5` | current; this plugin's default and judge default. $2 / $10 per Mtok, 1M context, default effort `high` |
| `claude-opus-5-5` | current. $4 / $20, 1M, `medium` |
| `claude-fable-5-2` | current (launched 2026-11-09). $8 / $40, cache reads $0.20, 1M, 128k output, API default effort `high` (Claude Code: `medium`); needs Claude Code **2.1.321+**; what the `fable` alias resolves to from 2.1.321 (Fable 5 in Claude apps gateway sessions); fast mode on the Anthropic API; retirement not sooner than 2027-11-09 |
| `claude-fable-5-1` | current but **legacy** (still available): $10 / $50, 1M, `high`; retirement not sooner than 2027-09-01. A `claude-fable-5-1` saved in user settings moves to the `fable` alias on Pro, Max and Ultra at the first run of 2.1.321+; project, local and managed settings keep it |
| `claude-haiku-5-5` | current, and the **cheap judge option**. From $0.10 / from $0.50, 1M by default on every plan (no `[1m]` suffix), default effort `medium`, adaptive reasoning that cannot be turned off. The `haiku` alias resolves to it on the Anthropic API from Claude Code **2.1.293** (Bedrock, Vertex, Foundry and Claude Platform on AWS still get Haiku 4.5). "From" is literal: **it costs more per token once a prompt passes 100K tokens** |
| `claude-sonnet-4-5-20250929` | **deprecated 2026-09-30, retires 2026-11-30**, replacement `claude-sonnet-5-5` → `deprecated` |
| `claude-haiku-4-5-20251001` | retirement "not sooner than" 2026-10-15 → `retiring`. The date passed 24 days ago with no announcement: the deprecations page still lists it **Active** with that date, so it stays `retiring` rather than `retired` until the page says otherwise |
| `claude-opus-4-5-20251101` | retirement not sooner than 2026-11-24 → `retiring` |
| every `claude-3-*`, `claude-opus-4-*` (4.0/4.1), `claude-sonnet-4-20250514` | `retired` |

**Effort and names in Claude Code (docs read 2026-10-29, re-read 2026-11-14).** When nothing sets
effort, Claude Code uses `high` except on Fable 5.2, Opus 5.5, Sonnet 5.5 and Haiku 5.5
(`medium`) and Opus 4.7 (`xhigh`); `CLAUDE_CODE_EFFORT_LEVEL` outranks the
`effort` option (order in `agent-harness/references/context-and-settings.md`).
So an agent on `claude-sonnet-5-5` with no `effort` runs at `medium` through the
SDK although the API default is `high` — set `effort` if a comparison depends on
it. From **2.1.311** model names drop the `[1m]` suffix where it has no effect
(the 5.x models already run with 1M); the suffix is still accepted. From
**2.1.312** automatic model switches after a flagged message also cover model
names Claude Code does not recognise (custom deployment names);
`CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK=1` turns those switches off, which keeps an
eval on the model it configured. From **2.1.314** a session whose organisation's
admin caps a model's effort no longer fails turn after turn with "Invalid effort
level": Claude Code lowers the effort, retries and says which level it uses — so
an eval's recorded `effort` can be lower than the one it asked for. **Subagents
and teammates** with no `effort` of their own run at the session's level only on
the session's model; on another model that level does not apply (docs
`model-config`, read 2026-11-04) and they use that model's saved level or its
default (2.1.317). Set `effort` on an `AgentDefinition` whose `model` differs.

**Fast mode on Opus 4.8 is deprecated** (Claude Code `CHANGELOG.md` 2.1.316, not
yet on the models pages; the settings reference read 2026-11-14 says Fable 5.2, Opus 5.5, Opus 5 and
Opus 4.8 support fast mode on the Anthropic API, and 2.1.322 added it on Vertex): deprecated as of 2026-10-30 and removed on
**2026-11-30**; after that a fast-mode request on Opus 4.8 returns an error and
does **not** fall back to standard Opus 4.8. Migrate to Opus 5.5 to keep the
speedup. An agent that pins Opus 4.8 with fast mode on (`fast_mode_state` in the
init message, `options-reference.md`) breaks on that date rather than slowing down.
Plan lists in the docs now include the **Ultra** plan (Pro, Max, Ultra, Team,
Enterprise); nothing in this policy differs by plan.

**Aliases moved in 2.1.321** (`model-config` version table, read 2026-11-14): `fable` resolves to Fable
5.2 (Fable 5 in Claude apps gateway sessions) and **`best` resolves to the same model as `opus`** — earlier
versions used the Fable model where Fable was available. An agent that pins `best` or `fable` changed
model on 2026-11-09 without a change in its repository; pin ids when results must stay comparable.

**Sonnet 5.5 or Opus 5.5.** Anthropic's Sonnet 5.5 guide (2026-09-28, written for the Messages API)
puts Sonnet 5.5 on well-scoped work "when the task has a clear spec and a way to check the result",
and Opus 5.5 on long-horizon work that needs careful judgment; effort levels are recalibrated per
model, so re-run an effort sweep rather than carry a level over. Its Opus 5.5 companion (2026-09-22,
Claude apps and Claude Code) adds: give the whole task with a finish line, drop "think carefully"
lines in favour of `effort`, and check a subagent's evidence before accepting its report. In the SDK
these map to `model`, `effort` and the prompt; none of it changes the grades above.

**Which model to build with** (Osmani, 2026-11-09, article #42; it names the Agent SDK): start most
work on Opus 5.5 at `medium`; move down to Sonnet 5.5 for well-scoped work and to Haiku 5.5 for
classification, routing and subagent side tasks; move up to Fable 5.2 for the hardest technical
projects or long unattended runs, or when Opus 5.5 at `high` still falls short. Before changing model,
give the agent a way to verify its own work (a test, a build, a script), then raise effort one level
before moving up a model — past `high`, one more level can cost as much as a bigger model. Price the
hardest tasks in a set, which carry most of the spend. The platform's what's-new page adds that
**nothing changes when Claude Code, Claude Managed Agents or the Agent SDK build the requests**: the
Fable 5.2 prefix check (a 400 when anything before a Fable 5.2 thinking block changed) and
thinking-block binding concern code that assembles Messages API requests itself. Its prompting guide
describes Fable 5.2 behaviour, not SDK behaviour; `agent-design/references/agent-loop.md` carries the
parts a loop must handle (a turn can end before the work is done).

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
starts on **Claude Code's default for the account** — Opus 5.5 on every plan and on the API unless a
model is saved in the account's user settings (`model-config`, read 2026-11-14) — which can change
under you without any change in your repository.

Measured on the build machine, with no `--model` and no `model` option:

| Run | Model reported | Cost for "reply with exactly: ready" |
|---|---|---|
| `claude -p` (no `--model`), API key, Claude Code 2.1.322, 2026-11-10 | `claude-opus-5-5` | $0.0667 |
| `claude -p --model claude-sonnet-5-5`, same day | `claude-sonnet-5-5` | $0.0331 |
| `claude -p` (no `--model`), subscription auth, 2026-10-11 | `claude-fable-5-1` | $0.3397 — the model recorded on that account, not a default |
| SDK `query()`, `model="claude-sonnet-5-5"`, default `setting_sources` | `claude-sonnet-5-5` | $0.0870 |
| SDK `query()`, `model="claude-sonnet-5-5"`, `setting_sources=[]`, `tools=[]`, `strict_mcp_config=True` | `claude-sonnet-5-5` | $0.0050 |

About 2x between the inherited default and an explicit Sonnet with an API key (4x on the
subscription run), and 17x again between an unisolated and an isolated run. That is why `OPT012` is a warning
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
  2.1.246+) and `thinkingTokens`, neither of which is on the 0.2.182
  `ModelUsage` TypedDict — read both with `.get()`.

## Subagent models

An `AgentDefinition.model` takes an alias, a full id, or `'inherit'`. Omitted,
Claude Code picks from the subagent model order. `'inherit'` means the model of the agent that
spawned this one — a nested subagent inherits its parent subagent, not the main conversation (docs
2026-11-14) — and the built-in Explore subagent runs on the parent's model (Fable → Opus on the API),
no longer always on Haiku (`agent-harness/references/subagent-design.md`). `'inherit'` is usually the
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
`ThinkingConfig` has no `between_tools` variant at 0.2.182.

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
<https://code.claude.com/docs/en/model-config#haiku-5-5-context-window-and-pricing>,
<https://code.claude.com/docs/en/model-config> (effort resolution and Claude
Code's per-model defaults, `[1m]` variants), <https://code.claude.com/docs/en/env-vars>
(`CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.311 `[1m]`
suffix, 2.1.312 refusal fallback, 2.1.314 "Invalid effort level" retry, 2.1.316
Opus 4.8 fast-mode deprecation, 2.1.317 subagent effort on another model);
<https://code.claude.com/docs/en/settings-reference> (fast-mode models);
<https://code.claude.com/docs/en/model-config> (v2.1.321 rows: `fable` → Fable 5.2, `best` → `opus`;
Fable 5.2 default effort; the saved `claude-fable-5-1` move; read 2026-11-14),
<https://platform.claude.com/docs/en/models/fable-5-2/whats-new-fable-5-2> (read 2026-11-14: prices,
1M/128k, adaptive thinking always on, the prefix check, "nothing changes" for Claude Code, Managed
Agents and Agent SDK requests), <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-2>
(read 2026-11-14), <https://www.anthropic.com/claude-fable-and-mythos-5-2> ("Introducing Claude Fable
5.2 and Claude Mythos 5.2", 2026-11-09, launch page), <https://claude.dev/blog/which-claude-model-should-you-build-with/>
("Which Claude model should you build with? Fable, Opus, Sonnet, or Haiku", 2026-11-09, the model
ladder, effort before model, self-verification first, price the hardest tasks; names the Agent SDK);
<https://claude.dev/blog/building-with-claude-sonnet-5-5/> ("Building with Claude Sonnet 5.5",
2026-09-28, Sonnet versus Opus, per-model effort sweep);
<https://claude.dev/blog/getting-the-most-out-of-opus-5-5/> ("Getting the most out of Opus 5.5 in
Claude and Claude Code", 2026-09-22, a finish line, effort over "think" lines, checking subagent
evidence); `claude-agent-sdk` 0.2.182 `types.py:2440` (`model`), `:2446`
(`fallback_model`), `:2746` (`effort`), `:1682` (`ModelUsage`), `:2185-2198`
(`ThinkingConfig`). The cost table
was measured by this plugin on 2026-09-30 against SDK 0.2.162 (bundled CLI
2.1.285) and system CLI 2.1.274, on a Claude Max subscription with no API key
set; the two-model `model_usage` figures were measured 2026-10-11 on SDK 0.2.165
(bundled CLI 2.1.294) with `ANTHROPIC_API_KEY` set, again on 2026-10-17 on SDK
0.2.168 (bundled CLI 2.1.301) and on 2026-10-24 on SDK 0.2.174 (bundled CLI
2.1.310). Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code
2.1.296 docs; re-read 2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code
2.1.310 docs; line numbers re-pinned to 0.2.178 on 2026-11-04 (unchanged in 0.2.179) and to 0.2.182
on 2026-11-14. Model ids, prices and dates unchanged on 2026-11-08; Fable 5.2 added and the
default-model row re-measured with an API key (2.1.322) on 2026-11-10.
Re-read 2026-11-08 against claude-agent-sdk 0.2.179 / Claude Code 2.1.319 docs.
Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
