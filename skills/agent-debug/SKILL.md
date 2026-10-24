---
name: agent-debug
description: >-
  Triages a misbehaving or flaky Claude Agent SDK agent from evidence: a runner
  trace, an imported Claude Code session file, or a results directory. Names
  the failure shape (loop, oscillation, stall, unknown tool, error cascade, a
  ceiling that fired), finds the first divergence from the case's expected
  trajectory, assigns the layer the fix belongs to (prompt, tool, options,
  budget, quota, the eval itself), separates deterministic from flaky with
  repeated runs, and closes the loop with a regression case. Use when asked
  "why is it looping", "it stalls", "it called the wrong tool", "the eval is
  flaky", "it did the wrong thing yesterday", "explain this session", or "find
  where it went wrong". Don't use to read a whole results directory for scores
  and reliability (use `/agent-sdk:eval-analyze`), to review code statically
  (use `/agent-sdk:agent-review`), or to write the regression case itself (use
  `/agent-sdk:eval-create`).
argument-hint: "[--trace file | --session file | --results dir] [--case-dir dir]"
allowed-tools: Read, Grep, Glob, Write, AskUserQuestion, Skill, Bash(python3 *)
---

# Debug an Agent SDK agent

A symptom is not a layer. The same "it reserved the wrong book" comes from a
prompt with no ordering rule, a tool whose error text says nothing, a mock
named differently from the real server, or a denied permission the agent never
saw. Triage is deciding which, from a trace, before touching anything. Nothing
here starts a session without asking; the evidence usually already exists.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own
directory. Use it verbatim in every command below; a sibling skill's scripts
are at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Rule out the evaluation** (free). A case that failed only after a grader
   change is a grader problem: `../eval-review/scripts/validate_cases.py`.

2. **Read what already exists** (free):

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/analyze_trace.py --trace evals/results/<ts>/<case>.1.trace.jsonl --case-dir evals/<case>
   python3 ${CLAUDE_SKILL_DIR}/scripts/analyze_trace.py --results evals/results/<ts>
   python3 ${CLAUDE_SKILL_DIR}/scripts/import_session.py <session-id> --cwd <project>
   ```

3. **Report** the calls in order, the signatures with their layer, the first
   divergence, how the run ended, the rate-limit state and the cost with its
   basis. Say what the evidence cannot show (an imported session has no cost).

4. **Options and confirm.** Each with its spend: capture a fresh trace
   (`../eval-run/scripts/run_evals.py --case <name> --runs 1`, one session), or
   establish deterministic versus flaky (`--runs 5`, five sessions). Ask with
   `AskUserQuestion` and wait; nothing below runs before the answer.

5. **Close the loop.** Fix in the named layer, pin the failing trace as a
   regression case (`../eval-create/scripts/trace_to_case.py`), re-run that
   case, then the `pr` tier.

## Failure shapes

| Shape | Evidence | Layer |
|---|---|---|
| loop | same tool, same arguments, three or more times running | tool result text; a stop rule in the prompt |
| oscillation | A, B, A, B | tool results that disagree; which to trust |
| stall | no tool call and no final text; often `permission_denials` on the result | options and permissions |
| unknown_tool | a call to a name the session did not have | MCP wiring; a mock named differently |
| error_cascade | consecutive error results (`is_error` truthy; `null` on success) | tool error text; "on error" rule in the prompt |
| max_turns / max_budget | a ceiling fired; the answer proves nothing | find the loop before raising the cap |
| refusal / tool_deferred | `is_error` on `subtype` success with `stop_reason` `refusal` / `tool_deferred_unavailable`; not an API error | the request or prompt / the resume's tool set |

Full descriptions and fixes: [failure-shapes.md](references/failure-shapes.md).
The layer table by evidence: [triage.md](references/triage.md).

## Decision rules

- **Read the first divergence, not the last symptom.** An early argument
  mismatch followed by correct-looking calls is a cascade; fixing the last call
  fixes nothing.
- **One failing run is one sample.** Deterministic or flaky is established by
  five runs, and the user approves those runs first.
- **A capped run is inconclusive, not wrong.** `max_turns` is not a hard cap on
  the turn count; read `terminal_reason`.
- **Quota is not a bug.** A `rejected` rate limit or a 429 means wait for
  `resets_at`; there is nothing to fix in the agent.
- **Imported evidence has no cost.** Say so; run the case under the runner
  when the budget matters.
- **Pin the fix as a case.** A fix without a regression case is undone by the
  next prompt edit.

## References

| Question | File |
|---|---|
| From a symptom to a layer, step by step | [triage.md](references/triage.md) |
| Every failure shape, what causes it, what fixes it | [failure-shapes.md](references/failure-shapes.md) |
| What a trace holds and what a session file lacks | [evidence.md](references/evidence.md) |
| Finding, importing and redacting session files | [session-files.md](references/session-files.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/analyze_trace.py --trace F \| --session F \| --results D [--case-dir D] [--case N] [--json]` | calls, signatures with layer, divergence, terminal, rate limit, cost | 0 nothing found, 1 signatures or divergence, 2 unreadable |
| `scripts/import_session.py <id \| path> [--cwd D] [--out D] [--json]` | converts a Claude Code session file to a trace | 0 written, 1 unconvertible, 2 not found |

## Completion checklist

- [ ] The trace or session was analyzed by the script, and its output shown, before any diagnosis.
- [ ] Every signature was reported with the layer it belongs to.
- [ ] The first divergence was named when the case has a trajectory grader, or its absence noted.
- [ ] No session was started without the user's confirmation and its spend stated.
- [ ] The fix was pinned as a regression case, or the user was pointed at `/agent-sdk:eval-create`.
