---
name: eval-review
description: >-
  Validates a Claude Agent SDK project's eval suite without running it, and
  says what it does not cover. Parses every case and grader, checks the
  frontmatter and every grader's required fields, cross-checks grader tool
  names against the agent's real tools and the mocks, validates
  evals/eval_config.json against the installed runner copy, builds a matrix of
  the system prompt's rules against the cases aimed at them, and reports the
  n+1 gaps — refusal rules with no case that tries to break them. Use when the
  user says "check my eval cases", "is this suite any good", "what am I not
  testing", "why does this case always pass", "coverage", "my grader names the
  wrong tool", or before committing a suite or trusting a green run. Don't use
  to write cases (use `/agent-sdk:eval-create`), to write graders or the config
  (use `/agent-sdk:eval-criteria`), to run anything (use `/agent-sdk:eval-run`),
  or to interpret results that already exist (use `/agent-sdk:eval-analyze`).
argument-hint: "[project-dir] [--strict]"
allowed-tools: Read, Grep, Glob, AskUserQuestion, Skill, Bash(python3 *)
---

# Review an eval suite before it costs anything

A green suite is only evidence if its graders could have gone red. This skill
reads the suite without running it and reports two different things: what is
**wrong** (findings, with stable ids) and what is **missing** (gaps, which are
advice). Nothing here spends a token, and everything here is a problem a run
would otherwise find expensively.

`${CLAUDE_SKILL_DIR}` is this skill's directory; a sibling skill's scripts are
at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Discover.** All three, in this order — validity, consistency, coverage:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/validate_cases.py <project>
   python3 ${CLAUDE_SKILL_DIR}/scripts/crosscheck_tools.py <project>
   python3 ${CLAUDE_SKILL_DIR}/scripts/coverage_matrix.py <project>
   ```

   There is no point discussing which rule needs a case while a grader in the
   suite asserts nothing.

2. **Report.** Findings by id and severity, then gaps. Say plainly when a check
   was **skipped** rather than passed — the tool cross-check is skipped when
   the agent's tools cannot be read statically, and the rule matrix is empty
   when the system prompt is built at runtime. Both are "not measured", not
   "clean".

   An `overrides` error (`EVC003`) is not a silent no-op: the runner validates
   every case's `overrides` against `ClaudeAgentOptions` and refuses the whole
   run before a single session starts, so the typo costs nothing but it also
   means nothing runs until it is fixed. Say that, and offer the validator's
   own `Fix:` rather than applying it.

3. **Options.** Fix in order: load errors, contract errors, silent-pass
   warnings, then everything else. Route the writing: cases to
   `/agent-sdk:eval-create`, graders and config to `/agent-sdk:eval-criteria`.

4. **Confirm** with `AskUserQuestion` before handing off.

5. **Verify.** Re-run `validate_cases.py` after the fixes and show the diff in
   the finding list.

## What each script answers

| Question | Script | Gate |
|---|---|---|
| do the files parse and mean what they say? | `validate_cases.py` | exit 1 on errors; `--strict` adds warnings |
| do the graders, the agent and the mocks agree on tool names? | `crosscheck_tools.py` | exit 1 on any mismatch |
| which rules has nobody written a case for? | `coverage_matrix.py` | exit 0 with gaps; `--strict` to gate |

## Decision rules

- **Never invent a tool list.** When the agent's tools cannot be read from the
  AST, `EVC020` is skipped and the report says so. An empty set would report
  every grader as naming an unknown tool.
- **Findings are wrong; gaps are missing.** A finding names a defect with an
  id. A gap is a judgement about coverage made by a text heuristic — offer it,
  do not assert it.
- **The silent-pass warnings come first.** `EVC020`, `EVC041` and `EVC060` are
  what make a green suite meaningless; a missing `category` can wait.
- **An uncovered rule may be covered.** The matrix matches on tools and
  phrases. Show the row's evidence and let the user disagree.
- **`unknown` is not `0`.** A runtime-built system prompt yields no rules;
  reporting "0 of 0 covered" as a pass would be the worst possible answer.
- **`--strict` belongs in CI, not in conversation.** A grader that quietly
  asserts nothing is worse than a red build; a coverage gap is not.
- **A restraint case needs a trace-level grader.** `no_tool`, `trajectory`
  EXACT, or `tool_used` with `max: 0`. An `llm` grader reads the apology.

## References

| Question | File |
|---|---|
| Every `EVC`/`CFG`/`MCP`/`DEP` id: severity, trigger, why | [validation-rules.md](references/validation-rules.md) |
| How rules are extracted and matched; shape; n+1 | [coverage-matrix.md](references/coverage-matrix.md) |
| Grader names vs agent tools vs mocks; the alias and prefix rules | [tool-crosscheck.md](references/tool-crosscheck.md) |
| The questions validation cannot answer | [quality-review.md](references/quality-review.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/validate_cases.py <project\|evals-dir> [--agent-dir D] [--strict] [--json]` | every case, every grader, the mocks and the config, against the installed runner copy | 0 clean, 1 findings (warnings too under `--strict`), 2 nothing to validate |
| `scripts/coverage_matrix.py <project> [--agent-dir D] [--strict] [--json]` | system-prompt rules against cases, suite shape, n+1 gaps, tool coverage | 0 reported, 1 gaps under `--strict`, 2 nothing to analyse |
| `scripts/crosscheck_tools.py <project> [--agent-dir D] [--strict] [--json]` | grader tool names vs the agent's tools vs the mocks; `Task`/`Agent`, `mcp__` prefixes, orphan mocks | 0 consistent, 1 mismatches, 2 the tool list could not be read |

## Completion checklist

- [ ] All three scripts were run and their output shown, not summarized from memory.
- [ ] Any skipped check was reported as skipped, with the reason.
- [ ] Findings were ordered: load errors, contract errors, silent-pass warnings, then the rest.
- [ ] Gaps were offered as advice, with the evidence the heuristic matched on.
- [ ] Writing work was handed to `/agent-sdk:eval-create` or `/agent-sdk:eval-criteria`.
- [ ] `validate_cases.py` was re-run after the fixes.
