---
name: agent-harness
description: >-
  Design and check the wired parts of a Claude Agent SDK (Python) agent: hooks,
  the permission model, MCP servers and in-process tools, subagents, and the
  `setting_sources` isolation that decides whether a run depends on the machine
  it ran on. Checks hook callbacks for async, three parameters, the right
  `hookSpecificOutput`/`hookEventName` shape, a valid matcher regex and an event
  the Python SDK actually has; `mcp__` prefixes that name no server; stdio
  commands missing from PATH; `@tool` schemas; `AgentDefinition` tools, model
  and `maxTurns`. Generates correct hook callbacks, `.mcp.json` or
  `mcp_servers=` wiring, and subagent definitions, always with a write plan
  first. Use when asked to "add a hook", "audit every tool call", "block
  dangerous commands", "inject context", "why does my hook never fire", "set up
  an MCP server", "restrict what my agent can do", "add a subagent", "cap
  subagent spend", or "why does my agent read my CLAUDE.md". Don't use for a
  whole-agent review (use `/agent-sdk:agent-review`), hosting, containers and
  credentials (use `/agent-sdk:agent-deploy`), mock MCP servers and fault
  injection for evals (use `/agent-sdk:eval-simulation`), or diagnosing a run
  that already happened (use `/agent-sdk:agent-debug`).
argument-hint: "[project-dir]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, Bash(python3 *)
---

# The harness: hooks, permissions, MCP, subagents

The harness is the part of an agent that is wired rather than written, and it
fails quietly. A synchronous hook callback raises only when the event fires. A
hook that returns the wrong dict raises nothing at all — the decision simply
never arrives. An `mcp__` prefix for a server that does not exist is a rule that
can never match. None of it shows up as an error; it shows up as an agent that
does not behave the way its code says it should.

