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
  `max_budget_usd`, an API error, an abort.

---

Sources: this plugin; SDK terms from `https://code.claude.com/docs/en/agent-sdk/python`
and `https://code.claude.com/docs/en/agent-sdk/agent-loop`.
