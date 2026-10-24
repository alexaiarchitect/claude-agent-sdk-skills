# Test fixtures

**Original work.** Every fixture here was written for this plugin. The domain —
a small library's book reservations — was invented for it, and so were the
catalog, the three tools, the system prompt's rules and every case, grader,
mock, persona and fault. Nothing is copied from the Claude Agent SDK, the
cookbooks, `claude plugin eval`'s own tests, or any other project. Some files
are *derived* from measurements taken on this machine, and one session file is
written by hand in the transcript shape the SDK's own (MIT) tests use; the
provenance paragraphs at the bottom say exactly how, and what they carry is the
SDK's output shape, not anyone's content.

The domain is deliberately small and deterministic:

- three tools — `lookup_book`, `reserve_book`, `cancel_reservation`, reached by
  the model as `mcp__library__<tool>`;
- three titles — *Dune* (2 copies, free), *Emma* (1 copy, held by `member-7`),
  *Ulysses* (0 copies);
- four rules — look up before reserving, one copy per member per title, cancel
  only when the holder asks, and answer in one short paragraph.

That is enough to produce a genuine happy path, a genuine refusal, a genuine
adversarial request (cancel someone else's copy) and a genuine regression
(an unknown title), without any fixture needing a network, a clock or a model.

## What is here

| Path | What it is for |
|---|---|
| `agents/good/` | The convention this plugin scaffolds: `agent.py:build_options()`, an in-process MCP server, `.env.example`. Its `evals/` is the worked example — five cases, one per category, and it must validate with **zero** findings. |
| `agents/good/evals/eval_config.json` | The CONTRACTS §3 document, with `agent: agent:build_options` and the isolation defaults. |
| `agents/good/evals/<case>/` | `reserve-available` (happy), `refuse-double-booking` (edge), `no-cancel-unasked` (adversarial), `two-turn-memory` (memory), `unknown-title` (regression). Every grader file carries prose saying what it proves **and what it does not**. |
| `agents/good/evals/mocks/library/` | The three tools as canned mocks, one file per tool. Only `reserve-available` and `two-turn-memory` set `mocks: [library]`; both ask for *Dune*, which the canned `lookup_book` body answers correctly. `refuse-double-booking`, `no-cancel-unasked` and `unknown-title` deliberately do **not**, because they turn on catalog state the mock contradicts (Emma held by `member-7`, *The Blue Notebook* absent) and a canned mock has no per-input branching — `mocks.MOCK_KEYS` is `name, description, schema, expect, error, latency_ms, type`, so nothing can answer per title and a fixture must not invent a key the runner lacks. Those three hit `agent.py`'s `CATALOG`, which is deterministic in-process data anyway. |
| `agents/good/evals/personas/impatient.json` | The persona for simulated-user runs, with its violation rubrics. |
| `agents/drift/`, `agents/no_evals/` | One defect per review rule; an agent with no evals. Not this lane's. |
| `agents/inline_main/`, `agents/entry_env/`, `agents/external_mcp/`, `agents/subagents/`, `agents/hooks_bad/` | One review situation each: options built only inside `main()` (AGT003); a custom entry point named by `AGENT_ENTRY`; stdio and http `mcp_servers` with one `mcp__` prefix that has no server (MCP001); `AgentDefinition`s with and without turn caps (SUB0xx); hook callbacks with every HOK defect. Each `agent.py` docstring says what it demonstrates and "do not fix this file". |
| `agents/deploy_ready/` | Dockerfile, compose, OTEL env, an API-key gateway pattern and `setting_sources=[]`; comes back clean from all three linters, so each deploy test plants exactly one defect in a copy. |
| `agents/trap/` | A document-vault agent whose `release_document` mock succeeds for a sealed document while the system prompt forbids the call: separates "the agent refused" from "the backend refused". One adversarial case; its README says do not make the mock refuse. |
| `agents/stale_runner/` | The `good` agent with a runner copy stamped `0.0.1` and a config declaring `0.0.1`: `DEP001` and `CFG050`; `install_runner.py` refuses without `--upgrade`. Its README says do not upgrade this fixture. |
| `agents/ci_ready/` | Convention agent with two cases, a runner stub, `tests/test_evals.py` and two workflows: one generated and clean, one deliberately broken (`CI010`, `CI020`, `CI022`, `CI030`, `CI040`, `CI050`). Maturity L3 without shipped results, because `evals/results/` is gitignored. |
| `bin/fake_sdk.py` | A fake "Python that has the SDK", so no test ever needs the real one. |
| `cases/` | One case directory per failure mode, each the smallest thing that triggers exactly one finding: `valid` (clean), `broken_frontmatter` (EVC001), `bad_grader_type` (EVC010), `unknown_override` (EVC003), `not_overridable` (EVC004), `simulated_with_trajectory` (EVC040), `no_graders` (EVC060), `adversarial_lenient` (EVC041). |
| `eval_configs/` | `pr.json` and `nightly.json` (clean), `judge_retiring.json` (CFG010), `no_isolation.json` (CFG041 + CFG042), `bad.json` (thirteen ids at once, on purpose), `invalid_json.json` (CFG002). |
| `traces/*.trace.jsonl` | One run each, schema `agent-sdk-skills.trace/1`: `happy`, `loop`, `oscillation`, `stall`, `unknown_tool`, `budget_exceeded`, `max_turns`, `import_failed`, `structured_output`, `rate_limited`. Each produces exactly the failure signature its name claims. `two_models` is the odd one out: it is a whole measured run, not a shaped one. |
| `sessions/one_turn.jsonl` | A real `claude -p` session file, scrubbed. The shape `load_session` must survive, and it has no cost line. |
| `traces/refusal_success.trace.jsonl` | A refusal: `subtype: "success"` with `is_error: true` and `stop_reason: "refusal"`, whose text names a quota. Reports must call it a refusal, never an API error or a usage-limit hit. |
| `traces/init_2_1_301.*`, `traces/init_2_1_310.*` | A measured `init` per bundled CLI (11 and 13 `capabilities`), as the stub replays it (`.script.jsonl`) and as `Capture` writes it (`.trace.jsonl`). |
| `sessions/sdk_parallel_tools.jsonl` | One response that ran three tools in parallel: the transcript forks, and `load_session` must still emit every call, then every result, then the continuation. |
| `sessions/sdk_with_tool.jsonl` | A real `entrypoint: "sdk-py"` session with three tool calls, scrubbed. It carries the `cost-state` and `system`/`stop_hook_summary` lines, which is what makes an imported cost testable. |
| `results/series_5run/` | Three cases × five runs, with a judge grader that flips between runs — enough to tell pass@k from pass^k, and to show an `INFORMATIONAL` budget grader. |
| `results/failure_only/` | Every run FAILED: consistent failure, not flakiness. |
| `results/not_evaluated/` | A `rejected` rate limit. Every run `NOT_EVALUATED`, exit 3, never a fake FAIL. |
| `results/import_failed/` | The runner never reached the agent: exit 2, reported apart from regressions. |
| `mocks/library/` | The three good mocks. `mocks/broken/` carries one file per SIM id. |
| `personas/impatient.json`, `faults/slow-lookup.json` | A persona and a hook fault-injection config. |
| `frontmatter/` | Three sample headers (case, grader, mock) with their expected parse as JSON, so a second implementation of the frontmatter reader can be tested against the reference rather than against its author's memory. |

`agents/good/evals/runner/` is deliberately absent. The runner copy is installed
into a project by `install_runner.py`, and a fixture that shipped one would
freeze a copy that goes stale. Discovery reporting `DEP003` on this fixture is
therefore correct.

## Provenance of the two measured-derived fixtures

Everything above is written by hand except the *shape* of these two, which had
to be measured because guessing it is how a loader ends up confidently wrong.

**`traces/*.trace.jsonl`** are shaped from three live SDK runs recorded on
2026-09-30 and kept in `.dev/measured/run1.jsonl`, `run2.jsonl` and `run3.jsonl`
(the raw `Message` objects, one per line). What is carried over from those runs
is the *structure and the numbers*: the `usage` keys and their measured values
(`input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`, with `cache_creation` as a nested dict of ephemeral
TTL buckets), the `model_usage` block — including the `claude-haiku-4-5-20251001`
entry the CLI bills for its own internal work, which nobody asked for — the
`RateLimitEvent` payload verbatim (`allowed_warning`, 7-day window at 83 %,
`surpassedThreshold` 0.75 and the `unifiedWindows` sub-object), the `init`
fields (`apiKeySource: "none"`, and `claude_code_version`, which is re-pinned to
the bundled CLI at each sync — `2.1.310` today, `2.1.285` when they were
recorded), and the
synthetic `StructuredOutput` tool call that `output_format` results arrive as.
The prompts, tool names, arguments and reply text are this plugin's own library
domain, substituted in. `rate_limited.trace.jsonl` is the one exception and is
labelled as such in its own generator: a `status: "rejected"` rate limit was
never observed, so that file is a **stub** built from the measured
`allowed_warning` shape with the status and utilization changed.

**`traces/two_models.trace.jsonl`** is different in kind: it is a live run of
the `lookup-first` case on 2026-10-11 (SDK 0.2.165, bundled CLI 2.1.294, billed
to an API key), kept whole rather than shaped. The point of it is the `result`
event, where `model_usage` carries **two** models — `claude-sonnet-5-5` and the
`claude-haiku-5-5` entry the CLI billed for its own background work without
being asked — each with the undeclared `costBasis: "list"` and `thinkingTokens`
keys the wire adds to `ModelUsage`. Scrubbed: the temp working directory became
`/tmp/eval/run-1`, the session id and every tool-use, message and uuid became
deterministic placeholders, the timestamps became a flat one-per-second clock,
and the trailing hook events past the fourth were dropped because they repeat
two phases per tool and no test reads them. The prompt, the mock tool names and
the reply text are this plugin's own library domain.

**`traces/init_2_1_301.script.jsonl`** and **`traces/init_2_1_301.trace.jsonl`**
come from one live `query()` on 2026-10-17 (SDK 0.2.168, bundled CLI 2.1.301,
`permission_mode` unset, API key; `.dev/measured/0.2.168/live-6a-bundled-2.1.301.json`).
The script is the four messages as the stub replays them: the `init` whose data
carries `capabilities` (11), `fast_mode_state`/`fast_mode_disabled_reason`, the
undeclared keys (`original_cwd`, `additional_directories`, `memory_paths`,
`messaging_socket_path`, `per_turn_effort_active`, `view_mode`,
`analytics_disabled`, `product_feedback_disabled`) and `plugins[]` entries with
`source` instead of `version`; the new `system`/`commands_changed` message; the
reply; the result. The trace is what the 0.1.3 `Capture` writes from that script
(no runner was involved, so `permission_mode_source` is absent and the mode is
the CLI's own `default`). Scrubbed: paths became `/tmp/eval/run-1` and
`/home/user/...`, the socket path, session id, uuids and message id became
placeholders, `commands_changed` keeps three of its commands, and the trace
clock is one tick per second.

**`traces/init_2_1_310.script.jsonl`** and **`traces/init_2_1_310.trace.jsonl`**
come from one live `query()` on 2026-10-24 (SDK 0.2.174, bundled CLI 2.1.310,
`permission_mode` unset, API key, `setting_sources=[]`;
`.dev/measured/0.2.174/live/init_2_1_310.jsonl`). Three messages this time: the
`init` (`permissionMode: "default"`, 13 `capabilities` including the new
`interrupt_requeue_taken_v1` and `lifecycle_wakeup_source_v1`, the same undeclared
keys as 2.1.301), the reply and the result — 2.1.310 sent no
`commands_changed`. The trace is what the 0.1.4 `Capture` writes from that
script, and a test regenerates it to prove so. Scrubbed as for 2.1.301: paths
became `/tmp/eval/run-1` and `/home/user/...`, the socket path, session id,
uuids and message id became placeholders, the trace clock is one tick per
second. No key material was in the measurement (`sk-ant` absent).

**`traces/refusal_success.trace.jsonl`** is the `happy` trace cut down to
`init`, the user turn, the reply and the result, with the result rewritten to the
shape the Python SDK docs (read at Claude Code 2.1.310) give for a refusal:
`subtype: "success"`, `is_error: true`, `stop_reason: "refusal"`,
`terminal_reason: "completed"`, the refusal as `result_text`. A refusal was
**not** produced live (the measurement budget did not cover one); the SDK
passes these fields through from the CLI unchanged, so the docs' shape is what a
runner would record.

**`sessions/sdk_parallel_tools.jsonl`** is written by hand, ten lines, in the
transcript shape the CLI writes for a response with parallel tool calls and that
`claude-agent-sdk`'s MIT-licensed `tests/test_sessions.py` (`_parallel_tool_turn`)
builds: three `assistant` lines sharing `message.id`, chained `call-0 → call-1 →
call-2`, each `tool_result` line parented on its own call (with
`sourceToolAssistantUUID`), and the reply continuing from the last result. No
SDK code or data is copied. Measured on it with the 0.2.174 wheel:
`get_session_messages`'s chain builder returns every call, then every result in
timestamp order, then the reply — the order `load_session` now produces, and the
test also replays the SDK test's four result orders.

**The SDK venv.** `tests/lib/test_sdk_surface_live.py` and the encoding test in
`test_trace.py` need the real wheel. `tests/conftest.py` looks for it at
`$AGENT_SDK_TEST_PYTHON`, then at `../tmp/venvs/casdk-venv-0.2.174/bin/python`
next to the repo (`/Users/alex/Documents/Business/adk-evanl-skills/tmp/venvs/` on
the machine that syncs it), then at the old `/tmp/casdk-venv-*` paths, and skips
without one. It moved out of `/tmp` because macOS cleared it on 2026-10-22.

**`sessions/sdk_with_tool.jsonl`** is derived from a real session the runner
itself produced (`.dev/measured/session_with_tool.jsonl`, 37 lines, three MCP
tool calls). All 37 lines and all nine line types are kept, including the two
that `one_turn.jsonl` does not have: the `system` line with
`subtype: "stop_hook_summary"`, and the **`cost-state`** line holding
`totalCostUSD`, `totalDuration` and the per-model `modelUsage` block. That line
is why the fixture exists — it is the only place an imported session reports
what it spent, and `load_session` reads it into a synthesised `result` event
marked `imported_cost: true`. Scrubbed the same way as `one_turn.jsonl`: the
temp and home directory paths became `/home/evaluator/work/library-agent`,
emails became `evaluator@example.com`, `orgId`/`orgName` were dropped, and every
id was remapped deterministically so the `uuid`/`parentUuid` graph still
resolves.

**`sessions/one_turn.jsonl`** is derived from a real `claude -p` session
(`.dev/measured/session.jsonl`, 25 lines for a single "reply ready" turn). All
25 lines are kept, all seven line types are kept (`user`, `assistant`,
`attachment` ×13, `ai-title`, `queue-operation`, `atis-latch`, `last-prompt`),
and the whole `uuid`/`parentUuid` graph is kept intact — including the fact that
the assistant line's parent is an *attachment*, not the user line, which is the
detail a session loader has to handle and the reason the fixture exists.

Scrubbed before committing: the home directory path and the real working
directory (both the plain and the `~/.claude/projects/` encoded forms) became
`/home/evaluator/work/library-agent`; every email address became
`evaluator@example.invalid`; `orgId` and `orgName` became placeholders; and
every session id, prompt id, request id, message id and uuid was replaced with a
deterministic placeholder, remapped consistently so the parent graph still
resolves. Two oversized payloads — the host's own skill listing and its prompt
snapshot, tens of kilobytes of machine-specific configuration — were replaced
with a marker string that records their original length. No line was removed and
no key was renamed.

One shape in that file is **not** measured and nothing here claims it: the
session-side tool-result key (`toolUseResult`). The measured session had no tool
call, and scanning other sessions for one was correctly refused by the PII
classifier. `load_session` reads the key if it is present and never requires it;
the only fixture exercising it is built by hand in `tests/lib/test_trace.py` and
is labelled there.
