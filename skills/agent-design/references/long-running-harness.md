# Long-running harnesses

An agent that works for hours does so in **sessions**, and each session starts
with no memory of the last — like engineers working in shifts. *Effective
harnesses for long-running agents* (2025-11-26) found that compaction alone does
not carry a large build across those boundaries. What does is a harness that
leaves the next session a clear, checkable state.

## Two failure modes, and the fix for each

| Failure | What happens | Harness fix (article #8) |
|---|---|---|
| doing too much at once | the session runs out of context mid-feature; the next one finds a half-built, undocumented feature | one feature per session; finish in a clean, committed state |
| declaring victory early | a later session sees progress and decides the job is done | a feature list it must read, with every item failing until tested |
| marking a feature done untested | unit tests or `curl` pass while the feature is broken for a user | end-to-end testing as a user would, with browser automation |
| time lost working out how to run the app | each session rediscovers the dev server | an `init.sh` the first session writes and every later one runs |

## Initializer and coding sessions

Article #8 uses one harness — same system prompt, same tools — and changes only
the first user prompt:

- **Initializer session**: writes `init.sh`, a progress file
  (`claude-progress.txt` in the article), an initial git commit, and a
  **feature list** that expands the spec into individual, testable features,
  each starting as failing. For the article's web-app clone that was over 200
  features.
- **Coding sessions**: one feature at a time; commit with a descriptive
  message; update the progress file; leave code that could be merged.

**Feature list in JSON, not Markdown.** The article found the model less likely
to rewrite or delete entries in a JSON file than in Markdown. Coding sessions
may flip only the `passes` field, and the prompt says plainly that removing or
editing tests is unacceptable.

**Git is the safety net.** A session can read `git log` to see what changed and
revert a bad step.

## The session-start routine

Every coding session begins the same way:

1. Confirm the working directory, and edit only there.
2. Read the git log and the progress file.
3. Read the feature list; pick the highest-priority feature still failing.
4. Run `init.sh`, then a basic end-to-end test **before** new work, and fix
   anything broken first — new work on a broken base makes it worse.

The article's browser tests had blind spots (native alert dialogs were
invisible to its automation), and features behind them were buggier. Know what
your verification cannot see.

## Generator and evaluator

*Harness design for long-running apps* (2026-03-24) adds two findings:

- **Self-evaluation is lenient.** Agents praise their own mediocre work,
  especially on subjective tasks. Separate the generator from the evaluator; a
  standalone evaluator is generous at first, but tuning it to be skeptical was
  far easier than making the generator self-critical. In the article's words,
  "Out of the box, Claude is a poor QA agent" — it found real issues, then
  talked itself into approving.
- **Make subjective quality gradable.** Turn "is it good?" into named criteria
  both agents share, give each a hard threshold, and calibrate the evaluator
  with few-shot examples that carry detailed score breakdowns, which reduced
  score drift.

Its three-agent harness was a **planner** (expands a short prompt into a product
spec, deliberately not into implementation detail), a **generator** (works
feature by feature, git for history) and an **evaluator** (clicks through the
running app and grades against the criteria). Before each sprint the generator
and evaluator agreed a **sprint contract** — what "done" means and how it will
be checked — through files.

**Costs, as the article reports them**: a solo run of its game-maker task took
20 minutes and $9; the full harness took 6 hours and $200, with clearly better
output. A later run of its updated harness on a music app took 3 h 50 min and
$124.70. These are the article's own token costs for its runs, not estimates
for yours.

## Every component is an assumption

The same article's principle: "every component in a harness encodes an
assumption about what the model can't do on its own." Those assumptions go
stale as models improve. When the article's author moved to a newer model, he
removed the sprint structure (the model decomposed work itself), kept the
planner (without it the generator under-scoped), and ran the evaluator once at
the end. The evaluator is worth its cost only when the task sits beyond what
the model does reliably alone.

So:

- **Simplify one component at a time** and measure; cutting several at once
  hides which one was load-bearing.
- **Re-examine the harness when the model changes.** Strip what is no longer
  needed, add what is newly possible.

The model-specific observations in articles #9 and #11 (which model showed
"context anxiety", which did not) are dated; current model facts come from the
platform models overview.

## The session is not the context window

*Scaling Managed Agents with stable interfaces* (2026-04-08) separates three
things one process usually holds: the **session** (an append-only log of
everything that happened), the **harness** (the loop) and the **sandbox** (where
code runs). Compaction, trimming and memory files are irreversible choices
about what to keep; a log kept outside the window lets a harness resume,
rewind or re-read without losing anything. A harness with no state of its own
can crash and restart from the log. Managed Agents is a Claude Platform
service; in the Agent SDK, the transferable parts are:

- keep the transcript outside the process: `session_store`, resume by session
  id (sessions and session-storage docs);
- archive before compaction with a `PreCompact` hook;
- keep credentials out of the sandbox (`/agent-sdk:agent-deploy`).

## Mapping to the Agent SDK

| Need | SDK mechanism |
|---|---|
| end a runaway session | `max_turns` (each turn with tool calls plus one for the final text-only response) and `max_budget_usd` |
| choose when compaction happens | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` in `env` (100,000–1,000,000 tokens); a `compact_boundary` system message marks it |
| rules that survive compaction | `CLAUDE.md` loaded through `setting_sources`, re-injected every request |
| continue a session | resume by session id, or `session_store` for transcripts kept off the host |
| separate evaluator | a second `query()` with its own prompt and read-only tools, or a subagent whose prompt is only to grade |

## In this plugin

- `design_check.py` DSG008 and `design_brief.py`'s long-running checklist.
- `/agent-sdk:agent-debug` (`failure-shapes.md`, `## stall`) diagnoses a run
  that stopped early or looped.
- `/agent-sdk:eval-criteria` for an `llm` grader as the separate evaluator;
  `/agent-sdk:agent-deploy` for hosting, session storage and sandboxing.

Sources: https://www.anthropic.com/research/effective-harnesses-for-long-running-agents ("Effective harnesses for long-running agents", 2025-11-26, initializer and coding sessions, JSON feature list, progress file, git, one feature per session, session-start routine, end-to-end testing, the failure-mode table); https://www.anthropic.com/research/harness-design-long-running-apps ("Harness design for long-running apps", 2026-03-24, generator/evaluator split, gradable criteria, few-shot calibration, sprint contract, harness components as assumptions, reported costs and times); https://www.anthropic.com/research/managed-agents ("Scaling Managed Agents with stable interfaces", 2026-04-08, the session log outside the context window, a stateless harness); https://code.claude.com/docs/en/agent-sdk/agent-loop (read 2026-10-29, turns and budget, automatic compaction, `PreCompact`); https://code.claude.com/docs/en/env-vars (read 2026-10-29, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`); https://code.claude.com/docs/en/agent-sdk/sessions (read 2026-10-29, resume); https://code.claude.com/docs/en/agent-sdk/session-storage (read 2026-10-29, `session_store`). Written 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
