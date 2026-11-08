# Evidence: what a trace holds, and what a session file does not

## The runner's trace

`evals/results/<ts>/<case>.<n>.trace.jsonl`, one event per line:

| Event | What to read in it |
|---|---|
| `init` | model, tools, MCP servers, permission mode, `cli_version`, `api_key_source`, the isolation applied |
| `user` | the prompt of each turn |
| `assistant_text` | what the agent said, and `model` (the model that answered) |
| `tool_use` | `tool`, `input`, `parent_tool_use_id` (set inside a subagent), `synthetic` (`StructuredOutput`) |
| `tool_result` | `is_error` (truthy on error, `null` on success), `content` (truncated), `tool_use_result` |
| `hook` | `event`, `phase`, `decision`, `fault_id` when a fault was injected |
| `rate_limit` | `status`, `windows` (five-hour and seven-day utilization), `resets_at` |
| `system` | any other system message, as `subtype` and `data` — including a failed hook callback (`subtype: informational`, `data.tag: hook_callback_failed`) |
| `result` | `subtype`, `is_error`, `terminal_reason`, `stop_reason`, `num_turns`, `total_cost_usd`, `cost_delta_usd`, `usage`, `permission_denials`, `structured_output`. Read `stop_reason` before `is_error`: on `subtype: success`, `refusal` (the model declined) and `tool_deferred_unavailable` (a deferred tool gone on resume) set `is_error` without being API errors |

Useful reads:

- **`permission_denials`** on the result: a stall with denials is a permission
  problem, not a reasoning problem.
- **`parent_tool_use_id`**: calls made inside a subagent; a loop inside a
  subagent shows up as repeated events with the same parent.
- **`synthetic: true`**: the structured-output call; not a real tool call.
- **`cost_delta_usd`**: the cost of one turn; `total_cost_usd` is the running
  total of the session.
