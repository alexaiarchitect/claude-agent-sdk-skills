# Mock MCP servers: one file per tool, and what a mock may return

A mock replaces one entry of the agent's `mcp_servers` with a deterministic
in-process server, so a case asserts on the agent's behaviour instead of on
whatever the real backend returned today. Mocks are the cheapest lever in this
skill: they cost nothing to write and add no model calls at run time.

## Layout and shape

```
evals/mocks/<server>/<tool>.md
```

The **directory name is the server name** and the **file stem is the tool name**;
the model sees `mcp__<server>__<tool>`. A case opts in with `mocks: [library]`,
and the runner builds
`create_sdk_mcp_server(name="library", version="1.0.0", tools=[...])` and
replaces the agent's `mcp_servers["library"]` by name. Servers the case does not
name are left exactly as the agent built them.

```markdown
---
type: canned
description: Find a book by title and report copies and holders
schema:
  title: str
expect:
  title: Dune
latency_ms: 40
---
{{input.title}}: 2 copies available; reserved by nobody.
```

| Key | Meaning |
|---|---|
| `schema` | the input schema the server advertises — **required** (`SIM010`) |
| `description` | what the tool does, in the words the model reads |
| `expect` | an input guard checked inside the handler |
| `error` | return an error result instead of the body (`SIM011` if a body is also present) |
| `latency_ms` | `asyncio.sleep` before answering (`SIM012` if negative or non-numeric) |
| `type` | `canned` (default) or `agent` (`SIM013` for anything else) |
| `name` | overrides the file stem; normally left out |

Any other frontmatter key makes the runner refuse the file (`MCP010`).

## The body and its three substitutions

The body is the canned result. Exactly three templates are expanded, and nothing
else:

| Template | Expands to |
|---|---|
| `{{input.x}}` | the call's `x` argument; dotted paths (`input.a.b`) walk nested dicts; missing → empty string |
| `{{input.x\|fallback}}` | the argument, or the literal fallback when it is missing |
| `{{file:fixtures/catalog.json}}` | the file's text, read relative to the mock file's own directory; a missing file becomes `<<missing mock fixture …>>` rather than an exception |

`validate_sim.py` warns when the body substitutes a key the `schema` does not
declare: the substitution would render empty, silently.

## Why only text comes back

The handler returns
`{"content": [{"type": "text", "text": …}], "is_error": True?}`. Of what an MCP
tool may legally return, only `text` and `image` (`data` + `mimeType`) survive
intact: a `resource_link` and a text `resource` are flattened to text, and
**binary resources and unknown types are dropped with a warning**. A mock that
emits them emits nothing. So a mock speaks prose.

## Why `schema` is not optional

Input is validated against the declared schema **before** the handler runs, and
both a schema violation and a raised exception reach Claude as an error result.
Three consequences:

- A mock with no schema gets a permissive default from the runner, and a mock
  that advertises nothing tells the model nothing about how to call it.
- A mock **cannot observe malformed input** unless its schema is permissive. If
  the case is *about* bad input, give the mock a loose schema and catch the bad
  call with `expect`.
- A schema that has drifted from the real tool turns every call into an error
  result the mock never sees — the case fails for a reason that has nothing to
  do with the agent.

`gen_mocks.py --from-agent` reads the schemas out of the agent's `@tool`
decorators with the AST reader, so the mock and the real tool start life in
agreement.

## `expect`: the runner's own guard

`expect` is checked **inside** the handler, after schema validation:

```yaml
expect:
  member_id: member-42
```

A call whose `member_id` is anything else is recorded as a mock call with
`is_error: true` and the text `mock <tool>: unmet expectation(s): …`, which the
agent then reads. Use it when the assertion is "it called this with *these*
arguments" and you want the agent to feel the mismatch. When you only want to
assert afterwards, use a `tool_used` grader with `args_match` instead — `expect`
changes the run.

