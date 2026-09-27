---
name: eval-create
description: >-
  Writes evaluation cases for a Claude Agent SDK project: one directory per
  case with a prompt.md and the graders its category actually needs. Covers the
  five categories (happy, edge, adversarial, memory, regression) and the n+1
  rule that every refusal in the system prompt needs a case trying to break it;
  turns a reviewed trace into a frozen trajectory case; and lists, renames,
  deletes and de-duplicates the cases already there. Use when the user says
  "write eval cases", "add a test for this behaviour", "cover this rule", "turn
  this trace into a case", "golden trace", "multi-turn case", "adversarial
  case", "my suite only has happy paths", or "clean up the eval directory".
  Don't use to choose or write graders in isolation (use
  `/agent-sdk:eval-criteria`), to validate what is already written (use
  `/agent-sdk:eval-review`), to run anything (use `/agent-sdk:eval-run`), to
  write mocks, personas or fault configs (use `/agent-sdk:eval-simulation`), or
  to set up the evals directory in the first place (use
  `/agent-sdk:agent-create`).
argument-hint: "[project-dir] [--category happy|edge|adversarial|memory|regression]"
allowed-tools: Read, Write, Edit, Grep, Glob, AskUserQuestion, Skill, Bash(python3 *)
---

# Write eval cases for an Agent SDK agent

A case is a claim about the agent, written so a machine can check it twice. The
generator writes the parts nobody remembers — frontmatter keys, the grader
types that suit the category, every required field, a prose body in each grader
saying what it proves and what it does not — and leaves the prompt as a TODO,
because the one thing it cannot know is what this agent is for. Filling that in
is the work, and it is yours.

`${CLAUDE_SKILL_DIR}` is this skill's directory; a sibling skill's scripts are
at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Discover.** What exists, and what the agent's rules are:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/manage_cases.py <project> list
   python3 ${CLAUDE_SKILL_DIR}/../eval-review/scripts/coverage_matrix.py <project>
   ```

   The coverage matrix reads the system prompt's rules and says which have no
   case aimed at them. Start from a gap, not from a blank page.

2. **Report.** Cases by category, the adversarial share against the 20%
   target, the rules with no case, and the refusal rules with no case that
   tries to break them.

3. **Options.** Two to four, each `free`: the highest-value gap first
   (usually an adversarial case for an untested refusal), then the others.
   Say which category and which rule each would cover.

4. **Confirm** with `AskUserQuestion`.

5. **Act.** `--dry-run`, show the plan, then write. Then **fill in the TODOs**
   with Edit — the generated prompt body and any `TODO-tool` placeholder. A
   generated case that is left as generated asserts nothing.

6. **Verify.**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../eval-review/scripts/validate_cases.py <project>
   ```

## What each category gets

| `--category` | Graders written | Why that pair |
|---|---|---|
| `happy` | `trajectory` IN_ORDER + `terminal` | the path and the clean finish; extra calls are not a defect here |
| `edge` | `terminal` + `llm` | a boundary has no single right trajectory, so the expectation is words |
| `adversarial` | `no_tool` + `llm` | the trace proves the restraint, the judge proves the explanation |
| `memory` | `turns` + `tool_order` | context survived when turn two acts on what turn one established |
| `regression` | `terminal` + `regex not_contains` | a regression case names the literal symptom |

## Decision rules

- **One behaviour per case.** A name with "and" in it is two cases. When a case
  fails, its name should be the diagnosis.
- **A refusal rule needs a case that attempts it.** n rules, n cases, plus one
  per refusal. Score it against the trace (`no_tool`, or `trajectory` EXACT) —
  an `llm` grader on the reply grades the apology, and a model that called the
  tool and then apologized passes.
- **Adversarial cases are 20% of a healthy suite.** Happy cases are the easy
  ones to write, so the share decays unless someone watches it.
- **Read a golden trace before freezing it.** Every call becomes a requirement,
  including the redundant lookup and the retry. Delete what you would not
  defend in review.
- **Never overwrite a case from a trace.** `trace_to_case.py` skips an existing
  directory: the old expectation may be right and the new run the regression.
- **A `turns` case has no body.** The body is ignored when `turns` or
  `simulated_user` is set; leaving a prompt there is a prompt that never runs.
- **Write the tool name the model sees.** `mcp__<server>__<tool>`, which is
  what the trace records. A bare name matches by suffix but reports `EVC020`.
- **`delete`, `rename` and `dedupe` need `--yes`.** A case is the record that
  someone once decided this mattered.

## References

| Question | File |
|---|---|
| Which category, and what each proves | [case-taxonomy.md](references/case-taxonomy.md) |
| Every frontmatter key, overrides, isolation | [case-schema.md](references/case-schema.md) |
| Freezing a reviewed run; EXACT vs IN_ORDER; synthetic calls | [golden-traces.md](references/golden-traces.md) |
| Refusal cases, trap mocks, restraint rubrics | [adversarial-cases.md](references/adversarial-cases.md) |
| `turns`, personas, what a session carries | [memory-and-multiturn.md](references/memory-and-multiturn.md) |
| Renaming, deleting, de-duplicating, splitting | [managing-cases.md](references/managing-cases.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/gen_cases.py <project> --category C [--tool T] [--name N] [--rule "text"] [--force] [--dry-run] [--json]` | writes one case directory with the graders its category needs, each with a prose body | 0 written or planned, 1 warnings (placeholder tool, skipped files), 2 usage |
| `scripts/trace_to_case.py <trace> --name N [--project P] [--match EXACT\|IN_ORDER] [--args-match subset\|exact\|ignore] [--dry-run] [--json]` | freezes a reviewed trace into a `trajectory` + `terminal` case; never overwrites | 0 written or planned, 1 case exists or no tool calls, 2 usage |
| `scripts/manage_cases.py <project> list\|rename\|delete\|dedupe [--from A] [--to B] [--yes] [--dry-run] [--json]` | the suite inventory, and the three file operations that are easy to get wrong | 0 done, 1 refused without `--yes` or duplicates found, 2 usage |

## Completion checklist

- [ ] The existing suite and its coverage gaps were reported before anything was written.
- [ ] The chosen case names the rule or behaviour it covers.
- [ ] `--dry-run` was shown and confirmed before writing.
- [ ] Every TODO in the generated prompt and graders was filled in, not left as generated.
- [ ] An adversarial case has a trace-level grader, not only an `llm` one.
- [ ] `validate_cases.py` was run afterwards and its findings shown.
