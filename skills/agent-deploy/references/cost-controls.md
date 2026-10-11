# Cost controls for a hosted agent

## The shape of the bill

Token cost dominates infrastructure cost by an order of magnitude or more. A
minimally provisioned container is roughly $0.05/hour; one long agent session
can spend dollars. So the controls that matter are the ones on the loop, not the
ones on the instance.

Four of them, in the order they bite.

## 1. `max_turns`

The turn ceiling. Two things to know:

- it is **not** a hard stop on assistant turns. Measured: `max_turns=1`
  produced `num_turns=2`, `subtype="success"` — a synthetic `StructuredOutput`
  round-trip counted as a turn without tripping the limit.
- so assert the limit *fired* with `terminal_reason == "max_turns"` or
  `subtype == "error_max_turns"`, never with `num_turns <= max_turns`.

For an ephemeral container it is also what makes the container exit rather than
loop.

## 2. `max_budget_usd`

The spend ceiling, and the only one that bounds a subagent tree. It counts the
call's own spend, subagent requests included, and totals restored from a resumed
session do not count. At the cap Claude Code does three things: refuses to spawn
more subagents (`Budget limit reached`), stops background subagents still
running, and ends the query with `subtype="error_max_budget_usd"`.

It is a **soft cap.** The figure it compares against is the running client-side
estimate, and that estimate can pass the value before the query stops — the docs
say so in as many words and tell you to leave headroom. Treat `max_budget_usd`
as the point at which the run is wound up, not as a figure the bill cannot
exceed: set it above what you can afford to spend, not equal to it.

