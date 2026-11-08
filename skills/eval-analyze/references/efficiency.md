# Efficiency: turns, tokens, cost, and what they are not

Efficiency numbers describe how expensive a run was, not how good. They are
reported in their own table, lower is better, and none of them passes or
fails a case unless a `budget` grader says so.

## The columns

| Column | Source | Notes |
|---|---|---|
| turns | `result.num_turns` | a `max_turns` option is not a hard cap; assert on `terminal_reason` instead |
| input / output tokens | `result.usage.input_tokens`, `output_tokens` | main loop only; subagent tokens are in `model_usage` |
| cache read | `result.usage.cache_read_input_tokens` | high cache reads with low input tokens is the healthy shape |
| cost USD | `result.total_cost_usd` | a session running total; per-turn deltas are in the trace |
| duration | `result.duration_ms` | wall clock, noisy |

## Cache-read share

One number summarises how well a run reused its prompt cache:

```
cache-read share = cache_read_input_tokens
                   / (input_tokens + cache_creation_input_tokens + cache_read_input_tokens)
```

all four from `runs[].result.usage` in `<case>.result.json`. The report does
not print it; compute it per run from those fields. *Lessons from building
Claude Code: Prompt caching is everything* (2026-04-30, article #32) explains
why it matters: the cache matches a **prefix** (system prompt and tools first,
then the conversation), Claude Code watches its hit rate like uptime, and
anything that changes the prefix mid-session — a different tool set, a model
switch, a timestamp in the prompt — makes every later turn pay full price.

- Compare the share **across runs of the same case**, not across cases: a
  one-turn case has little to reuse.
- A drop after a change to `system_prompt`, `allowed_tools`, MCP servers or
  `model` is the signal to look for; the article explains the mechanism, and
  the link to these options is our reading.
- The `claude_code` preset embeds the auto-memory location, so sessions with
  different working directories can share less (the docs'
  `exclude_dynamic_sections` note).
- A `budget` grader's `max_cache_read_tokens` caps the absolute count; the
  share is a reading aid, not a grader.

## Reading cost honestly

- **Basis.** `api_key` means an estimate of the bill; `subscription` means an
  API-equivalent estimate and the real limit is plan quota; `provider` means
  that cloud's price table. The table footer says which.
- **Running total.** `total_cost_usd` accumulates across turns of one session.
  A two-turn case's cost is the last value; the trace records `cost_delta_usd`
  per turn.
- **Models you did not ask for.** `model_usage` lists every model the CLI
  used, including its own Haiku calls for internal work. The model that
  answered is on each `assistant_text` event.
- **Isolation.** A run without `setting_sources=[]` carries the developer's
  settings and `CLAUDE.md` in every prompt; the measured difference was
  seventeen-fold. The trace's `init` event records what was applied.

## When a number should become a grader

Add a `budget` grader when a ceiling is a requirement: a support agent that
must answer within N turns, a batch job with a per-item cost. Mark it
`informational: true` while establishing the baseline, then set the ceiling
from the observed mean plus headroom. Compare runs of the same case, same
model, same isolation; anything else compares two different experiments.

To pick a model or an effort level, follow the recipe in Anthropic's model-choice
guide (2026-11-09, article #42; it names the Agent SDK): run each candidate at two or
three effort levels, each in its own session so runs share no cache, record the cost of
each completed task from `usage`, plot score against spend, keep a multi-model setup
only if it beats every single-model point, and shadow-run the winner on real traffic
before cutting over. The `cost_usd` and status columns here are that chart's two axes.

---

Sources: <https://claude.dev/blog/which-claude-model-should-you-build-with/> ("Which Claude model
should you build with? Fable, Opus, Sonnet, or Haiku", 2026-11-09, score against spend per model and
effort, shadow runs); `https://code.claude.com/docs/en/agent-sdk/cost-tracking` (`usage`,
`model_usage`, running totals), measurements in `.dev/VERIFIED-FACTS.md`; this
plugin's `lib/agent_sdk_skills/results.py` (`efficiency_rows`);
<https://claude.dev/blog/lessons-from-building-claude-code-prompt-caching-is-everything/>
("Lessons from building Claude Code: Prompt caching is everything", 2026-04-30,
prefix matching, no mid-session tool or model changes, hit rate monitored like
uptime; Claude Code and Messages API practice, the cache-read share is our
metric); `https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts`
(read 2026-11-08, the auto-memory location in the preset). Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
