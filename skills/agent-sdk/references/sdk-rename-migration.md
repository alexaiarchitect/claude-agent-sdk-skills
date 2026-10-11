# `claude_code_sdk` names and their Agent SDK replacements

The Claude Code SDK was renamed to the Claude Agent SDK; the Python package is
`claude-agent-sdk` (import `claude_agent_sdk`), the TypeScript package is
`@anthropic-ai/claude-agent-sdk`. Old names still turn up in code written from
early examples, and the reviewer flags them (`AGT030`) because the retired
package no longer receives the CLI the current SDK bundles.

## Renames

| Old | New | Reviewer id |
|---|---|---|
| `pip install claude-code-sdk` / `from claude_code_sdk import ...` | `pip install claude-agent-sdk` / `from claude_agent_sdk import ...` | `AGT030` (error) |
| `ClaudeCodeOptions` | `ClaudeAgentOptions` | `AGT030` (error) |
| `@anthropic-ai/claude-code` (npm) | `@anthropic-ai/claude-agent-sdk` | not reviewed (Python only) |
| `max_thinking_tokens` | `thinking` (a `ThinkingConfig`) or `effort` | `AGT031` (warn) |
| docs under the old `docs.claude.com` API section | `code.claude.com/docs/en/agent-sdk/...` | hygiene test on references |

## Behaviour changes that came with v0.1.0

**The system prompt is no longer Claude Code's by default.** A session started
with no `system_prompt` gets a minimal prompt. To get the old behaviour ask for
the preset explicitly:

```python
ClaudeAgentOptions(system_prompt={"type": "preset", "preset": "claude_code"})
```

or set your own string. An agent migrated without noticing this loses the
coding-assistant behaviour it was written against, which shows up in evals as a
trajectory that stops calling tools.

**Settings sources.** v0.1.0 briefly loaded no filesystem settings by default,
then reverted. Today, omitting `setting_sources` loads user, project and local
settings and `CLAUDE.md`, matching the CLI. `setting_sources=[]` runs isolated;
Python SDK 0.1.59 and earlier ignored the empty list, so upgrade before relying
on it. The reviewer's `OPT020` points at this because an eval or CI run with
the developer's local settings in the prompt measures something other than the
agent.

**Omitting `permission_mode` changed meaning too**, and later than the rename.
It used to be equivalent to passing `"default"` — the docs state the equivalence
ended before TypeScript Agent SDK v0.3.286 — and from Claude Code **2.1.285** a
headless session that does not fetch the interactive feature flags (a gateway
token, a third-party provider, telemetry off) starts in **`auto`** instead, where
a classifier reviews each shell command and network request and broad allow
rules such as a bare `Bash` are dropped. A project migrated years ago and never
revisited is exactly the one that relies on the old equivalence. Pass the mode
explicitly; `OPT013` flags the omission.

**Two more surfaces worth knowing on an old project.** `fork_session()` is now a
module-level function that copies a transcript into a new session, distinct from
the long-standing `fork_session: bool` option that forks on resume — so a
migration that greps for the name finds two different things. And
`ClaudeSDKClient.get_context_usage()` returns what `/context` shows, as an
unbilled off-stream token-counting request, which is a cheaper way to answer
"why is this session so expensive" than instrumenting the agent.

## What to do with a flagged project

1. `pip uninstall -y claude-code-sdk && pip install claude-agent-sdk`; update
   `requirements.txt` or `pyproject.toml`.
2. Replace the imports and the options class name.
3. Decide the system prompt deliberately: preset, custom, or minimal.
4. Decide `setting_sources` deliberately: `[]` for evals, CI and hosting.
5. Re-run `/agent-sdk:agent-review`, then the `pr` tier, before trusting any
   result produced after the rename.

---

Sources: `https://code.claude.com/docs/en/agent-sdk/migration-guide` (renames,
system prompt default, settings sources default and the 0.1.59 note);
`https://code.claude.com/docs/en/agent-sdk/python` (`ClaudeAgentOptions` fields,
`fork_session`, `get_context_usage`);
`https://code.claude.com/docs/en/agent-sdk/permissions` and
`https://code.claude.com/docs/en/permission-modes` (which mode a session starts
in). Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296
docs.
