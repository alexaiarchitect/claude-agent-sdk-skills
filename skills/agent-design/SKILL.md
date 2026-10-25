---
name: agent-design
description: >-
  Design review and advice for a Claude Agent SDK (Python) agent, grounded in
  Anthropic's published guidance on building agents: the gather-context /
  take-action / verify loop, context engineering, tool design, whether a
  subagent is warranted at all, and long-running harness patterns. Runs
  `design_check.py` and `design_brief.py` over the agent's source and reports
  `DSG0xx` findings — tool descriptions, ambiguous parameters, list tools with
  no limit, missing namespaces, overlapping tools, too many tool definitions,
  underspecified subagents, unbounded runs — each with the article and the
  docs page it cites. Writes nothing unless asked. Use when asked "is my tool
  set well designed", "too many tools", "should this be a subagent", "fold my
  subagents", "my agent runs out of context", "how do I make it run for hours",
  "design review", or "which pattern should I use". Don't use for wiring checks
  of hooks, permissions and MCP servers (use `/agent-sdk:agent-harness`), a
  static lint of the code (use `/agent-sdk:agent-review`), a run that
  misbehaved (use `/agent-sdk:agent-debug`), hosting (use
  `/agent-sdk:agent-deploy`), or writing the app itself (use
  `/agent-sdk-dev:new-sdk-app`).
argument-hint: "[project-dir]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, Bash(python3 *)
---

# Agent design: loop, context, tools, subagents, long runs

The wiring skills answer "does this work as written". This one answers "is it
shaped the way the model needs": what the model is shown about each tool, how
many it has to choose between, what a subagent is told to bring back, and what
carries a run past one context window. Those choices fail as quality, not as
errors — a model that picks the wrong one of two near-identical tools raises
nothing.

The guidance comes from Anthropic's articles on building agents (cited by
title and date in every finding) and the current mechanics from the
`code.claude.com` docs. Where they differ, the docs win.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own
directory. Use it verbatim in every command below.

## Flow

1. **Find the agent.** Use the project directory the user named, else the
   current one. The scripts find the entry point the way every skill here
   does (`build_options()` in `agent.py`, else any module that builds
   `ClaudeAgentOptions`); pass one module's path to review it alone.

2. **Check.**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/design_check.py <project>
   ```

   `--json` to branch on ids. Exit 2 means nothing was checked (no SDK usage,
   or source that does not parse): say so and stop.

3. **Brief.**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/design_brief.py <project>
   ```

   It lays the same facts out as the five questions below: the tool table,
   the keep-or-fold table per subagent, the verification ladder against this
   plugin's graders, and the long-running checklist with `yes`/`no`/`ask`.

4. **Report** in the format below. Answer the user's question first; then the
   findings that bear on it; then the rest briefly.

5. **Offer next steps; write nothing.** This skill is report-only by default.
   If the user wants a change, name the generator that makes it — and let
   that skill show its write plan:
   `/agent-sdk:agent-harness` (`gen_subagent.py`, `gen_hook.py`) for a
   subagent definition or a budget/`PreCompact` hook,
   `/agent-sdk:eval-create` for the task-completion evals a fold needs,
   `/agent-sdk:agent-create` for the eval-ready layout. Edit the agent's own
   source only when asked, after showing the diff as a plan and getting a yes.

## Reporting a finding

Name every finding by the id the script printed (`DSG001` … `DSG008`), with
its severity, its locator (`agent.py line 74`) and its `Source:` line — the
article and the docs page. Never assign a severity of your own and never
report an id the script did not print. A design opinion of your own is fine,
but label it as one and keep it apart from the findings.

The thresholds are heuristics from the articles, not SDK limits. Say that a
finding is a question for the evals to settle, not a defect to fix blindly.

## The five design questions

1. **Loop and verification.** Is this an agent or a workflow — can the steps
   be predicted? What stops it (`max_turns`, counting each turn with tool calls
   plus one for the final text-only response; `max_budget_usd`)? How does it
   learn it is wrong — rules first, then visual feedback, then an LLM judge?
   → [agent-loop.md](references/agent-loop.md)
