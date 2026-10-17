# Changelog — `agent_sdk_evals`

The runner is versioned separately from the plugin that ships it; `VERSION` is
what a project's copy carries and what the plugin's staleness check compares.

## 0.1.3 — 2026-10-17

Re-checked against `claude-agent-sdk` 0.2.168 with its bundled CLI 2.1.301
(docs and changelog read at Claude Code 2.1.302); minimum supported SDK stays
0.2.140. The 49 options, 6 permission modes, 10 Python hook events, 5 effort
levels and the 19 `ResultMessage` fields are unchanged and re-verified against
the installed wheel.

- **`HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT` is `("PreCompact",)`.** SDK 0.2.166
  types 21 `*HookSpecificOutput` classes; of the 10 Python events only
  `PreCompact` has none. A `Stop` or `SubagentStop` hook may now return
  `hookSpecificOutput.additionalContext`; blocking a stop is still the
  top-level `decision: "block"`. The CLI reads that dict shape on older SDKs
  too, so the constant is not version-gated.
- **The `init` event records `capabilities`, `fast_mode_state` and
  `fast_mode_disabled_reason` when the CLI sends them** (11 capability strings
  and `off`/`sdk_opt_in_required` measured on 2.1.301). They are read with
  `.get()`, never required, and nothing grades on them. The capture tolerates
  the `system`/`commands_changed` message 2.1.301 sends right after `init`
  (a plain `system` event), the undeclared `init` keys (`original_cwd`,
  `additional_directories`, `memory_paths`, `messaging_socket_path`,
  `per_turn_effort_active`, `view_mode`, `analytics_disabled`,
  `product_feedback_disabled`) and `plugins[]` entries that carry `source`
  instead of `version`.
- **The permission-default rationale is version-ranged.** With
  `permission_mode` unset the CLI picks the mode: a headless session that
  fetches feature flags starts in `default` (measured on CLI 2.1.292 and
  2.1.301, direct API key, telemetry on); on CLI 2.1.285–2.1.301 one that does
  not (third-party provider, telemetry off, first run after an install or
  upgrade) starts in `auto`; 2.1.302+ starts those in `default` too. The runner
  still forces `dontAsk` when the agent leaves the mode unset, and
  `permission_mode_source` keeps its two values.
- **`sandbox` literals accept the released shapes.** `ignoreViolations` is
  `dict[str, list[str]]` (command-pattern substring, `"*"` for all, mapped to
  violation-text substrings; reporting only), and the forwarded-but-undeclared
  `failIfUnavailable` and `filesystem` (`denyWrite`, ...) keys are accepted
  (plugin library `options_ast.sandbox_problems`).
- Cost note: the bundled CLI 2.1.301 estimates Sonnet 5.5 cache reads at the
  list $0.10/Mtok (measured); CLI 2.1.294 used $0.20 (2026-10-11, history).

## 0.1.2 — 2026-10-11

The runner's behaviour changed, so a project copy at 0.1.1 is reported as older
(`DEP001`) and offered the upgrade.

- **`--dry-run` counts sessions, not cases.** `runs` is resolved
  narrowest-first — `--runs`, then the case's own `runs:`, then the tier's, then
  1 — and a case pinning its own repetition outranks the tier, which is the
  design. The dry run now says so: the JSON carries `sessions_total` (the sum of
  the per-case runs; one session per run, since a `turns:` or `simulated_user`
  case replays inside the one session) and per-case `runs`, `sessions` and
  `runs_source` (`"cli"` | `"case"` | `"tier"` | `"default"`), and the prose
  prints `sessions: 11 (3 cases pin runs: 3)`. The plugin's `run_evals.py
  --dry-run` reports the same total. Before this, the worked example's `pr` tier
  read as 5 sessions and started 11.

## 0.1.1 — 2026-10-11

Re-checked against `claude-agent-sdk` 0.2.165 with its bundled CLI 2.1.294;
minimum supported SDK stays 0.2.140. `types.py` is byte-identical to 0.2.162, so
the 49 options, the 6 permission modes, the 10 Python hook events, the 5 effort
levels and the `ResultMessage` fields are unchanged and re-verified against the
installed wheel rather than against the test stub.

- **`permission_mode` is resolved by the runner.** An agent whose
  `build_options()` leaves it `None` now gets `permission_mode="dontAsk"`, and
  the trace `init` event records who decided: `permission_mode_source: "agent"`
  (the agent's options or a case's `overrides` set a mode) or `"runner-default"`.
  `--dry-run` prints both. An unset mode is not `default`: from CLI 2.1.285 a
  headless session without the interactive feature flags can start in `auto`,
  where a classifier reviews each tool call and a bare allow rule no longer
  settles it, so a run's permission rules were not knowable before.
- **The `result` event says what was billed, and on what basis.**
  `models_billed` lists every model in `model_usage` and `cost_basis_list` is
  true when none reported a negotiated rate. Measured 2026-10-11: CLI 2.1.294
  bills its own background work to `claude-haiku-5-5` unasked, so the agent's
  model is not the whole cost. `costBasis` and `thinkingTokens` are on the wire
  but not on the 0.2.165 `ModelUsage` TypedDict, so both are read with `.get()`.
  The `budget` grader's help now says `max_budget_usd` is a soft cap: the
  estimate can finish over it, and only the next request is refused.
- **An imported session reports its own cost.** A session JSONL with a
  `cost-state` line (what `entrypoint: "sdk-py"` sessions write) becomes a
  synthesised `result` event carrying `total_cost_usd`, `duration_ms` and
  `model_usage`, marked `imported_cost: true`. `budget` graders can now be
  decided on imported evidence; `terminal` and `structured_output` abstain on
  one, because a cost line has no subtype, `terminal_reason` or `num_turns`.
  A `claude -p` session writes no such line and still yields no result event.
- Model policy copies added beside the option tuples: `CURRENT_MODELS` (Sonnet 5.5,
  Opus 5.5, Fable 5.1 and **Haiku 5.5**), `DEPRECATED_MODELS`
  (`claude-sonnet-4-5-20250929` retires 2026-11-30), `RETIRING_MODELS` and
  `RETIRED_MODELS`. The default model and judge model are unchanged.

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
