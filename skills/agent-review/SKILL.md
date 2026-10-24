---
name: agent-review
description: >-
  Report-only static review of a Claude Agent SDK (Python) agent, read from the
  syntax tree so it works on a project that does not yet run. Checks the entry
  point and whether the options are injectable at all, `claude_code_sdk` and
  `ClaudeCodeOptions` leftovers, deprecated fields, model policy (hardcoded,
  retiring, retired, or unpinned so the session inherits Claude Code's default),
  credential literals, what `allowed_tools` versus `disallowed_tools` versus
  `tools` actually do, turn and budget ceilings, `setting_sources` isolation,
  hook shape (async, three parameters, `hookSpecificOutput`, matcher regex),
  MCP servers and `@tool` schemas, subagents, system prompt and
  `output_format`. Optionally imports the entry point to prove it loads, without
  starting a session. Use when asked to "review / lint / check my agent sdk
  agent", "is this agent safe to run", "why does my hook never fire", "why is my
  agent ignoring allowed_tools", "why is a run so expensive", or before trusting
  an agent you did not write. Don't use for eval case quality (use
  `/agent-sdk:eval-review`), a run that misbehaved (use `/agent-sdk:agent-debug`),
  designing hooks or MCP servers rather than checking them (use
  `/agent-sdk:agent-harness`), or hosting readiness (use `/agent-sdk:agent-deploy`).
argument-hint: "[project-dir]"
allowed-tools: Read, Grep, Glob, AskUserQuestion, Skill, Bash(python3 *)
---

# Review an Agent SDK agent

Static first, because a review that needs the project to run is useless exactly
when you need it most. Nothing here imports the agent unless the user asks for
the load check.

