---
name: agent-create
description: >-
  Makes an existing Claude Agent SDK (Python) project evaluable, and never
  writes the bare app. Reports eval-readiness — entry point present and
  injectable, .env.example, .gitignore covering .env and evals/results/, evals/
  with a config and cases, the runner copy's version, a pytest gate, and
  whether the official agent-sdk-dev plugin is installed — then, on your
  confirmation, copies the eval runner into evals/runner/ and scaffolds
  evals/eval_config.json, a starter case with two free graders, evals/mocks/,
  .env.example and tests/test_evals.py. Use when the user says "set up evals",
  "make my agent testable", "add an eval harness", "install the runner",
  "upgrade the runner copy", "scaffold evals", or asks why their agent cannot
  be evaluated. Don't use to write the agent itself (that is
  `/agent-sdk-dev:new-sdk-app`, or fifteen lines by hand), to write cases (use
  `/agent-sdk:eval-create`), to choose graders (use `/agent-sdk:eval-criteria`),
  to review agent code (use `/agent-sdk:agent-review`), or to generate CI
  workflows (use `/agent-sdk:eval-ci`).
argument-hint: "[project-dir] [--dry-run]"
allowed-tools: Read, Grep, Glob, AskUserQuestion, Skill, Bash(python3 *)
---

# Make an Agent SDK agent evaluable

An agent that works is not an agent you can test. The gap is a seam: options a
second process can obtain, tools that answer the same way twice, a model that
is pinned, and a runner that lives in the repository so a result from six
months ago can be reproduced. This skill builds that seam around an agent that
already exists. It does not write the agent, and it never writes anything
before you have seen the plan.

`${CLAUDE_SKILL_DIR}` is this skill's directory; a sibling skill's scripts are
at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Discover.** Always both, in this order:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../agent-sdk/scripts/discover.py <project> --format md
   python3 ${CLAUDE_SKILL_DIR}/scripts/readiness.py <project>
   ```

   `readiness.py` exits 2 when nothing here is an agent. Stop there and go to
   step 3's handoff row rather than scaffolding evals around nothing.

2. **Report.** Show the `Found` / `Missing` / `Warnings` blocks verbatim. The
   three lines people act on are the entry point (`convention`, `custom`,
   `inline`, `collection`), the runner copy's status, and the credential.

3. **Options.** Offer only what is missing, each `free`:

   | Situation | Offer | Writes |
   |---|---|---|
   | no runner copy (`DEP003`) | install the runner | `evals/runner/agent_sdk_evals/` |
   | copy older than the plugin (`DEP001`) | upgrade, diff first | same |
   | no config or no cases | scaffold the eval suite | `evals/`, `.env.example`, `tests/`, `.gitignore` |
   | both missing | install then scaffold | both of the above |
   | no agent at all (exit 2) | hand off to `/agent-sdk-dev:new-sdk-app`, or fifteen lines by hand | nothing here |

4. **Confirm** with `AskUserQuestion`.

5. **Act.** `--dry-run` first, show the write plan, then the same command
   without it.

6. **Verify.** Not optional; the scaffold is only useful if it parses:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../eval-review/scripts/validate_cases.py <project>
   python3 ${CLAUDE_SKILL_DIR}/../eval-run/scripts/check_runner.py <project>
   ```

   Then hand off: the starter case's prompt is a TODO, and
   `/agent-sdk:eval-create` is what fills the suite in.

## Decision rules

- **Never write the agent.** If `readiness.py` exits 2, this skill's job is to
  say so and name the two ways to get one. Scaffolding evals around a
  non-existent agent produces a config naming an entry point nothing
  implements.
- **`AGT003` is the finding that matters most.** Options built inside `main()`
  cannot be obtained, so no case can pin a model, narrow tools or cap a budget.
  The fix is a three-line extraction; say so rather than working around it.
- **Refuse to replace a runner copy silently.** An existing copy needs
  `--upgrade`, and an upgrade prints the diff — including `DEP004` files edited
  in place — before writing. Someone edited those for a reason.
- **`.gitignore` is merged, never replaced.** The scaffold appends only the
  lines that are missing, under a comment saying who added them.
- **An existing file is skipped unless `--force`.** Report the skips; do not
  pass `--force` on the user's behalf because a file "looked like a stub".
- **The starter case is a TODO on purpose.** Only the author knows what the
  agent does. Its two graders (`terminal`, `regex not_contains`) are true for
  any agent and are meant to be replaced.
- **Say what a run will cost before offering to run one.** Everything this
  skill does is `free`; the first `run`-tier step belongs to
  `/agent-sdk:eval-run`.

## References

| Question | File |
|---|---|
| What makes an agent evaluable at all | [eval-ready-architecture.md](references/eval-ready-architecture.md) |
| `build_options`, `run`, `AGENT_ENTRY`, `module:function` | [entry-point-convention.md](references/entry-point-convention.md) |
| What `/agent-sdk-dev:new-sdk-app` writes, and the soft-reference policy | [new-sdk-app-handoff.md](references/new-sdk-app-handoff.md) |
| `.env`, credentials, cost basis, gitignore | [env-and-secrets.md](references/env-and-secrets.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/readiness.py <project> [--json] [--no-cli] [--no-probe]` | the eval-readiness checklist: entry point, `.env.example`, `evals/`, runner copy, pytest gate, `.gitignore`, `agent-sdk-dev` | 0 ready, 1 findings, 2 no agent here |
| `scripts/eval_scaffold.py <project> [--model M] [--judge-model M] [--force] [--dry-run] [--json]` | writes `evals/eval_config.json`, `evals/smoke/`, `evals/mocks/README.md`, `.env.example`, `tests/test_evals.py`, and merges the `.gitignore` lines | 0 written or planned, 1 warnings to act on, 2 usage |
| `scripts/install_runner.py <project> [--upgrade] [--dry-run] [--json]` | copies `agent_sdk_evals` into `evals/runner/` and writes `MANIFEST.sha256`; refuses an existing copy without `--upgrade`, and shows the diff before an upgrade | 0 installed or planned, 1 refused or local edits replaced, 2 usage |

## Completion checklist

- [ ] `readiness.py` was run and its report shown before anything was offered.
- [ ] The user chose from options that named their writes and their cost tier.
- [ ] `--dry-run` was shown and confirmed before any file was written.
- [ ] The runner copy's version was reported; no copy was replaced without `--upgrade`.
- [ ] `validate_cases.py` and `check_runner.py` were run afterwards and their output shown.
- [ ] The starter case was named as a TODO and handed to `/agent-sdk:eval-create`.
