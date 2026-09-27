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
turns), so read the terminal reason, not the count.

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
`permission_denials`); the `max_turns` measurement in `.dev/VERIFIED-FACTS.md`.
