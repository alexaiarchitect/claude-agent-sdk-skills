---
name: eval-simulation
description: >-
  Builds the three levers that let a Claude Agent SDK eval suite test what a
  plain prompt cannot: mocked MCP tools (evals/mocks/<server>/<tool>.md, derived
  from the agent's own @tool schemas), simulated users (a persona JSON with
  behaviour instructions and violation rubrics that judge the simulator, not the
  agent), and hook-based fault injection (deny, rewritten input, replaced
  output, latency, seeded probability). Validates every mock, persona and faults
  file against the loaders the runner actually uses, and says what each lever
  costs before anything runs. Use when asked to "mock the MCP server", "test a
  multi-turn conversation", "simulate an impatient user", "test what happens
  when the tool fails", "add latency", "inject a fault", or "why did my persona
  case pass". Don't use to write ordinary cases (use `/agent-sdk:eval-create`),
  to choose graders or rubrics (use `/agent-sdk:eval-criteria`), to validate a
  whole suite (use `/agent-sdk:eval-review`), or to run anything (use
  `/agent-sdk:eval-run`).
argument-hint: "[project-dir] [--mocks | --persona NAME | --faults TOOL]"
allowed-tools: Read, Grep, Glob, Write, AskUserQuestion, Skill, Bash(python3 *)
---

# Simulate users, tools and failures

Three levers, and they do not cost the same.

| Lever | What it tests | Cost to run | Written to |
|---|---|---|---|
| **Mock MCP server** | behaviour against a deterministic backend, including one that would say yes | free — no model calls, the handler is in-process | `evals/mocks/<server>/<tool>.md` |
| **Fault injection** | recovery when a tool is denied, slow or wrong | free — hooks, no model calls; the agent may spend extra turns | `evals/faults/<name>.json` |
| **Simulated user** | a conversation nobody scripted | **judge-tier call per user turn**, plus one per violation rubric, plus the agent's session | `evals/personas/<name>.json` |

So mocks and faults are free to write and free to run; a simulated user is the
only lever here that spends. Say the arithmetic before offering it.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own directory.
Use it verbatim; a sibling skill's scripts are at
`${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Discover** (free). What the agent exposes, and what the suite already has:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../agent-sdk/scripts/discover.py <project>
   python3 ${CLAUDE_SKILL_DIR}/scripts/validate_sim.py <project>
   ```

2. **Report.** The agent's MCP servers and tools, which of them have mocks,
   which personas and faults files exist and whether any case references them,
   and every `SIM`/`MCP020` finding with its fix. Name the gaps as gaps.

3. **Options, with cost.** Offer them cheapest first: mocks (free), a faults
   case (free), a simulated-user case (judge calls per turn — state the number).
   Ask with `AskUserQuestion` and wait.

