# Changelog — `agent_sdk_evals`

The runner is versioned separately from the plugin that ships it; `VERSION` is
what a project's copy carries and what the plugin's staleness check compares.

## 0.1.0 — 2026-09-30

First release. Built against `claude-agent-sdk` 0.2.162 with bundled CLI 2.1.285.

- `run`, `list-tools`, `replay`, `version`, `whoami`. One JSON object as the last
  stdout line of each; exit codes 0/1/2/3.
- Trace (`agent-sdk-skills.trace/1`), result (`.result/1`) and aggregate
  (`.aggregate/1`) schemas, all snake_case and language-neutral.
- Eleven free graders (`regex`, `tool_used`, `tool_order`, `no_tool`,
  `trajectory`, `file_exists`, `structured_output`, `budget`, `hook_event`,
  `final_text`, `terminal`) and one judge grader (`llm`).
- In-process MCP mocks from `evals/mocks/<server>/<tool>.md`, hook-based fault
  injection with a seeded RNG, and a persona-driven simulated user.

Behaviour that came out of measuring the SDK rather than reading it:

- `setting_sources=[]` and `strict_mcp_config=True` are forced on every run.
- `StructuredOutput` is a synthetic tool name the CLI uses to deliver
  `output_format` results; tool graders skip it unless a grader names it.
- `Task` and `Agent` are the same tool under two names and match each other.
- `total_cost_usd` is a session running total, so the trace records
  `cost_delta_usd` and a case's cost is the last total, not a sum.
- `budget.max_turns` is the grader's own ceiling: a successful run reported
  `num_turns=2` under `max_turns=1`. Assert a tripped limit with `terminal`.
- `ToolResultBlock.is_error` is `null` on success, not `False`.
- A `hook_event` grader without its hook installed is NOT_EVALUATED, not FAILED:
  `include_hook_events=True` alone emits nothing.
- Only a `rejected` rate limit stops the suite; `allowed_warning` fired on every
  measured healthy run and is recorded, not acted on.
- `ResultError` is caught before `ProcessError`, which it subclasses.
- `whoami` reports `kind`, `cost_basis`, `plan`, `auth_method` and
  `api_provider` only; `claude auth status` also returns `email`, `orgId` and
  `orgName`, which are dropped before anything is printed or written.
