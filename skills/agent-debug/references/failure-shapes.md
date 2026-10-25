# Failure shapes a trace can show

Each shape is detected from the normalized trace events by
`trajectory.detect_signatures`; the name is what `analyze_trace.py` prints.

## loop

The same tool with the same arguments three or more times in a row. The agent
is not learning from the result: either the result does not say what changed
(a tool returning `ok` with no state), or the prompt gives no stopping rule.
Look at the repeated `tool_result` content first. A loop always ends by
`max_turns` or `max_budget_usd`; raising the cap makes it longer, not better.

## oscillation

A, B, A, B: two calls that each undo or contradict the other, typically a
lookup and an action whose results disagree (the catalog says one copy, the
reservation says none). The fix is usually in the tool results agreeing with
each other, then in the prompt saying which one to trust.

## stall

A result with no tool call and no final text, or a final text that says it
will do something and does not. Common causes: a permission the agent was
denied without being told (check `permission_denials` on the result event and
`PermissionRequest` hook events), an `output_format` the model could not
satisfy, or `max_turns` reached mid-thought (`terminal_reason: max_turns`).

Two stall shapes belong to **long-running** agents that work across several
sessions (Anthropic's long-running harness article, 2025-11-26):

- **Tried to do too much at once.** The agent attempts the whole job in one
  session, runs out of context mid-feature, and the next session inherits
  half-built, undocumented work. In the trace: a session ending on
  compaction or a cap with edits but no commit or test run.
- **Declared victory early.** A later session looks around, sees progress, and
  says the project is finished while features are missing or untested. In the
  trace: a confident final text after few tool calls, and no end-to-end check.

Layer: **harness**, not prompt wording. The fix is structure the next session
can read: a progress file and git history it reads first, a feature list (JSON,
each feature marked passing only after testing) from which it picks **one
feature per session**, and an end-to-end smoke test before new work. For the
design itself, `/agent-sdk:agent-design`.

## unknown_tool

A call to a name the agent does not have. In evals this is nearly always a
mock or server named differently from what the prompt mentions
(`mcp__library__reserve` versus `mcp__library__reserve_book`); in production it
is a prompt that names a tool that was removed. `list-tools` on the runner
prints the names the session actually had.

## error_cascade

Two or more consecutive tool results with `is_error` (truthy; the SDK sets
`null` on success). The agent did not change strategy after an error. The
prompt should say what to do on error, and the tool should say what went
wrong in words the model can act on.

## capped

`terminal_reason: max_turns` or `subtype: error_max_budget_usd`. Not a shape of
its own: find the loop, oscillation or stall that consumed the budget. Note
that `max_turns` is not a hard cap on `num_turns` (a cap of 1 measured two
turns), so read the terminal reason, not the count. A cap sized to the tool
calls alone is a classic `capped` run: count each turn with tool calls plus one
for the final text-only response, or the run ends `error_max_turns` with no
final response (measured again 2026-10-29).

## refusal

The result has `is_error` set on `subtype: success` with
`stop_reason: refusal`; its `terminal_reason` can read `completed` or even
`api_error`, and it is still **not an API error** (the signature reads `stop_reason`
first). Layer: prompt. Read the refusal text before blaming the agent: either
the case asks for something the model declines — then assert the refusal with a
`final_text` grader and `terminal: {allow_error: true}` — or the prompt makes
an ordinary request read as one it should decline.

## tool_deferred

The result has `is_error` set with `stop_reason: tool_deferred_unavailable`: a
`PreToolUse` hook deferred a call, and when the session resumed the tool was
gone (typically its MCP server was not connected). `deferred_tool_use` names the
call. Not an API error and not the agent's fault. Layer: eval. Resume with the
tools the deferring session had; the harness lost the tool.

## wrong_path_right_answer (Q3)

Not a signature; a verdict. The answer graders pass and a trajectory grader
fails: the agent produced the right words without doing the work, or did it in
an order the case forbids. Treat as a real failure; the fix is an ordering or
refusal rule in the system prompt.

## Flaky

Some runs pass, some fail, same case, same code. Established only by repeated
runs (`--runs 5`). Fixes are about robustness: sharper tool descriptions, an
explicit ordering rule, a `fallback_model`, `effort`. The success measure is
pass@1, never one green run.

---

Sources: this plugin's `lib/agent_sdk_skills/trajectory.py`; result fields per
`https://code.claude.com/docs/en/agent-sdk/python` (`ResultMessage`,
`permission_denials`, `is_error` and the `stop_reason`-first order),
`https://code.claude.com/docs/en/hooks` (`tool_deferred_unavailable` on resume),
re-read 2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs;
the `max_turns` measurement in `.dev/VERIFIED-FACTS.md`;
`https://code.claude.com/docs/en/agent-sdk/agent-loop` (the `max_turns` "+1"
rule); <https://www.anthropic.com/research/effective-harnesses-for-long-running-agents>
("Effective harnesses for long-running agents", 2025-11-26, the two long-run
failure modes and the progress-file / feature-list / one-feature-per-session
fix). Re-read 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312
docs.