4. **Generate.** `--dry-run` first, always, then write. "Always" includes the
   case where the user has **already approved writing**: the dry run's write
   plan is the record of what is about to change, so pre-approval skips the
   *confirmation*, not the dry run. Every lever is generated — a persona by
   `gen_persona.py`, mocks by `gen_mocks.py`, faults by `gen_faults.py` — never
   hand-written, because the generators are what know the exact JSON shapes
   `simulate.Persona` and `faults.load_plan` load:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/gen_mocks.py <project> --from-agent --dry-run
   python3 ${CLAUDE_SKILL_DIR}/scripts/gen_persona.py <project> --name impatient \
     --behaviour "Never volunteer your member id." \
     --violation "the user never states a member id unless asked twice" --dry-run
   python3 ${CLAUDE_SKILL_DIR}/scripts/gen_faults.py <project> \
     --tool mcp__library__lookup_book --error "catalog service timed out" --dry-run
   ```

   Nothing is overwritten without `--force`.

5. **Wire and validate.** Add `mocks:`, `simulated_user:` or `faults:` to the
   case that uses it, then re-run `validate_sim.py <project> --strict`. Hand
   grader choices to `/agent-sdk:eval-criteria` and the run to
   `/agent-sdk:eval-run`.

6. **Say what wrote what.** In the answer, name the generator behind each file
   and quote a line of its plan — "`gen_persona.py` planned **create**
   `evals/personas/<name>.json`", "`gen_mocks.py` reported all three mocks as
   **skip**, they already exist" — never "I wrote the persona", which reads as
   a hand-written file. Then show the validator's output as it printed it: its
   findings **by id** (`SIM…`, `EVC…`, `MCP…`) with the `Fix:` it gave, and its
   `_Summary: N error(s), M warning(s), K note(s)._` line, unfiltered. "Both validators pass"
   with the output piped through `grep` is not a report; a note that was
   printed and not shown is the one the reader needed. Keep the credential line
   the way the scripts gave it, `none found` included, and when the user has
   said they are on a subscription, say that the figures are therefore
   estimates rather than claiming a cost basis no script reported.

## Decision rules

- **A mock must advertise a schema.** Input is validated against it *before* the
  handler runs, so a missing or drifted schema turns every call into an error
  result the mock never sees. Derive it from the agent's `@tool` with
  `gen_mocks.py --from-agent`; never hand-write one against a tool you have not
  read.
- **A mock speaks text.** Only `text` and `image` content survives intact;
  `resource_link` and text `resource` are flattened, binary and unknown types
  are dropped with a warning. A mock that returns them returns nothing.
- **A simulated-user case cannot use a `trajectory` grader** (`EVC040`, refused
  by the runner). The persona chooses what to ask, so the tool sequence is not
  reproducible and the case would flake with no change to the agent. Assert on
  a *set* (`tool_used`, `no_tool`), on the final answer (`llm`, `final_text`),
  or on the conversation itself (`llm` with `target: simulated_user`). If the
  sequence is the point, the case wants `turns:` and a script, not a persona.
- **Violation rubrics judge the simulated user, not the agent.** They catch a
  simulator that drifted off character; a violation makes the case
  NOT_EVALUATED, not FAILED. Assertions about the agent go in `graders/`. A
  persona with no rubrics is refused (`SIM001`).
- **Faults default to `probability: 1.0`, in a dedicated case, never the happy
  path.** A gate that fires a fault nine times in ten is a coin flip; a fault
  mixed into the happy path makes green mean two things. Sub-1.0 probabilities
  belong in a nightly soak with several runs.
- **Assert that the fault fired.** A `hook_event` grader naming the fault's
  `id`. Without it, a matcher typo means the fault never matched, the run was
  ordinary, and the case passed proving nothing.
- **Keep simulated suites in their own tier.** One persona case with four turns
  and three rubrics is seven judge-tier calls before its own graders. That does
  not belong in the per-PR gate.
- **A trap mock answers favourably.** The point is to make the wrong action
  *available* — the refusal must come from the agent's judgement, not from a
  backend that said no.

## References

| Question | File |
|---|---|
| How the runner drives a persona, and what it costs per turn | [user-simulation.md](references/user-simulation.md) |
| The persona file shape, behaviour instructions, rubrics, worked examples | [personas.md](references/personas.md) |
| Mock file format, substitutions, `expect`, trap mocks, `mock_calls` | [mock-servers.md](references/mock-servers.md) |
| The faults file, deny vs. updatedInput vs. updatedToolOutput, seeded probability | [fault-injection.md](references/fault-injection.md) |

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/gen_mocks.py <project> [--server N] [--tool N] [--from-agent] [--out D] [--force] [--dry-run] [--json]` | one mock per in-process `@tool` from its declared schema; a TODO stub per external server | 0 written or planned, 1 nothing to generate, 2 usage |
| `scripts/gen_persona.py <project> --name N [--goal T] [--style T] [--opening T] [--behaviour T]... [--violation T]... [--max-turns N] [--stop-marker M] [--model M] [--out P] [--force] [--dry-run] [--json]` | a persona in the exact shape `simulate.Persona` loads | 0 written or planned, 1 nothing written, 2 usage incl. no `--violation` (`SIM001`) |
| `scripts/gen_faults.py <project> --tool N [--error T] [--latency-ms N] [--probability P] [--seed N] [--id I] [--out P] [--force] [--dry-run] [--json]` | a faults file in the exact shape `faults.load_plan` reads | 0 written or planned, 1 nothing written, 2 usage incl. `SIM002`, `SIM021` |
| `scripts/validate_sim.py <project> [--strict] [--json]` | every mock, persona, faults file and the cases that reference them | 0 clean, 1 findings, 2 no project or no `evals/` |

`SIM001` no violation rubrics · `SIM002` bad probability or action · `SIM003`
`constraints` not a list of strings · `SIM004` persona key the runner ignores ·
`SIM005` `max_user_turns` below 1 · `SIM006` retired/retiring persona model ·
`SIM010`–`SIM013` mock schema, `error` with a body, `latency_ms`, `type` ·
`SIM020` fault names an unknown tool · `SIM021` fault injects nothing ·
`SIM030`–`SIM032` a case pointing at a missing mock server, persona or faults
file · `MCP020` mock for a server the agent no longer has.

## Completion checklist

- [ ] `validate_sim.py` was run and its findings shown before anything was generated.
- [ ] Every generator was run with `--dry-run` first, and the plan shown.
- [ ] The cost of each offered lever was stated: free for mocks and faults, judge calls per turn for a persona.
- [ ] Every mock advertises a schema derived from the agent's own `@tool`.
- [ ] Every persona carries violation rubrics that judge the *user*, and no simulated case carries a `trajectory` grader.
- [ ] Every faults file is referenced by a dedicated case with a `hook_event` grader naming its `fault_id`.
- [ ] `validate_sim.py --strict` was re-run after writing, and the suite handed to `/agent-sdk:eval-run`.
