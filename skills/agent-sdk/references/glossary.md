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
  `hookSpecificOutput` names the event. A **guard** is a hook that denies, asks
  or blocks; an **observer** only logs or adds context.
- **Fail open / fail closed (hooks)** — what happens when a hook callback
  raises, returns `None` or returns a value the CLI rejects. By default it
  **fails open**: the failure counts as no decision and the call goes ahead,
  with an informational `hook_callback_failed` system message. `on_failure="block"`
  on the `HookMatcher` (claude-agent-sdk 0.2.177+, Claude Code 2.1.317+) makes
  it **fail closed**: the action is refused (`HOK011`). Settings-file hooks have
  the same switch as `"onFailure": "block"`.
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
- **Context engineering** — choosing which tokens reach the model each turn
  (prompt, tools, retrieved data, history), treating the window as a finite
  budget: compaction, notes kept outside the window, data loaded on demand.
  `/agent-sdk:agent-design` reviews it.
- **Progressive disclosure** — showing the model a short description first and
  the full content only when it is needed: a skill's name and description up
  front, its body on use; tool search loading tool definitions on demand.
- **Fold (subagents)** — merging a subagent back into the main loop as skills
  and tools, one at a time, keeping it a subagent only when the folded version
  scores worse on the evals.
- **Harness** (design sense) — everything around the model that runs the loop:
  options, tools, hooks, permissions, compaction, the files a long run reads
  and writes between sessions. In this plugin's file names it also means the
  wiring `/agent-sdk:agent-harness` checks.
- **Message thread** — a Messages API (Claude Platform) beta: the first request
  starts a thread with the whole conversation, later ones send only the new
  messages plus the previous response's id; a thread expires 5 minutes after its
  last request. Same billed tokens, lower time to first token. A platform fact:
  nothing documents the Agent SDK using or exposing it.
- **Tool Search Tool** — the API tool that lets Claude load deferred tool
  definitions on demand. In the Agent SDK, tool search is on by default and
  defers MCP schemas itself (`ENABLE_TOOL_SEARCH`); a `ToolSearch` call in a
  trace is that mechanism, and the runner treats it as synthetic.
- **Mirrored lean (deferral)** — two simulated users on the same task stating
  opposite leans; if the agent's recommendation flips with the lean both times,
  it defers rather than judges. `/agent-sdk:eval-simulation` builds the pair
  (`gen_persona.py --lean`).
- **Agentic AI Foundation (AAIF)** — the Linux Foundation body that, since
  2026-10-22, governs the base Agent Skills open standard (and MCP). The
  `SKILL.md` folder format is unchanged; Claude Code's own skill extensions are
  not part of the donated spec.
- **Hillclimbing** — improving an agent against an eval by repeated small edits,
  each kept or reverted on the score. It needs one attributable surface per
  change and a held-out set, or it overfits (`/agent-sdk:eval-analyze`).
- **Held-out (test) set** — cases the person or agent tuning never reads; a
  change is kept only when it improves these as well as the cases it tuned on.
  The runner has no split field: it is a convention of which cases you read.
- **Destination-confirmed completion** — counting an action (a post, a write
  to another system) as done only when the destination confirms it, and moving
  bookmarks or ledgers only after that, so a re-run of a scheduled agent is
  idempotent (`/agent-sdk:agent-design`, `long-running-harness.md`).
- **Memory note** — a file an agent writes for a later session, as a prediction of
  what that session will need; not a transcript, not compaction, not in-context
  learning (`/agent-sdk:agent-design`, `memory-design.md`).
- **Consolidation ("dreaming")** — an offline pass between sessions that corrects
  notes against transcripts, builds linked representations, promotes notes to the
  top file, focuses memory on a goal and fills gaps one session left.
- **Salience** — whether something is worth remembering: keep what the environment
  will not tell you again (plans, tested rules, decisions), skip what can be re-read.
- **Prompt-cache prefix** — the fixed start of each request (system prompt, tools,
  then earlier turns) that the cache matches; changing it mid-session makes every
  later turn pay full input price (`agent-deploy/references/cost-controls.md`).
- **Effort** — `ClaudeAgentOptions.effort` (`low` … `max`): how much the model spends
  on verification and edge cases; the SDK side of Claude Code's `/effort`. Hold it
  fixed across compared eval runs.

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
Claude Code 2.1.310 docs. The four design terms follow
<https://www.anthropic.com/research/effective-context-engineering-for-ai-agents>
("Effective context engineering for AI agents", 2025-09-29, context engineering),
<https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills>
("Equipping agents with Agent Skills", 2025-10-16, progressive disclosure),
<https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop>
("Building agents: When to fold subagents into your main agent loop",
2026-10-22, folding) and
<https://www.anthropic.com/research/effective-harnesses-for-long-running-agents>
("Effective harnesses for long-running agents", 2025-11-26, the harness).
The four 2026-11-02 terms follow
<https://claude.com/resources/articles/message-threads> ("Make long-running
agents faster with message threads", 2026-11-02, message threads) and
`https://platform.claude.com/docs/en/build-with-claude/message-threads` (expiry,
beta status);
<https://www.anthropic.com/research/advanced-tool-use> ("Introducing advanced
tool use for Claude", 2025-11-24, the Tool Search Tool) and
`https://code.claude.com/docs/en/agent-sdk/tool-search` (on by default);
<https://www.anthropic.com/research/agents-judgment-calls> ("How AI agents shape
experts' judgment calls", 2026-10-27, deferral measured by randomising the lean;
the mirrored pair is this plugin's adaptation);
<https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation>
("Donating Agent Skills to the Agentic AI Foundation", 2026-10-22, the AAIF)
and `https://code.claude.com/docs/en/skills` (Claude Code's extensions).
Fail open / fail closed per
`https://code.claude.com/docs/en/agent-sdk/hooks#block-the-action-when-a-callback-fails`
and `https://code.claude.com/docs/en/hooks` (`onFailure`).
The three 2026-11-05 terms follow
<https://claude.dev/blog/automating-eval-design-and-hillclimbing/> ("Automating eval design
and hillclimbing with Claude", 2026-09-28, hillclimbing and the held-out test set) and
<https://claude.dev/blog/building-effective-agent-automations/> ("Building effective agent
automations", 2026-10-08, destination-confirmed completion).
The five 2026-11-08 terms follow
<https://www.anthropic.com/research/components-of-agent-memory> ("The components of agent
memory", 2026-11-06, memory note, consolidation, salience; Managed Agents experiments),
<https://claude.dev/blog/lessons-from-building-claude-code-prompt-caching-is-everything/>
("Lessons from building Claude Code: Prompt caching is everything", 2026-04-30, the cache prefix)
and <https://claude.dev/blog/spending-your-effort/> ("Using Claude Code: Spending your effort",
2026-09-25, effort); `effort` per `https://code.claude.com/docs/en/agent-sdk/python`.
Re-read 2026-11-08 against claude-agent-sdk 0.2.179 / Claude Code 2.1.319 docs.