2. **Context.** Is the system prompt at the right altitude, minimal, grown from
   observed failures? Does the agent fetch context just in time? What carries
   across compaction (`CLAUDE.md` through `setting_sources`, notes in files)?
   → [context-engineering.md](references/context-engineering.md)
3. **Tools.** Does each tool have a distinct purpose, a description a new hire
   could act on, unambiguous parameters, bounded output, actionable errors, a
   namespace? Are there fewer than ~30 to choose from?
   (DSG001–DSG006) → [tool-design.md](references/tool-design.md)
4. **Subagents.** Is each one split by context (parallel, fresh, disposable
   windows; compact result) rather than by problem type? If not, fold it — one
   at a time, against evals — and keep it only if the folded version scores
   worse. If kept: objective, output format, tool guidance, boundaries.
   (DSG007) → [subagent-decisions.md](references/subagent-decisions.md)
5. **Long runs.** Does work span sessions? Then: init script, JSON feature
   list, progress file, one feature per session, git checkpoints, an
   end-to-end check at session start, and an evaluator separate from the
   generator. (DSG008) → [long-running-harness.md](references/long-running-harness.md)

## Decision rules

- **Default to one loop.** A single agent with skills and good tools often
  beats a subagent design; a subagent earns its place with a context-based
  reason, not an org-chart one.
- **Split by context, never by problem type.** "The search reads hundreds of
  results the parent never needs, in parallel" is a reason; "search is a
  separate concern" is not.
- **Search over list.** A tool that returns everything will one day return
  more than 25,000 tokens; the SDK then saves it to a file and the agent has
  to recover.
- **Simplest thing that works.** Add a harness component only when an eval
  shows the model needs it, and re-examine each one when the model changes.
- **Report, don't rewrite.** The user asked a design question; the answer is
  an explanation and a choice, not a diff.

## Report format

```
## Design review: <project>
**Answer:** <one paragraph answering the user's question>
### Findings (from design_check.py)
- `DSG005` warn — agent.py line 74 — `lookup`, `find_book`, `search_books` overlap
  Source: <article, date>; <docs URL>
### Subagents: keep or fold
<per subagent: the decision, the context-based reason, the fold steps if folding>
### Next steps (nothing was written)
1. <generator or skill, what it would write, cost: free>
```

## References

| Question | File |
|---|---|
| Gather/act/verify, workflows against agents, the five patterns in SDK terms, the verification ladder | [agent-loop.md](references/agent-loop.md) |
| Right-altitude prompts, just-in-time retrieval, compaction, note-taking, skills, code execution | [context-engineering.md](references/context-engineering.md) |
| Each DSG tool rule and why, `response_format`, output limits, `@tool` annotations, eval-driven iteration | [tool-design.md](references/tool-design.md) |
| Keep or fold, the fold procedure, delegation rules, background/fork/caps facts | [subagent-decisions.md](references/subagent-decisions.md) |
| Initializer and coding sessions, feature list, progress file, generator/evaluator, the session log | [long-running-harness.md](references/long-running-harness.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/design_check.py <project> [--json] [--strict]` | reports `DSG001`–`DSG008` with article and docs sources | 0 no warnings, 1 warnings (under `--strict`, any finding), 2 nothing to check |
| `scripts/design_brief.py <project> [--json]` | prints the tool table, keep-or-fold tables, verification ladder and long-running checklist | 0 printed, 2 nothing to brief |

Both are free: they read source and file names, never run the agent, never
write.

## Completion checklist

- [ ] `design_check.py` ran, and every finding was reported by its id, severity, locator and `Source:` line.
- [ ] `design_brief.py` ran, and its tables were used for the subagent and long-running answers.
- [ ] The user's own question was answered first, in plain words.
- [ ] Every keep-or-fold decision gave a context-based reason (parallel, fresh, disposable windows; compact result), not a problem-type one.
- [ ] At least one Anthropic article and the matching `code.claude.com` page were cited.
- [ ] Nothing was written; changes were offered as next steps naming the skill or generator that would make them.
