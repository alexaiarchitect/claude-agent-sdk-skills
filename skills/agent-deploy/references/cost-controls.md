# Cost controls for a hosted agent

## The shape of the bill

Token cost dominates infrastructure cost by an order of magnitude or more. A minimally provisioned container is
roughly $0.05/hour; one long agent session can spend dollars. So the controls that matter are the ones on the loop,
not the ones on the instance.

Four of them, in the order they bite.

## 1. `max_turns`

The turn ceiling. Size it as the docs say: count each turn with tool calls, plus one for the final text-only response
— without that extra turn the run ends with `error_max_turns` and no final response (measured 2026-10-29:
`max_turns=1` with one tool call needed gave no answer at all). Two more things to know:

- it is **not** a hard stop on assistant turns. Measured: `max_turns=1`
  produced `num_turns=2`, `subtype="success"` — a synthetic `StructuredOutput`
  round-trip counted as a turn without tripping the limit.
- so assert the limit *fired* with `terminal_reason == "max_turns"` or
  `subtype == "error_max_turns"`, never with `num_turns <= max_turns`.

For an ephemeral container it is also what makes the container exit rather than loop.

**Effort is a cost lever too.** Thinking tokens bill as output. Set `effort` per agent, or `CLAUDE_CODE_EFFORT_LEVEL`
in `env`, which outranks the option; with nothing set, Opus 5.5, Sonnet 5.5 and Haiku 5.5 run at `medium` in Claude
Code (`agent-harness/references/context-and-settings.md` has the order). Anthropic's notes on Claude Code's `/effort`
(Shihipar, 2026-09-25; `effort` is the SDK side of it) find that higher effort mostly buys verification and edge-case
testing: it pays on tasks with many hidden edge cases and does not fix a wrong approach, and with a detailed spec
outputs converge across levels. So raise effort for the checking step, not for every turn.

**Price the task, not the token.** Osmani's breakdown of Claude Code costs on Opus 5.5 (2026-09-25; its prices are a
snapshot, not repeated here) puts a task's cost at turns × resent context (mostly cache reads) plus output, thinking
included: "A turn costs more than the tokens it adds, because it resends everything before it." Fewer turns is the
cheapest saving, so give the agent a way to check its own work (a test, a build); raise `effort` before moving to a
bigger `model`, and do not carry an effort level across models, since levels mean different amounts of thinking per
model (the Sonnet 5.5 guide of 2026-09-28 says the same: re-run the effort sweep); put search and log-reading
subagents on a smaller `agents[*].model`. Measure on your own task: run it per setting and compare `num_turns`, output
tokens, cache-read share and `total_cost_usd`.

## 2. `max_budget_usd`

The spend ceiling, and the only one that bounds a subagent tree. It counts the call's own spend, subagent requests
included, and totals restored from a resumed session do not count. At the cap Claude Code does three things: refuses
to spawn more subagents (`Budget limit reached`), stops background subagents still running, and ends the query with
`subtype="error_max_budget_usd"`.

It is a **soft cap.** The figure it compares against is the running client-side estimate, and that estimate can pass
the value before the query stops — the docs say so in as many words and tell you to leave headroom. Treat
`max_budget_usd` as the point at which the run is wound up, not as a figure the bill cannot exceed: set it above what
you can afford to spend, not equal to it. For a scheduled agent, start the cap at three to five times a normal run's
cost and tighten it from real runs (Martin, Avilla, 2026-10-08, about Managed Agents, where the cap pauses a run); in
the SDK the run ends, so a cap set too low reads as a short, quiet result.

Caveat that matters for reporting: `total_cost_usd` is a **client-side estimate** from a bundled price table, unless
an administrator's `modelPricing` table (managed settings) is in effect; for authoritative billing the cost-tracking
page now points to `costs#manage-costs-for-your-organization` (docs read 2026-11-04), and says not to bill end users
from these fields. On a subscription it is an API-equivalent figure, not a bill — the real ceiling there is the plan's
usage limits. Each `model_usage` row also carries `costBasis` — `list` (the public price list), `managed` (a
`modelPricing` table) or `unknown`, needing Claude Code **2.1.246+**. It is not on the 0.2.182 `ModelUsage` TypedDict,
so read it with `.get()`; measured 2026-10-11 on an API key it was `"list"` on every row. A cost figure reported
without its basis is not comparable between two accounts.