So: check before designing, and generate the shape rather than describing it.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own
directory. Use it verbatim in every command below; a sibling skill's scripts
are at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Check what is wired now.**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/lint_harness.py <project>
   ```

   `--json` to branch on ids, `--no-path-check` when the agent runs elsewhere.

2. **Report** the findings and the gaps separately. A finding is something
   present and wrong; a gap is something absent — no hooks, no MCP server, no
   subagents — and a gap is a suggestion, not a defect.

   Name every finding by the id the script printed (`HOK001`, `MCP001`, …),
   with the severity the script gave it and its `Source:` line, so the reader
   can check the claim. Never assign a severity of your own, and never report
   an id the script did not print. Describing a hook defect in prose with no id
   leaves the reader nothing to look up and nothing to re-run. When the fix is
   a hook, offer the generator by name — `gen_hook.py` — as the next step.

3. **Options.** Fix the wiring errors first; then generate what is missing.
   Name the cost: every generator here is free and writes at most one file.

4. **Confirm, then generate.** Every generator prints a write plan first and
   supports `--dry-run`. Show the plan, get a yes, then run it without
   `--dry-run`. An existing file is skipped unless the user asks for `--force`.

5. **Verify.** Re-run `lint_harness.py`. A generated hook should produce no
   `HOK` findings; if it does, the generator is wrong and that is worth saying.

## The four surfaces

| Surface | The decision | What goes wrong |
|---|---|---|
| **Hooks** | which of the ten Python events, which matcher, what the callback returns | not `async`; a dict with no `hookSpecificOutput`; a `hookEventName` that does not match the event; an invalid matcher regex; `SessionStart`, which the Python SDK does not have |
| **Permissions** | `tools` (availability) vs `allowed_tools` (permission) vs `disallowed_tools` (both), and the mode | believing `allowed_tools` restricts anything; `bypassPermissions` because a prompt was in the way; `can_use_tool` set where it can never fire |
| **MCP** | in-process, stdio or HTTP; and the server key, which becomes the tool prefix | an `mcp__x__` name with no server `x`; a stdio command missing on the target host; ambient servers loading because `strict_mcp_config` is unset |
| **Subagents** | what to delegate, with which tools, under which ceiling | no `tools`, so it inherits everything; no `maxTurns`, so nothing bounds it; the Agent/Task tool not allowed, so nothing delegates at all |

## Decision rules

- **`allowed_tools` pre-approves; it does not restrict.** `tools=[]` removes the
  built-ins; a bare name in `disallowed_tools` removes one tool. Say this
  whenever an allow list is the subject.
- **To observe every tool call, use a `PreToolUse` hook, not `can_use_tool`.**
  `can_use_tool` fires only when the rules evaluate to "ask", so it never sees a
  pre-approved call — and setting both raises `CanUseToolShadowedWarning`.
- **`return {}` is the safe hook return.** It means allow, unchanged. Only
  reach for `hookSpecificOutput` when the hook is meant to change something.
- **Only `PreCompact` has no `hookSpecificOutput` type.** `Stop` and
  `SubagentStop` take `hookSpecificOutput.additionalContext` (typed from
  0.2.166), but blocking a stop is still the top-level `decision: "block"` +
  `reason`. Do not generate `hookSpecificOutput` for `PreCompact`.
- **Probability belongs inside the callback.** `HookMatcher` has no
  `probability` field; matchers on one event are dispatched concurrently.
- **Prefer in-process MCP tools.** No subprocess, no network, testable
  directly, and the tool names are ones you chose — which is what makes a
  trajectory grader possible.
- **`setting_sources=[]` plus `strict_mcp_config=True`, for anything
  reproducible.** Measured on this machine: 17x the cost without them, and the
  tool surface changes with the host. `[]` still leaves builtin plugins and
  managed MCP; say so rather than promising isolation.
- **A subagent gets one prompt string and returns one final message.** Whatever
  must be verified has to be in that message, a file, or a mock call record.

## References

| Question | File |
|---|---|
| All ten events, when they fire, input fields, return shapes, timeouts, concurrency | [hooks-catalog.md](references/hooks-catalog.md) |
| The seven-step evaluation order, the six modes, `tools` vs `allowed_tools` | [permission-model.md](references/permission-model.md) |
| In-process vs stdio vs HTTP, `mcp__server__tool`, `strict_mcp_config`, mocks | [mcp-patterns.md](references/mcp-patterns.md) |
| `AgentDefinition` fields, depth/concurrency/spend caps, the Agent/Task naming | [subagent-design.md](references/subagent-design.md) |
| `setting_sources`, `CLAUDE.md`, auto memory, and the 17x measurement | [context-and-settings.md](references/context-and-settings.md) |

Finding ids and severities are listed in
`${CLAUDE_SKILL_DIR}/../agent-review/references/review-checklist.md`.

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/lint_harness.py <project> [--json] [--no-path-check]` | checks hooks, permissions, MCP and subagents | 0 no errors, 1 errors, 2 nothing to check |
| `scripts/gen_hook.py --event E --purpose audit\|deny\|inject\|latency [--tool T] [--probability p] [--out path] [--dry-run] [--force] [--json]` | writes a callback with the right shape and its `HookMatcher` line | 0 written or planned, 1 nothing written, 2 event and purpose do not go together |
| `scripts/gen_mcp_config.py --server NAME (--command CMD [--arg=X] \| --url URL) [--as mcp-json\|python] [--dry-run] [--force] [--json]` | writes `.mcp.json` or an `mcp_servers=` snippet | 0 written or planned, 1 nothing written, 2 bad arguments |
| `scripts/gen_subagent.py --name N --description D [--tools ...] [--model M] [--max-turns N] [--as python\|markdown] [--dry-run] [--force] [--json]` | writes an `AgentDefinition` or `.claude/agents/<name>.md` | 0 written or planned, 1 nothing written, 2 bad arguments |

## Completion checklist

- [ ] `lint_harness.py` ran first, and its findings and gaps were reported separately.
- [ ] Every hook finding was explained as "this fails silently", not "this is invalid".
- [ ] If an allow list was the subject, the user was told it only pre-approves.
- [ ] Every generated file was shown as a write plan and confirmed before writing.
- [ ] `lint_harness.py` was re-run after generating, and came back clean.
- [ ] If the agent will be hosted, the user was pointed at `/agent-sdk:agent-deploy`.
