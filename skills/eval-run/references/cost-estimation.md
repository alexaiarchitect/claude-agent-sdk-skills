# Estimating what a run spends, before starting it

## The arithmetic

```
sessions     = cases × runs                       (+ subagent turns inside a session)
judge calls  = Σ over cases of (llm graders × samples) × runs
```

Twelve cases, three runs, two `llm` graders at three samples: 36 sessions and
216 judge calls. Say both numbers before the user chooses. The `pr` tier in a
generated config has no `llm` graders, so a per-change gate never pays a judge.

## What a session costs

The measured baseline on this plugin's fixture agent (Sonnet 5.5, one short
prompt, one tool call) was a few cents API-equivalent with isolation on, and
seventeen times that with isolation off, because the developer's user settings,
`CLAUDE.md` files and ambient MCP servers were loaded into the prompt. The
runner forces `setting_sources=[]` and `strict_mcp_config=True` for that
reason; a case that turns them off should say why.

The CLI's default model on this account is a Fable model and measured four
times Sonnet's cost for the same prompt. The runner refuses to start without an
explicit model.

## Subscription versus API key

| Credential | What is spent | What `total_cost_usd` means |
|---|---|---|
| `ANTHROPIC_API_KEY` | money, per token | an estimate of the bill from a bundled price table |
| stored login or `CLAUDE_CODE_OAUTH_TOKEN` | the plan's session and weekly usage limits | an API-equivalent estimate; the binding limit is quota |
| provider switch | that cloud's account | that provider's price table |

On a subscription the runner records `RateLimitEvent`s: `allowed` and
`allowed_warning` are informational (the measured runs all carried
`allowed_warning` at 83% of the weekly window); only `rejected` stops the
suite. The aggregate's `rate_limit.windows` shows the five-hour and seven-day
utilization, which is the right "how close am I" figure.

## Ceilings

- `max_budget_usd` on the options: the SDK ends a session that crosses it with
  `subtype: error_max_budget_usd`; the runner records it, and a `terminal`
  grader can assert on it. It is a **soft** cap — the running estimate can pass
  the value before the session stops, so leave headroom.
- `--max-cost-usd` on the run: the runner stops launching further runs and
  exits 3 with partial results. Soft in the same way, one level up.
- `budget.max_cost_usd_total` in the config: the default for `--max-cost-usd`.

## Reading the cost afterwards

`total_cost_usd` is a session running total, so a multi-turn case's cost is the
last value, not a sum of turns; the trace records `cost_delta_usd` per turn.
`model_usage` also lists models the agent never asked for: measured 2026-10-11
on SDK 0.2.165 with bundled CLI 2.1.294, the extra row was **`claude-haiku-5-5`**
(1192 in / 26 out, $0.0001322 — exactly $0.10 and $0.50 per Mtok), where the
2026-09-30 runs on CLI 2.1.285 had shown Haiku 4.5. Read it per model, never as
the first entry; the model that answered is `assistant_text.model`. Each row
also carries `costBasis` (`list` | `managed` | `unknown`, Claude Code 2.1.246+)
and `thinkingTokens`, neither of them on the 0.2.165 `ModelUsage` TypedDict, so
read both with `.get()` and record the basis beside any figure you compare
between accounts.

One price to date rather than quote: a Sonnet 5.5 **cache read** is $0.10/Mtok
on the platform price list and in Claude Code **2.1.296**, but the CLI bundled
with `claude-agent-sdk` 0.2.165 is **2.1.294**, whose estimate still charges
**$0.20/Mtok** (measured 2026-10-11). A cache-heavy estimate therefore halves
when the bundled CLI crosses 2.1.296.

---

Sources: `https://code.claude.com/docs/en/agent-sdk/cost-tracking` (estimates,
running totals, `max_budget_usd`), `https://code.claude.com/docs/en/agent-sdk/configuration`
(`setting_sources`, model default),
`https://code.claude.com/docs/en/agent-sdk/agent-loop#budget-headroom`,
`https://platform.claude.com/docs/en/about-claude/models/overview` (cache-read
percentages); measurements in `.dev/VERIFIED-FACTS.md`. Re-read 2026-10-11
against claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs.