And it is **cumulative per session**, not per turn. Measured across two turns of one `ClaudeSDKClient` session:
`0.004991` then `0.0061734`. To get a per-turn figure, diff consecutive `ResultMessage`s; to get a session figure,
take the last one. Summing them double-counts.

## 3. Subagent caps

Claude decides when to spawn a subagent and how many, and a subagent can spawn its own. Three limits, two of them
environment variables:

| Limit | Set with | Default | At the limit |
|---|---|---|---|
| depth | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` in `env` | 3 layers (`1` stops your subagents spawning any) | the bottom layer does the work itself |
| concurrency | `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` in `env` | 20 at once | refuses to spawn; Claude receives `Concurrent subagent limit reached` as the tool result |
| spend | `max_budget_usd` | none | as above |

In Python, `env` merges into the inherited environment. Opus 5 delegates more readily than earlier models, so these
matter most on Opus runs (`HST012`).

## 4. Cache TTL

Prompt caching is automatic; you do not configure it. `usage` reports it as two fields: `cache_creation_input_tokens`
(charged above standard input) and `cache_read_input_tokens` (charged below).

The lever is the TTL. Your own turns default to a **5-minute** TTL when you authenticate with an API key or run on a
cloud provider. A workload of many short sessions against the same system prompt, more than five minutes apart, pays
full input price every time.

- `ENABLE_PROMPT_CACHING_1H=1` requests a 1-hour TTL on cache writes in both buckets. 1-hour writes
  cost more than 5-minute writes, so this trades write cost for read hits — worth it only when the
  gaps really are longer than five minutes.
- Per bucket instead: `CLAUDE_CODE_PROMPT_CACHE_TTL` (your turns) and
  `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` (everything else), each `5m` or `1h`,
  both taking precedence over `ENABLE_PROMPT_CACHING_1H`.
- On a Claude subscription within the plan's included usage you get the 1-hour TTL on your own turns
  without setting anything; it drops to 5 minutes once you are drawing on usage credits
  (`promptCacheTtl: "1h"` keeps it). The Claude Code costs page no longer states the lifetimes itself:
  it says a first message "after a break longer than the cache lifetime misses the cache" and links to
  the prompt-caching page for "which lifetime your requests get and the controls for setting it" —
  read that page, not a remembered number.

**The cache-read price moved, and which price you see depends on the CLI.** The platform list prices a cache read at
10 % of base input, **except 5 % on Opus 5.5 and Sonnet 5.5** (**$0.10/Mtok** for Sonnet 5.5). The 2.1.301 and 2.1.310
bundled CLIs charge exactly that (measured 2026-10-17 and 2026-10-24); the 2.1.294 bundled with 0.2.165 charged
**$0.20/Mtok** (2026-10-11). So a cost table names the CLI it ran on, and a cache-heavy total recorded on 2.1.294 or
earlier changes on a newer CLI.

**Keep the cache prefix stable.** The cache matches a request's prefix: system prompt and tools first, then the turns.
Claude Code's own lessons (Shihipar, 2026-04-30, about Claude Code on the Messages API) follow from that: put static
content first and send changes (time, changed files) as messages, not prompt edits; don't switch models or add and
remove tools mid-session ("adding or removing a tool invalidates the cache for the entire conversation"), and defer
tools through tool search instead; compact with the same prompt and tools so the summary reuses the prefix; and watch
the cache hit rate. In the SDK the prefix is `system_prompt`, `tools`/`allowed_tools`, MCP servers, `model` and loaded
settings, so changing them between turns of one session, or `set_model()` midway, breaks it (our inference). "The
prompt cache belongs to the model that wrote it" (Osmani, 2026-11-09, article #42): the first turn on a new model pays
the cache write for the whole conversation, so switch at a natural break — compact first, or start a fresh session
with a short plan — and know that a move down a tier drops the earlier model's thinking blocks (readable downward
only; the request still succeeds). Whether an effort change also breaks the cache depends on the surface: Claude Code
on an API key or subscription keeps it on the newest models, Bedrock, Agent Platform and gateways clear it, and on the
Messages API a top-level effort change invalidates it.

**Message threads cut latency, not cost.** On the Messages API a thread sends only the new messages plus the previous
response's id; billed tokens do not change and a thread expires 5 minutes after its last request. Nothing documents
the Python SDK using it, so leave it out of a cost model.

## The cheapest optimisation is not a cap at all

Measured on the build machine, same prompt, same model, same host:

| Configuration | Cache-creation tokens | Cost |
|---|---|---|
| default `setting_sources` | 21 503 | $0.0870 |
| `setting_sources=[]`, `tools=[]`, `strict_mcp_config=True` | 111 | ~$0.0050 |

**17x**, all of it ambient configuration being turned into cache-creation tokens on every run. And separately, `claude
-p` with no `--model` runs on the account's default or saved model: with an API key on Claude Code 2.1.322
(2026-11-10) that was `claude-opus-5-5` at $0.0667, **2x** an explicit Sonnet ($0.0331); on subscription auth in
2026-10-11 it was `claude-fable-5-1` at $0.3397, 4x. Pin the model and isolate the run before tuning anything else.
Price the hardest tasks in a set, which carry most of the spend (two of 20 problems carried 43 % in one of Anthropic's
runs, #42).

## Caps at a gateway, in front of the agent

`max_budget_usd` caps one query. A fleet-wide ceiling belongs in front of the agent. Anthropic's guide to Claude Code
costs on Google Cloud (2026-10-27) is about interactive Claude Code behind the Claude apps gateway, but its pattern
carries over: the gateway sets **spend caps per user, IdP group or organisation** by day, week or month (group and
organisation caps are per-developer defaults, not a shared pool), warns in the CLI past 75 % and again past 95 %, and
at the cap "returns 429 until the period resets or an admin raises the cap"; **model allowlists per IdP group** are
enforced server-side, and it argues that cost per task, not price per token, is the number to track. An SDK process
behind such a gateway sees the 429 as an API error, not the 75/95 % warnings, so handle it as a rate-limit failure
rather than a crash.

## Subscription versus API billing

| | API key | Subscription (login or `CLAUDE_CODE_OAUTH_TOKEN`) |
|---|---|---|
| What pays | the API account, per token | the plan's usage limits |
| `total_cost_usd` | an estimate of the bill | an API-equivalent estimate; not billed |
| Real ceiling | your spend | session and weekly usage limits, distinct from HTTP 429s |
| Hosted use | **required** | not permitted for third-party products without prior approval |

`init.data["apiKeySource"]` is the authoritative read-back of which credential the subprocess actually chose —
`"none"` on all three measured subscription runs. It is the cheapest signal there is for stamping a cost basis on a
result.

## Two time limits that are not budgets

A **background Bash command** has its own ceiling: with `run_in_background` the `timeout` defaults to **1800000 ms**
(30 minutes), ceiling **7200000 ms** (2 hours); foreground commands stay capped at 600000 ms.
`BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` above their defaults apply **in unattended sessions only**, and a
ceiling above two hours also raises the background limit, so setting them high lengthens how long a background command
may burn tokens.

**Retries** cost money too. `CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS` caps how long the watchdog waits on a stalled
request; `CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS` ends a request at a usage limit that resets too far
away, and `CLAUDE_CODE_RETRY_WATCHDOG_USAGE_LIMIT_RECHECK_MS` (2.1.305, `60000`–`10800000`) sets how often it checks
whether that limit lifted early; `CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS` and
`CLAUDE_CODE_OVERLOADED_RETRY_MAX_DELAY_MS` bound overload backoff (not under the watchdog), and
`CLAUDE_CODE_NONSTREAMING_TIMEOUT_RETRIES` bounds retries of a timed-out non-streaming request. Also set
`CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR` deliberately if the agent searches: the default is **100 interactive but 0
non-interactive** (**2.1.290+**), so a headless deployment gets no refills unless you ask for them.

Watch for `RateLimitEvent`. Measured, it fires on **every** run, not only near a limit, carrying `status` (`allowed`,
`allowed_warning`, `rejected`), `rate_limit_type` (`five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet`,
`overage`), `utilization` and `resets_at`, plus a `raw` dict with per-window figures. Only `rejected` means work
stopped; `allowed_warning` is information. From 2.1.312 Claude Code's own messages call the `five_hour` window the
"5-hour limit" (formerly "session limit"), so match on `rate_limit_type`, not on message text.

From **2.1.311** a standard-context session whose request runs over 200K tokens compacts and continues instead of
stopping, so a run that used to fail cheaply now keeps spending: keep `max_budget_usd`.

For the developer's own sessions on a Pro, Max, Ultra, Team or Enterprise plan, `/usage` lists **Recommendations**
(each with its share of recent usage, as in `25%  Trim ~/code/api/CLAUDE.md · 49k tokens per request`; `f` applies
them). It is an interactive view, not something an SDK agent reads, but its rows name the same ambient costs
(oversized `CLAUDE.md`, many MCP tools) that `setting_sources=[]` removes from an agent. From 2.1.311 `/usage` also
shows **large prompt-cache misses** under "What's contributing to your limits usage?" — the same misses that make an
SDK agent's `cache_creation_input_tokens` jump.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/cost-tracking> (token usage, totals, cache tokens, the 1-hour TTL
and its controls), <https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget>,
<https://code.claude.com/docs/en/agent-sdk/subagents#cap-subagent-depth-concurrency-and-spend>,
<https://code.claude.com/docs/en/agent-sdk/hosting#cost>, <https://code.claude.com/docs/en/env-vars>,
<https://code.claude.com/docs/en/agent-sdk/quickstart> (the third-party policy note),
<https://code.claude.com/docs/en/costs> (`/usage` recommendations, the fix shortcut, cache misses, `modelPricing`),
<https://code.claude.com/docs/en/costs#manage-costs-for-your-organization> (the billing pointer); `claude-agent-sdk`
0.2.182 `types.py:2420` (`max_turns`), `:2426` (`max_budget_usd`), `:1708-1747` (`ResultMessage`), `:1682`
(`ModelUsage`), `:1766` (`RateLimitInfo`; `:1760` is `RateLimitType`);
<https://platform.claude.com/docs/en/about-claude/models/overview> (the cache-read percentages),
<https://code.claude.com/docs/en/agent-sdk/python#bash> (the background-command limit),
<https://code.claude.com/docs/en/agent-sdk/agent-loop#budget-headroom>,
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.301, 2.1.305, 2.1.311 and 2.1.312 as named
above); <https://code.claude.com/docs/en/model-config> (effort order and defaults);
<https://claude.com/resources/articles/message-threads> ("Make long-running agents faster with message threads",
2026-11-02, threads as a latency lever with unchanged billing) and
<https://platform.claude.com/docs/en/build-with-claude/message-threads> (expiry, pricing and rate limits unchanged);
<https://claude.com/resources/articles/how-to-manage-costs-and-demonstrate-roi-for-claude-code-on-google-cloud>
("Manage costs and demonstrate ROI for Claude Code on Google Cloud", 2026-10-27, gateway spend caps, 75 %/95 %
warnings, 429 at the cap, model allowlists, cost per task; interactive Claude Code, not the SDK);
<https://claude.dev/blog/building-effective-agent-automations/> ("Building effective agent automations", 2026-10-08, a
per-run budget cap at 3–5× a normal run, then tightened);
<https://claude.dev/blog/lessons-from-building-claude-code-prompt-caching-is-everything/> ("Lessons from building
Claude Code: Prompt caching is everything", 2026-04-30, prefix order, no mid-session model or tool changes, cache-safe
compaction); <https://claude.dev/blog/spending-your-effort/> ("Using Claude Code: Spending your effort", 2026-09-25,
what higher effort buys); <https://claude.dev/blog/what-a-task-costs-on-opus-5-5/> ("What a task costs on Opus 5.5",
2026-09-25, cost per task, turns and cache share, effort before model; no prices copied);
<https://claude.dev/blog/building-with-claude-sonnet-5-5/> ("Building with Claude Sonnet 5.5", 2026-09-28, per-model
effort, the API effort/cache rule); <https://claude.dev/blog/which-claude-model-should-you-build-with/> ("Which Claude
model should you build with? Fable, Opus, Sonnet, or Haiku", 2026-11-09, the cache belongs to the model, switch at a
natural break, thinking blocks readable downward, price the hardest tasks; names the Agent SDK). The default-model row
was re-measured with an API key on 2026-11-10. The 17x and 4x figures, the cumulative-cost behaviour, the `max_turns=1
→ num_turns=2` result and the `RateLimitEvent` shape were measured by this plugin on 2026-09-30 on a Claude Max
subscription with no API key set; `costBasis` and the $0.20/Mtok cache-read price of the bundled CLI 2.1.294 were
measured 2026-10-11 with `ANTHROPIC_API_KEY` set, and the $0.10/Mtok of the bundled CLI 2.1.301 on 2026-10-17 and of
2.1.310 on 2026-10-24. Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
