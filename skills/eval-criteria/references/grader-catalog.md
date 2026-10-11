# The twelve grader types

Eleven are free — they read the trace, the result or the files and cost
nothing. One, `llm`, costs a judge call per sample. Run
`scripts/grader_info.py` for the live catalog; this page is the argument behind
it.

| type | tier | required | reads |
|---|---|---|---|
| `llm` | judge | `criteria` (the body) | `last_message`, `trace`, a file |
| `regex` | free | `pattern` | `last_message`, `trace`, `files`, `mock_calls` |
| `tool_used` | free | `tool` | trace, `mock_calls` |
| `tool_order` | free | `before`, `after` | trace |
| `file_exists` | free | `path` (glob) | the run's working directory |
| `trajectory` | free | `expected` | trace |
| `structured_output` | free | `schema` or `schema_file` | `result.structured_output` |
| `budget` | free | one ceiling | result |
| `hook_event` | free | `event` | trace hook events |
| `final_text` | free | `reference` | `last_message` |
| `no_tool` | free | `tools` | trace |
| `terminal` | free | `subtype` or `terminal_reason` | result |

## Choosing

* **Did it call the right thing?** `tool_used` for presence, `tool_order` for a
  pair, `trajectory` for a sequence.
* **Did it hold back?** `no_tool`, or `trajectory` under `EXACT`, or
  `tool_used` with `max: 0`.
* **Did it end properly?** `terminal`. `budget` for how much it cost getting
  there.
* **Did it produce the right artifact?** `file_exists` plus a `regex` with
  `target: files`, or `structured_output` when the agent has an
  `output_format`.
* **Did it say the right thing?** `regex` for a literal, `final_text` for a
  reference, `llm` when the answer is a judgement rather than a string.

Prefer the cheapest grader that can fail for the right reason. A judge call to
check that a number appears in the reply is a judge call wasted, and its
verdict is less stable than the regex would have been.

When an `llm` grader really is the right answer, the cheap judge as of
2026-10-11 is **`claude-haiku-5-5`** ($0.10 / $0.50 per Mtok, 1M context by
default, needs Claude Code 2.1.293+). Name it on the grader; the suite default
stays `claude-sonnet-5-5` so verdicts remain comparable. Its price rises per
token above a 100K-token prompt, so a judge that reads a whole transcript saves
less than the headline suggests.

## Semantics that were measured, not designed

These are the ones that surprise people, and each cost a debugging session to
find:

* **`budget.max_turns` is not the option.** `max_turns=1` was measured
  producing `num_turns=2`. The grader compares `result.num_turns` against its
  own ceiling. To assert a limit actually *tripped*, use `terminal` with
  `subtype: error_max_turns` or `terminal_reason: max_turns`.
* **`budget` token ceilings map to measured `usage` keys.** `max_input_tokens`
  → `usage.input_tokens`, `max_output_tokens` → `usage.output_tokens`. Cache is
  `cache_read_input_tokens` and `cache_creation_input_tokens`;
  `usage.cache_creation` is a nested dict of TTL buckets, never a number.
* **`budget.max_cost_usd` reads the case total**, the last `total_cost_usd` of
  the session — not a sum of per-turn deltas, because the SDK's figure is a
  running total.
* **Synthetic tools are skipped.** `StructuredOutput` (how `output_format` is
  delivered) and `ToolSearch` (deferred MCP tool loading) appear in the trace
  as tool calls. `tool_used`, `tool_order`, `trajectory` and `no_tool` skip
  them unless a grader names one explicitly. Without that rule every
  structured-output case sees a phantom call and every `no_tool` fails.
* **`Task` and `Agent` are the same tool.** The CLI reports `Task`, the docs
  and SDK say `Agent`. A grader naming either matches both.
* **A bare tool name matches `mcp__<server>__<name>` by suffix**, but the
  validator will tell you to write the qualified form — it is what the model
  sees and what the trace records.
* **`ToolResultBlock.is_error` is `null` on success**, not `False`. Anything
  reading it tests truthiness.
* **`hook_event` needs an installed hook.** `include_hook_events=True` alone
  emits nothing; if the runner's capture hook is not registered for the event
  the grader names, the grader is `NOT_EVALUATED`, not `FAILED`.
* **`hook_event.event` is one of ten literals**: `PreToolUse`, `PostToolUse`,
  `PostToolUseFailure`, `UserPromptSubmit`, `Stop`, `SubagentStop`,
  `PreCompact`, `Notification`, `SubagentStart`, `PermissionRequest`.
  `SessionStart` and `SessionEnd` are not valid.
* **Result-shaped graders cannot score every imported session.** `budget`,
  `terminal` and `structured_output` read the `result` event. A session from
  `claude -p` has none, so they report `NOT_EVALUATED`. An SDK-produced session
  JSONL does carry a `cost-state` line, from which the importer synthesises a
  `result` event marked `imported_cost: true` — so `budget` can score those,
  and the flag is how a reader tells a cost the SDK reported from one the runner
  measured in-process.
* **A deferred tool ends the turn with `stop_reason: "tool_deferred"`.** A
  `PreToolUse` hook returning `permissionDecision: "defer"` is not a quieter
  deny: it stops the turn, and `deferred_tool_use` on the result names the call.
  Assert it with `terminal` on `stop_reason: tool_deferred`, not with a text
  match on the reply.
* **A cost figure has a basis.** Each `model_usage` row carries `costBasis`
  (`list` | `managed` | `unknown`, Claude Code 2.1.246+) and `thinkingTokens`,
  neither of them on the 0.2.165 `ModelUsage` TypedDict — read both with
  `.get()`. Comparing a `list`-basis run with a `managed`-basis one compares two
  price lists.

## There is no `session_state` grader

It was considered and dropped. Nothing in the 49 options or the seven message
types carries agent state, so there is nothing to read. Assert state through
its effects instead: `file_exists`, `structured_output`, or `mock_calls`.

## What every grader file owes the reader

Frontmatter is the check; the **body is the argument**. Two paragraphs: what
this proves, and what it does not. The second is the one that matters — it is
what tells the next person which other grader has to exist beside this one, and
it is why `grader_info.py` prints a "does not prove" column at all.

Sources: `lib/agent_sdk_skills/graders.py` (`GRADER_CATALOG`, `catalog_rows`,
`semantics_lines`, `validate_grader`); `.dev/CONTRACTS.md` §2 and §2.1 (the
normative table and every measured semantic) and §12.1/§12.7 (`ToolSearch` as
synthetic, the accepted grader extras);
https://code.claude.com/docs/en/agent-sdk/python (`ResultMessage`,
`ToolResultBlock`, `HookEvent`, `costBasis`),
https://code.claude.com/docs/en/agent-sdk/hooks (`defer` and
`stop_reason: "tool_deferred"`),
https://platform.claude.com/docs/en/about-claude/models/overview (Haiku 5.5's
price). `costBasis: "list"` was measured by this plugin on 2026-10-11 against
SDK 0.2.165 with bundled CLI 2.1.294. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs.