**This skill reports. It does not edit.** Fixes happen after the user has seen
the findings and chosen.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own
directory. Use it verbatim in every command below; a sibling skill's scripts
are at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Review.** Run it before saying anything about the agent:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/lint_agent.py <project>
   ```

   Add `--strict` to fail on warnings (what a CI gate wants), `--json` to
   branch on ids, `--no-path-check` when the agent will run on a different
   machine than this one.

2. **Report** in severity order, leading with the count: "2 errors, 5
   warnings". An error means the SDK rejects it, ignores it, or acts on it in a
   way that makes the run mean something else. A warning runs today and either
   misleads or stops running on a date.

   Name every finding by the id the script printed (`AGT030`, `OPT002`, …),
   with the severity the script gave it and its `Source:` line, so the reader
   can check the claim. Never assign a severity of your own, and never report
   an id the script did not print.

3. **Options.** Typically: fix the errors; pin the model; add ceilings; isolate
   the run with `setting_sources=[]`; move on to the harness or to eval
   coverage. Offer the load check when the static review is clean and the agent
   is reported not to work.

4. **Confirm before editing anything.** If the user wants fixes, make the
   smallest change per finding and re-run the review.

## The ten dimensions

| # | Dimension | What goes wrong |
|---|---|---|
| 1 | entry point | options built inside `main()`, so nothing can obtain them; several modules and no named builder; `query()` with no options |
| 2 | legacy names | `claude_code_sdk`, `ClaudeCodeOptions`, `max_thinking_tokens`, `debug_stderr` |
| 3 | model policy | a hardcoded dated id, a retiring or retired id, or no model at all so the session inherits Claude Code's default |
| 4 | credentials | an `sk-ant-` literal in source; no `.env.example` to say what is needed |
| 5 | tool surface | `allowed_tools` mistaken for a restriction; `tools` never set, so the built-ins are still in context; `"Skill"` instead of `skills`; `permission_mode` never passed, so the CLI picks it (`OPT013`) |
| 6 | ceilings | no `max_turns`, no `max_budget_usd` |
| 7 | context | `setting_sources` unset, so the host machine's settings and `CLAUDE.md` load into every run — measured at 17x the cost |
| 8 | hooks | a synchronous callback, a wrong return shape, an invalid matcher, an event the Python SDK does not have |
| 9 | MCP | an `mcp__` prefix for a server that does not exist, a stdio command not on PATH, an unreadable `@tool` schema |
| 10 | shape | subagents defined but not callable, a minimal system prompt where a persona was intended, an `output_format` the CLI ignores |

## Decision rules

- **`allowed_tools` does not restrict anything.** It pre-approves. Everything
  else stays available and falls through to `permission_mode`. If the user
  wanted a smaller agent, the answer is `tools=[]` or bare names in
  `disallowed_tools`. Say this plainly: it is the single most common
  misunderstanding of the options object.
- **An unset `permission_mode` is not the same as `"default"`.** The CLI
  resolves it: a session that fetches feature flags starts in `default`, but on
  Claude Code 2.1.285–2.1.301 one that fetches none — a gateway or third-party
  provider, telemetry off — could start in `auto`, where broad allow rules such
  as a bare `Bash` are dropped. The docs now say "In Claude Code v2.1.302 or
  later, `claude -p` and Agent SDK runs with no permission mode set start in
  Manual mode" (`default`). Behaviour that depends on the CLI version is
  why `OPT013` stays a warn; the fix is to pass `"dontAsk"` or `"default"`
  explicitly. The plugin's runner forces `"dontAsk"`, but the
  agent also runs outside the runner, so the finding stands either way.
- **Result handling reads `stop_reason` first.** A refusal or a deferred tool
  missing on resume reports `is_error=True` with `subtype="success"`; code that
  treats every `is_error` as an API error to retry is wrong. No lint id checks
  it — read the result-handling code by hand (`references/review-checklist.md`,
  "Read by hand").
- **Options built inside `main()` are a structural finding, not a style note.**
  Until there is a builder, no eval can override anything and this review can
  only see literals. Say what the review could not see.
- **A hardcoded model id is a warning; an unpinned model is also a warning.**
  Env-derived is the answer to both, and the env default is still graded.
- **`setting_sources` unset is about cost and reproducibility, not security.**
  Frame it as: the result depends on whose laptop it ran on. And `[]` is not
  full isolation — builtin plugins and managed MCP still load; that needs
  `strict_mcp_config=True` too.
- **A hook that returns the wrong dict is invisible, not broken.** Nothing
  errors; the decision simply never arrives. That is why `HOK002` is an error.
- **The load check costs an import, not a session.** Offer it when the static
  review is clean, when values were `dynamic`, or mid-migration.
- **Report only.** Do not edit as part of reviewing, even for something obvious.

## References

| Question | File |
|---|---|
| Every finding id: severity, trigger, why, source | [review-checklist.md](references/review-checklist.md) |
| The model policy, and the measured cost of not pinning | [model-policy.md](references/model-policy.md) |
| All 49 options, grouped, with which are overridable and which are deprecated | [options-reference.md](references/options-reference.md) |
| Decoding a failed load, and which interpreter ran it | [load-check.md](references/load-check.md) |

The finding-id bands and the report format live in the router skill:
`${CLAUDE_SKILL_DIR}/../agent-sdk/references/gap-report-format.md`.

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/lint_agent.py <project> [--strict] [--json] [--no-path-check]` | the static review | 0 no errors, 1 errors (or any warning under `--strict`), 2 nothing to review |
| `scripts/load_agent.py <project> [--entry module:function] [--json] [--timeout s]` | imports the entry point and prints the built options; never starts a session | 0 loaded, 1 did not load, 2 no interpreter with the SDK |

## Completion checklist

- [ ] `lint_agent.py` ran and its counts were reported, not summarized from memory.
- [ ] Every error was explained with its consequence, not just its rule.
- [ ] Model findings named the replacement, and said whose clock the date is on.
- [ ] If `allowed_tools` was the finding, the user was told it only pre-approves.
- [ ] If the options are built inside `main()`, the user was told what the review could not see.
- [ ] Nothing was edited without the user asking.
- [ ] If the project has no eval cases, the user was pointed at `/agent-sdk:eval-create`.