Two mocked tools cannot be reached unattended whatever you pre-approve. A tool
whose server sets `requiresUserInteraction`, and a connector tool an
organisation has set to `ask`, always land at the ask step — and in `dontAsk`
they are **denied** rather than prompted, because that mode never prompts. If
the agent needs such a tool in a suite, the mock has to stand in for it
entirely; no allow rule will let the real one through. (A read from a network
path is denied in `dontAsk` for the same reason, so a mock that returns a
`\\server\share` path is setting the agent up to fail.)

## `mock_calls`: the only evidence a mock was reached

The SDK records nothing about in-process tools, so the runner's own wrapper
records every call: `{tool, server, name, input, output_chars, output (2 KB),
is_error, note}`. Graders with `target: mock_calls` read that list. Without the
wrapper there would be no way to prove a mock was ever called — `include_hook_events`
does not cover in-process tools.

## Not this runner: `claude plugin eval`'s mock rules

`claude plugin eval` has its own mock mechanism with a confusingly similar
`expect:` key, and three of its rules became load errors in the 2.1.289/2.1.293
window. They do **not** apply to the format above, but a case written for one
and pasted into the other will fail in a way that reads like a bug:

- `expect:` patterns there follow a documented `/regex/` **dialect**: literals,
  `.`, `\d`-style escapes, classes `[a-z]`, quantifiers `*` `+` `?` `{m,n}`
  (over a single character, escape or class only), an optional `^`/`$`, and the
  flags `i` and `s`. **No groups, no alternation, no backreferences, no
  lookaround** — an out-of-dialect pattern is a load failure that scores 0 and
  names the pattern. Use a list of literals where you would have written `a|b`.
- all `type: agent` mocks in a run **share one call budget** of 4 × the case's
  `max_turns` (40 at the default 10). Replay-recorded calls count against it,
  and exceeding it aborts the run with score 0 and "mock call budget exceeded".
- an `expect:` guard on `_server.md` is a load error unless its `tools:` key
  names **exactly one** tool.

## Trap mocks

The sharpest use of a mock is not to make the happy path deterministic; it is to
make the wrong answer *available*. A trap mock answers favourably while the
scenario carries a stop condition the agent must honour — the catalogue reports
a copy available for a member who already holds one, the payments mock accepts a
refund the policy forbids. The agent that follows its rules never calls the
tool; the agent that is pleasing the user does, and the mock says yes.

A trap case therefore pairs:

- a mock that would succeed, so nothing external stops the agent;
- a `no_tool` grader (or `tool_used` with `count:0`) on the forbidden call;
- an `llm` grader on whether the refusal gave a reason.

A trap with a mock that *refuses* proves nothing: the backend stopped the agent,
not the agent's judgement.

## Generating them

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/gen_mocks.py <project> --from-agent --dry-run
python3 ${CLAUDE_SKILL_DIR}/scripts/gen_mocks.py <project> --from-agent
```

One file per in-process `@tool`, with the tool's own description, its declared
schema, and a body that substitutes every declared input. External
`mcp_servers` entries (stdio, http, sse) have no schema in the source, so each
gets one stub with a TODO schema; ask the live server for the real ones with
`python -m agent_sdk_evals list-tools <evals-dir> --probe`.

Sources: this plugin's runner —
`runner/agent_sdk_evals/mocks.py` (`load_mock_tools`, `substitute`,
`build_handler`, `build_servers`, `MockRecorder`), `MOCK_KEYS`;
`lib/agent_sdk_skills/mocks.py` (the `SIM010`–`SIM013`, `MCP020` checks);
`.dev/CONTRACTS.md` §4 (mock format and the content-item pins), §12.7
(`{{input.x|fallback}}`);
`https://code.claude.com/docs/en/agent-sdk/custom-tools` (`tool`,
`create_sdk_mcp_server`),
`https://code.claude.com/docs/en/agent-sdk/mcp` (`mcp__<server>__<tool>` naming);
`https://code.claude.com/docs/en/plugin-evals` (that product's `/regex/` mock
dialect, the shared agent-mock call budget, the `_server.md` guard rule),
`https://code.claude.com/docs/en/permission-modes` (`dontAsk`'s always-denied
list). Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296
docs.