- **`hook_callback_failed`**: an SDK hook callback raised, returned `None` or
  returned a value the CLI rejected (`on_failure` needs claude-agent-sdk 0.2.177+
  and Claude Code 2.1.317+). The `data.content` says what happened next
  (measured on 2.1.318 and, unchanged, on 2.1.319): "…Its answer was treated as empty." means the call went
  ahead — a guard that failed open; "…onFailure is "block", so this failure
  counts as a block." means it was refused, the tool result reads `failed;
  blocking because onFailure is "block"` and the call is in
  `permission_denials` while the result is still `success`. The guard's own
  error text is not in the trace; read the app's logs for it.

## A Claude Code session file

`~/.claude/projects/<encoded cwd>/<session-id>.jsonl` is what the CLI writes
for any run, including production runs of the agent. `import_session.py`
turns it into the same trace shape so it can be analysed without re-running.
Two differences matter:

- **No result event.** Sessions carry no cost, no `terminal_reason`, no
  `num_turns`. `budget` and `terminal` graders report `NOT_EVALUATED` on an
  import, and the cost line is blank.
- **Bookkeeping lines.** Most lines are not messages (`attachment`,
  `ai-title`, `queue-operation`, ...); the loader keeps them as `system`
  events and orders messages through the `parentUuid` graph, which runs
  through attachment lines.
- **Parallel tool calls fork the graph.** The CLI writes one assistant entry
  per tool call, chained by `parentUuid`, and parents each `tool_result` on its
  own call, so the conversation continues from whichever result was written
  last. The SDK's `get_session_messages` returned only that branch before
  0.2.170 (it now returns every call and result); this plugin's loader keeps
  every entry and, from 0.1.4, orders a parallel turn as all calls, then all
  results sorted by timestamp, then the reply.

`version` in a session file is the CLI version, which may differ from the CLI
bundled with the SDK the runner used; both are reported. Before **2.1.311**,
`claude -p` and SDK sessions could save transcript messages **out of order** or
keep messages that were taken back; a session file written by an older CLI
(the 0.2.174 wheel bundled 2.1.310; the pinned 0.2.182 bundles 2.1.325) can therefore disagree with the live
message stream. Prefer the runner's trace, which records the stream as it came,
and order a session file by its `parentUuid` graph, never by line position.

## When the CLI never started

A run that fails at startup leaves no trace and no session file; the evidence
is the exit code and stderr. The Claude Code `CHANGELOG.md` (2.1.314) says
`claude -p` used to exit 0 with no output when startup failed and now prints the
error and exits 1. Separately, measured by this plugin on 2026-11-02: six bad
flags or configurations (a missing `--settings` file, invalid `--mcp-config`
JSON, an unknown `--resume` id, a bad `--permission-mode`, invalid `--agents`
JSON, a bad `--setting-sources`) all exited 1 with the error on stderr on both
2.1.310 and 2.1.316, and through the SDK each raised `ProcessError` with
`exit_code=1` on 0.2.174 and 0.2.176 (the message itself goes to the parent's
stderr). The runner reports that as `NOT_EVALUATED` (exit 2), so read stderr
before reading the agent.

Later CLI changes affect what the exit code and result mean (changelog):
from **2.1.317** `claude -p` exits 1 when a full disk or quota lost its transcript
or `~/.claude.json` writes (it used to exit 0); from **2.1.318** `claude -p` and SDK
sessions no longer report `success` when an API error cut off a reply while a mod
hooked `turn.step`, so on an older CLI a truncated final text under `success` may
be an API error. Also from 2.1.318, `claude -p` JSON carries
`credential_expires_at` when a stored claude.ai sign-in is in use (absent with an
API key, measured 2026-11-04), text output warns on stderr 10 days before that
date, and a run whose sign-in has expired says so and names `claude auth login`
and `claude setup-token`. From **2.1.319** (changelog) an SDK host whose run failed on a
full disk gets that run's own error instead of a generic exit-code error; `claude -p` exits 1 when
auto mode refused actions for lack of a safety check; and a `claude -p --resume` whose deferred
tool's MCP server is missing exits 1, keeps the call and refuses later input until the tool is back
or `CLAUDE_CODE_DROP_UNAVAILABLE_DEFERRED_TOOL=1` drops it (hooks page).

## Capturing fresh evidence (spends)

When no trace exists, the cheapest new evidence is one run of the failing
case: `/agent-sdk:eval-run --case <name> --runs 1`. Ask first; it starts a
session. For a production incident, prefer importing the session file that
already exists.

---

Sources: this plugin's `.dev/CONTRACTS.md` §5 (trace events) and the measured
session file in `.dev/VERIFIED-FACTS.md`; session storage per
`https://code.claude.com/docs/en/agent-sdk/sessions` and
`https://code.claude.com/docs/en/agent-sdk/session-storage`; result fields per
`https://code.claude.com/docs/en/agent-sdk/python` (`ResultMessage.is_error`);
the parallel-call shape per the claude-agent-sdk-python `CHANGELOG.md` (0.2.170)
and `_internal/sessions.py`;
re-read 2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs;
the transcript-order fix per the Claude Code `CHANGELOG.md` (2.1.311) and the
`-p` startup-failure line per the same changelog (2.1.314); the startup-failure
exit codes and `ProcessError` measured by this plugin on 2026-11-02
(`.dev/VERIFIED-FACTS.md`); `https://code.claude.com/docs/en/agent-sdk/hooks#block-the-action-when-a-callback-fails`
(`hook_callback_failed`), the Claude Code `CHANGELOG.md` 2.1.317–2.1.319 (exit 1 on
lost writes, API-error-cut replies, `credential_expires_at`; disk-full error, auto-mode exit 1,
deferred-tool resume), `https://code.claude.com/docs/en/hooks` ("Resume when a deferred tool is
unavailable"); both `on_failure` paths and the `-p` JSON keys measured by this plugin on
2026-11-04 on 0.2.178 / 2.1.318 and again on 2026-11-08 on 0.2.179 / 2.1.319.
Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