Caveat that matters for reporting: `total_cost_usd` is a **client-side
estimate** from a bundled price table. On a subscription it is an
API-equivalent figure, not a bill — the real ceiling there is the plan's usage
limits. Each `model_usage` row also carries `costBasis` — `list` (the public
price list), `managed` (an organisation's negotiated rate) or `unknown`, needing
Claude Code **2.1.246+**. It is not on the 0.2.165 `ModelUsage` TypedDict, so
read it with `.get()`; measured 2026-10-11 on an API key it was `"list"` on
every row. A cost figure reported without its basis is not comparable between
two accounts.

And it is **cumulative per session**, not per turn. Measured across two turns of
one `ClaudeSDKClient` session: `0.004991` then `0.0061734`. To get a per-turn
figure, diff consecutive `ResultMessage`s; to get a session figure, take the
last one. Summing them double-counts.

## 3. Subagent caps

Claude decides when to spawn a subagent and how many, and a subagent can spawn
its own. Three limits, two of them environment variables:

| Limit | Set with | Default | At the limit |
|---|---|---|---|
| depth | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` in `env` | 3 layers (`1` stops your subagents spawning any) | the bottom layer does the work itself |
| concurrency | `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` in `env` | 20 at once | refuses to spawn; Claude receives `Concurrent subagent limit reached` as the tool result |
| spend | `max_budget_usd` | none | as above |

In Python, `env` merges into the inherited environment. Opus 5 delegates more
readily than earlier models, so these matter most on Opus runs (`HST012`).

## 4. Cache TTL

Prompt caching is automatic; you do not configure it. `usage` reports it as two
fields: `cache_creation_input_tokens` (charged above standard input) and
`cache_read_input_tokens` (charged below).

The lever is the TTL. Your own turns default to a **5-minute** TTL when you
authenticate with an API key or run on a cloud provider. A workload of many
short sessions against the same system prompt, more than five minutes apart,
pays full input price every time.

- `ENABLE_PROMPT_CACHING_1H=1` requests a 1-hour TTL on cache writes in both
  buckets. 1-hour writes cost more than 5-minute writes, so this trades write
  cost for read hits — worth it only when the gaps really are longer than five
  minutes.
- Per bucket instead: `CLAUDE_CODE_PROMPT_CACHE_TTL` (your turns) and
  `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` (everything else), each `5m` or `1h`,
  both taking precedence over `ENABLE_PROMPT_CACHING_1H`.
- On a Claude subscription within the plan's included usage you get the 1-hour
  TTL on your own turns without setting anything; it drops to 5 minutes once you
  are drawing on usage credits.

**The cache-read price moved, and which price you see depends on the CLI.** The
platform price list now says a cache read costs 10 % of the base input price,
**except 5 % on Opus 5.5 and Sonnet 5.5** — so the list price for a Sonnet 5.5
cache read is **$0.10/Mtok**, and that is what Claude Code **2.1.296** charges.
The CLI bundled with `claude-agent-sdk` 0.2.165 is **2.1.294**, and its estimate
still prices a Sonnet 5.5 cache read at **$0.20/Mtok** — measured 2026-10-11,
40257 cache-read tokens for a $0.0080514 residual, exactly $0.20 per Mtok. So a
cost table in a report has to name the CLI version it was produced on, and a
regression test that pins a cache-heavy total will change value when the CLI
crosses 2.1.296.

## The cheapest optimisation is not a cap at all

Measured on the build machine, same prompt, same model, same host:

| Configuration | Cache-creation tokens | Cost |
|---|---|---|
| default `setting_sources` | 21 503 | $0.0870 |
| `setting_sources=[]`, `tools=[]`, `strict_mcp_config=True` | 111 | ~$0.0050 |

**17x**, all of it ambient configuration being turned into cache-creation
tokens on every run. And separately, `claude -p` with no `--model` picked
`claude-fable-5-1` and cost $0.3397 for the same prompt — about **4x** an
explicit Sonnet. Pin the model and isolate the run before tuning anything else.

## Subscription versus API billing

| | API key | Subscription (login or `CLAUDE_CODE_OAUTH_TOKEN`) |
|---|---|---|
| What pays | the API account, per token | the plan's usage limits |
| `total_cost_usd` | an estimate of the bill | an API-equivalent estimate; not billed |
| Real ceiling | your spend | session and weekly usage limits, distinct from HTTP 429s |
| Hosted use | **required** | not permitted for third-party products without prior approval |

`init.data["apiKeySource"]` is the authoritative read-back of which credential
the subprocess actually chose — `"none"` on all three measured subscription
runs. It is the cheapest signal there is for stamping a cost basis on a result.

## Two time limits that are not budgets

A **background Bash command** has its own ceiling. With `run_in_background`
(Claude Code **2.1.285+**) the `timeout` the tool accepts is the background
limit: default **1800000 ms** (30 minutes), ceiling **7200000 ms** (2 hours)
unless raised. Foreground commands stay capped at 600000 ms. The raising is done
through `BASH_DEFAULT_TIMEOUT_MS` (default 120000) and `BASH_MAX_TIMEOUT_MS`
(default 600000): a value above the default replaces it **in unattended sessions
only**, and an effective ceiling above two hours also becomes the maximum
background time limit. An unattended deployment that sets those two high is
therefore also lengthening how long a background command may burn tokens.

**Retries** cost money too, and three variables bound them:
`CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS` (**2.1.295+**) caps how long the
watchdog waits before giving up on a stalled request;
`CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS` (default **500**, range 500–32000,
**2.1.292+**) sets the backoff base when the API reports overload; and
`CLAUDE_CODE_NONSTREAMING_TIMEOUT_RETRIES` (**2.1.285+**) bounds retries of a
non-streaming request that timed out. Also set
`CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR` deliberately if the agent searches:
the default is **100 interactive but 0 non-interactive** (**2.1.290+**), so a
headless deployment gets no refills unless you ask for them.

Watch for `RateLimitEvent`. Measured, it fires on **every** run, not only near a
limit, carrying `status` (`allowed`, `allowed_warning`, `rejected`),
`rate_limit_type` (`five_hour`, `seven_day`, `seven_day_opus`,
`seven_day_sonnet`, `overage`), `utilization` and `resets_at`, plus a `raw`
dict with per-window figures. Only `rejected` means work stopped;
`allowed_warning` is information.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/cost-tracking> (token
usage, totals, cache tokens, the 1-hour TTL and its controls),
<https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget>,
<https://code.claude.com/docs/en/agent-sdk/subagents#cap-subagent-depth-concurrency-and-spend>,
<https://code.claude.com/docs/en/agent-sdk/hosting#cost>,
<https://code.claude.com/docs/en/env-vars>,
<https://code.claude.com/docs/en/agent-sdk/quickstart> (the third-party policy
note); `claude-agent-sdk` 0.2.165 `types.py:2050` (`max_turns`), `:2056`
(`max_budget_usd`), `:1340-1379` (`ResultMessage`), `:1314` (`ModelUsage`),
`:1398` (`RateLimitInfo`; `:1392` is `RateLimitType`);
<https://platform.claude.com/docs/en/about-claude/models/overview> (the
cache-read percentages),
<https://code.claude.com/docs/en/agent-sdk/python#bash> (the background-command
limit), <https://code.claude.com/docs/en/agent-sdk/agent-loop#budget-headroom>.
The 17x and 4x figures, the cumulative-cost behaviour, the
`max_turns=1 → num_turns=2` result and the `RateLimitEvent` shape were measured
by this plugin on 2026-09-30 on a Claude Max subscription with no API key set;
`costBasis` and the $0.20/Mtok cache-read price of the bundled CLI 2.1.294 were
measured 2026-10-11 with `ANTHROPIC_API_KEY` set. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs.
