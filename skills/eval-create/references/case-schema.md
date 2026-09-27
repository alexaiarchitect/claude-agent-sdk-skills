# The case file format

A case is a directory under `evals/` holding `prompt.md` and a `graders/`
directory. The directory name is the case name unless the frontmatter says
otherwise.

```
evals/refuse-double-booking/
├── prompt.md
└── graders/
    ├── never_reserves_twice.md
    └── refuses_clearly.md
```

## `prompt.md` frontmatter

| key | type | default | notes |
|---|---|---|---|
| `name` | str | directory name | result files are keyed by this |
| `tags` | list[str] | `[]` | free-form; `--tag` on the runner filters on them |
| `category` | one of five | — | `EVC030` (info) when absent |
| `runs` | int ≥ 1 | from the tier | repeated runs are how reliability gets a number |
| `max_turns` | int | — | becomes `ClaudeAgentOptions.max_turns` |
| `timeout_seconds` | int | 180 | wall clock per run, enforced by the runner |
| `agent` | `module:function` | config's `agent` | per-case entry point |
| `turns` | list[str] | — | scripted multi-turn; excludes `simulated_user` |
| `simulated_user` | path | — | persona JSON; excludes `turns` |
| `overrides` | mapping | `{}` | a subset of `ClaudeAgentOptions` |
| `mocks` | list[str] | `[]` | server names under `evals/mocks/` |
| `faults` | path | — | fault-injection config |
| `env` | mapping | `{}` | keys must start `EVAL_` |
| `scaffold_script` | str | — | bash, run in the fresh per-run working directory |

The **body** is the first user prompt. When `turns` or `simulated_user` is set
the body is ignored, and saying so is `EVC002` (info) — write the case with no
body rather than leaving a prompt that never runs.

`env` uses the indented mapping form, never the flow form:

```yaml
env:
  EVAL_BRANCH: main          # correct
# env: { EVAL_BRANCH: main } # does not parse
```

## `overrides`: what a case may and may not set

Two lists, both derived from the SDK's own field list:

* **`OPTION_NAMES`** — all 49 `ClaudeAgentOptions` fields. A name outside this
  list is `EVC003`, an error, and it is caught *before* a session starts. A
  typo like `modle:` would otherwise be a silent no-op discovered after paying
  for the run.
* **`OVERRIDABLE_OPTIONS`** — the JSON-expressible subset a case may set. A
  real option that is not in it is `EVC004`: the runner owns it.

Runner-owned, and why: `cwd` and `enable_file_checkpointing` (the runner gives
each run a fresh directory), `hooks` and `can_use_tool` (the runner's capture
and fault hooks live there), `mcp_servers` (mocks replace servers by name
instead), `stderr`/`debug_stderr`, and the whole session-resumption family
(`resume`, `fork_session`, `continue_conversation`, `session_id`, …) because a
case that resumes someone else's session is not reproducible.

Deprecated, warned when set: `max_thinking_tokens` (use `thinking`), and
`allowed_tools` containing `"Skill"` (use `skills`).

## Isolation, and what overriding it costs

The runner forces two options on every run unless the case overrides them:

```python
setting_sources=[]          # no user/project/local settings, no CLAUDE.md
strict_mcp_config=True      # no ambient or managed MCP servers
```

The measurement behind this is a 17x cost difference with ambient settings
loaded. A case that overrides either gets an informational note in the trace,
because from that point the result describes the machine it ran on.

`setting_sources=[]` is not total isolation — builtin plugins and their skills
still load.

## Grader files

One file per grader under `graders/`. Frontmatter carries `type` and that
type's fields; the body is prose saying what the check proves and what it does
not. For `llm` graders the body is *also* the criteria, split by a bare `---`:
everything above it goes to the judge, everything below is for the next reader.

```markdown
---
name: refuses_clearly
type: llm
focus: the final reply only
samples: 3
---
PASS if the reply declines and states the reason.

FAIL if it agrees, asks the user to confirm instead of declining, or gives no
reason.

---

Proves the refusal is usable. It does not prove the agent held back — the
`no_tool` grader beside it does that.
```

Tool names in graders should be the full `mcp__<server>__<tool>` form, which is
what the model sees and what the trace records. A bare name matches by suffix,
but the report will tell you to qualify it (`EVC020`).

Sources: `.dev/CONTRACTS.md` §1, §1.1, §1.2, §2 and §12 (the normative format,
the overridable lists, the isolation defaults, the `llm` body split and the
`env` form); `lib/agent_sdk_skills/evalcase.py` and `graders.py` (the
validators and every `EVC` id); `lib/agent_sdk_skills/__init__.py`
(`OPTION_NAMES`, `RUNNER_OWNED_OPTIONS`, `ISOLATION_DEFAULTS`);
https://code.claude.com/docs/en/agent-sdk/python (`ClaudeAgentOptions`).
