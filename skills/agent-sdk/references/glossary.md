# Glossary

What a word means in this plugin. Where the SDK uses the same word, the SDK's
meaning is given first.

- **Agent** — a Python program that builds `ClaudeAgentOptions` and runs a
  session with `query()` or `ClaudeSDKClient`. Not a `.claude/agents/*.md`
  file; those are Claude Code subagents.
- **Entry point** — the function the runner calls to obtain options:
  `agent:build_options` by convention, or any `module:function`.
- **Case** — one directory under `evals/` with a `prompt.md` (frontmatter and
  the first user prompt) and `graders/`. A case is a specification of one
  behaviour; it is never edited to make a run pass.
- **Category** — `happy`, `edge`, `adversarial`, `memory`, `regression`; the
  coverage matrix counts cases per category and per tool.
- **Grader** — one file under `graders/`, one assertion. Free graders are
  deterministic (`regex`, `tool_used`, `tool_order`, `file_exists`,
  `trajectory`, `structured_output`, `budget`, `hook_event`, `final_text`,
  `no_tool`, `terminal`); the `llm` grader asks a judge.
- **Tier** — a named grader set with runs and a threshold in `eval_config.json`
  (`pr`: free graders, one run; `nightly`: judges, repeated runs). Also the
  cost tier of an option: `free`, `run`, `judge`.
- **Run** — one execution of one case: one SDK session, one trace, one result.
- **Trace** — `*.trace.jsonl`, the normalized event stream of a run (init,
  user, assistant text, tool use, tool result, hook, rate limit, result).
  A Claude Code session file can be imported into the same shape.
- **Result** — `<case>.result.json`: per-run grader verdicts, the SDK's result
  fields, cost basis. `aggregate.json` totals a whole run of the suite.
- **Status** — `PASSED`, `FAILED`, `NOT_EVALUATED` (a grader could not run:
  judge unreachable, usage limit, imported session without cost),
  `INFORMATIONAL` (a budget grader marked `informational`).
- **Trajectory** — the ordered list of tool calls in a run. `EXACT` forbids
  extras, `IN_ORDER` allows extras between expected calls, `ANY_ORDER` ignores
  order; a refusal case needs `EXACT` or `no_tool` to fail on a forbidden call.
- **Golden trace** — a run whose trajectory was reviewed and turned into a
  `trajectory` grader; it pins the behaviour the author accepted.
- **First divergence** — the earliest point where a failing run's trajectory
  departs from the expected one; everything after it is usually a consequence.
- **Quadrant** — right trajectory / right answer, right / wrong, wrong / right,
  wrong / wrong. The third one (wrong path, right answer) is the one that
  hides until a tool changes.
- **pass@k** — the probability at least one of `k` runs passes; **pass^k** the
  probability all `k` pass. Reliability is measured from repeated runs, never
  from one.
- **Judge** — an `llm` grader's model call, made through the SDK with the
  configured judge model, `samples` votes, majority verdict.
- **Cost basis** — what a run is paid with: `api_key`, `subscription`
  (login or OAuth token), `provider`. On a subscription, USD figures are
  estimates and the binding limit is plan usage.
- **Usage limit** vs **rate limit** — a plan quota that resets on a schedule
  vs an HTTP 429 from the API. Both become `NOT_EVALUATED`, never `FAILED`.
- **Runner copy** — the `agent_sdk_evals` package this plugin copies into
  `evals/runner/`, stamped with `VERSION` and `MANIFEST.sha256`.
- **Mock** — an in-process MCP server the runner builds from
  `evals/mocks/<server>/<tool>.md` to stand in for a real one.
- **Persona** — a simulated user: behaviour instructions plus violation
  rubrics that judge the simulator, not the agent.
- **Fault** — an error, latency or altered input a hook injects into a tool
  call with a per-tool probability.
- **Hook** — an async callback the SDK runs at a lifecycle point
  (`PreToolUse`, `PostToolUse`, `Stop`, ...), returning a dict whose
  `hookSpecificOutput` names the event.
- **`setting_sources`** — which of Claude Code's settings tiers the SDK loads
  (`user`, `project`, `local`). Omitted, all three load, like the CLI; `[]`
  runs isolated, which is what evals and CI want.
- **Structured output** — a JSON-schema `output_format` the SDK enforces on
  the final answer; it lands on `ResultMessage.structured_output`.
- **Terminal reason** — why a run ended: completed, `max_turns`,
  `max_budget_usd`, an API error, an abort. A deferred tool gives the result a
  `stop_reason` of `tool_deferred`, which is a stopped turn rather than a
  refusal.
- **Stop reason** — read it before `is_error`. On `subtype: success`,
  `is_error` is `True` for a refusal (`stop_reason: refusal`), a deferred tool
  gone on resume (`tool_deferred_unavailable`) and an error reported in place of
  a model response (any other value); only the last is an API error.
- **Fork (subagent)** — a subagent that copies the conversation so far
  (`subagent_type: "fork"`), on by default from Claude Code 2.1.302 with nothing
  configured; deny it with `Agent(fork)`, turn it off with
  `CLAUDE_CODE_FORK_SUBAGENT=0`. Not the same as `fork_session()`.
- **Cost basis** — which price list a cost figure came from: `list`, `managed`
  (an organisation's negotiated rate) or `unknown`, reported per model in
  `ResultMessage.model_usage[*].costBasis` (Claude Code 2.1.246+, read it with
  `.get()`). Two figures with different bases are not comparable.
- **Soft cap** — `max_budget_usd` and `--max-cost-usd`. They compare against a
  running client-side estimate, which can pass the value before the run stops,
  so they need headroom rather than exactness.
- **`fork_session()`** — the module-level function that copies a transcript into
  a new session (optionally up to one message). Distinct from the
  `fork_session: bool` option, which forks on resume; a fork keeps no file
  checkpoints from before it.
- **Mod** — a TypeScript plugin class Claude Code gained in 2.1.292, whose
  `tool.check` handler answers after the permission rules and hooks. Out of
  scope for these skills except as the seventh step of the permission model.
- **Unset permission mode** — not the same as `"default"`. The CLI resolves it,
  and on CLI 2.1.285–2.1.301 a headless session that fetches no feature flags
  lands in `auto`, where broad allow rules are dropped; 2.1.302 starts it in
  `default` (`OPT013`).

---

Sources: this plugin; SDK terms from `https://code.claude.com/docs/en/agent-sdk/python`
(`fork_session`, `costBasis`, `ResultMessage.is_error`),
`https://code.claude.com/docs/en/agent-sdk/subagents` (forked subagents) and `https://code.claude.com/docs/en/agent-sdk/agent-loop`
(the budget headroom note); `https://code.claude.com/docs/en/permission-modes`
and `https://code.claude.com/docs/en/permissions` (the unset mode, mods). Re-read
2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs.
The 2.1.302 unset-mode rule is stated at
<https://code.claude.com/docs/en/permission-modes#which-mode-a-non-interactive-run-starts-in>
(and in the CHANGELOG); re-read 2026-10-24 against claude-agent-sdk 0.2.174 /
Claude Code 2.1.310 docs.
