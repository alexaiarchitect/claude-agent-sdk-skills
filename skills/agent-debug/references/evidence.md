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
| `result` | `subtype`, `terminal_reason`, `num_turns`, `total_cost_usd`, `cost_delta_usd`, `usage`, `permission_denials`, `structured_output` |

Useful reads:

- **`permission_denials`** on the result: a stall with denials is a permission
  problem, not a reasoning problem.
- **`parent_tool_use_id`**: calls made inside a subagent; a loop inside a
  subagent shows up as repeated events with the same parent.
- **`synthetic: true`**: the structured-output call; not a real tool call.
- **`cost_delta_usd`**: the cost of one turn; `total_cost_usd` is the running
  total of the session.

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

`version` in a session file is the CLI version, which may differ from the CLI
bundled with the SDK the runner used; both are reported.

## Capturing fresh evidence (spends)

When no trace exists, the cheapest new evidence is one run of the failing
case: `/agent-sdk:eval-run --case <name> --runs 1`. Ask first; it starts a
session. For a production incident, prefer importing the session file that
already exists.

---

Sources: this plugin's `.dev/CONTRACTS.md` §5 (trace events) and the measured
session file in `.dev/VERIFIED-FACTS.md`; session storage per
`https://code.claude.com/docs/en/agent-sdk/sessions` and
`https://code.claude.com/docs/en/agent-sdk/session-storage`.
