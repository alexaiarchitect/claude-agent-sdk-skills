# Finding and importing session files

## Where they are

The SDK's subprocess writes every session under `~/.claude/projects/`, in a
directory named for the working directory with `/` replaced by `-`, or under
`CLAUDE_CONFIG_DIR/projects/` when that variable is set. One `.jsonl` per
session, named by session id. The runner's `init` event and result carry the
`session_id`, so a trace can be matched to its session file.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/import_session.py <session-id-or-path> --cwd <project> --out evals/results/imported/
```

`import_session.py` resolves an id to a path with the same encoding the SDK
uses, converts the file to the trace shape, and writes
`<session-id>.trace.jsonl`. It never modifies the session file.

## What import preserves and what it cannot

| Preserved | Lost |
|---|---|
| user and assistant turns, tool calls and results, order | cost (`total_cost_usd`) |
| the CLI version (`cli_version`) and entrypoint | `terminal_reason`, `num_turns`, `subtype` |
| `toolUseResult` payloads where present | rate-limit events (not written to sessions) |
| the session id | the options the session started with, beyond what `init`-like lines record |

So an imported trace supports `trajectory`, `tool_used`, `tool_order`,
`no_tool`, `regex` and `final_text` graders, and the signature detection, but
`budget` and `terminal` graders report `NOT_EVALUATED`.

## Privacy

Session files contain everything the user and the agent said, file contents
the agent read, and paths under the home directory. Keep imported traces out
of version control (`evals/results/` is gitignored by the scaffold), and
redact before sharing. The plugin's own fixtures use a scrubbed session with
paths, ids and account details replaced.

## Production incidents

The sequence: import the session, run `analyze_trace.py --trace` on the
result, name the shape and the layer, then write the failing trajectory into a
regression case with `/agent-sdk:eval-create`'s `trace_to_case.py`, and run it
under the runner to get the cost and terminal fields the import lacks.

---

Sources: `https://code.claude.com/docs/en/agent-sdk/sessions`,
`https://code.claude.com/docs/en/agent-sdk/session-storage` (locations,
`CLAUDE_CONFIG_DIR`), `https://code.claude.com/docs/en/agent-sdk/hosting`
(state on local disk); this plugin's `lib/agent_sdk_skills/trace.py`.
