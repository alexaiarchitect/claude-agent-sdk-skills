# Fault injection: breaking a tool on purpose, reproducibly

Every suite measures the happy path. Almost none measures what the agent does
when a tool is denied, slow, or returns something wrong — which is the path
production spends most of its incidents on. Faults are hooks, so like mocks they
cost nothing at run time: no extra model calls, only whatever turns the agent
spends recovering.

## The file

A case opts in with `faults: faults/<name>.json`, resolved against the case
directory first, then `evals/`.

```json
{
  "seed": 20260930,
  "faults": [
    {"id": "deny-writes", "event": "PreToolUse", "tool": "Write",
     "action": "deny", "probability": 1.0, "reason": "disk full"},
    {"id": "slow-lookup", "event": "PreToolUse", "tool": "mcp__library__.*",
     "action": "latency", "latency_ms": 1500},
    {"id": "garbled", "event": "PostToolUse", "tool": "Read",
     "action": "error_output", "updated_tool_output": "<unreadable>",
     "reason": "the file came back truncated"}
  ]
}
```

| Key | Meaning |
|---|---|
| `seed` | RNG seed; the runner adds the run index, so run 2 is a different but repeatable draw |
| `id` | the name a `hook_event` grader asserts on; defaults to `fault-<n>` |
| `event` | one of the Python SDK's ten hook events (`HOK020` otherwise) |
| `tool` | a regex **fullmatched** against the tool name; defaults to `.*`; an invalid regex falls back to an exact comparison |
| `action` | `deny`, `updated_input`, `error_output`, `latency`, `allow` (`SIM002` otherwise) |
| `probability` | share of matching calls hit, in `[0, 1]` (`SIM002` otherwise) |
| `reason` | the text the model reads on a denial; `additionalContext` on `error_output` |
| `updated_input` | the rewritten arguments, for `updated_input` |
| `updated_tool_output` | the substituted result, for `error_output` |
| `latency_ms` | slept before the action is applied, whatever the action |

## The three shapes, and which one you actually want

**`PreToolUse` deny with a reason.** Returns
`permissionDecision: "deny"` plus `permissionDecisionReason`. The tool never
runs; the agent is told no, and the reason is the only thing it can act on. A
denial with no reason is the classic cause of an agent retrying the same call
until `max_turns` — which is why an entry with `action: deny` and no `reason`
is `SIM021`. This is the fault to reach for when the question is "does the agent
have a fallback, and does it tell the user".

**`PreToolUse` `updatedInput`.** Returns `permissionDecision: "allow"` with
`updatedInput`. The call runs, with arguments the agent did not choose. Use it
to simulate a corrected or sanitised request, or an upstream that rewrites.
Harder to assert on than a denial, because the agent may never notice.

**`PostToolUse` `updatedToolOutput`.** The tool runs; its result is replaced.
One caveat decides whether this works: `updatedToolOutput` **must match the
tool's own output schema**, or the CLI rejects it and keeps the original — and
the mismatch is silent. So a case asserting on injected output should also
assert that the agent *noticed* it, otherwise a rejected substitution looks
exactly like a passing test.

**Latency.** `latency_ms` sleeps before the action is applied, for any action;
`action: latency` sleeps and then allows. On `PreToolUse` this delays the call;
on `PostToolUse` it delays the result reaching the model. Use it against a
`timeout_seconds` on the case, or against the agent's own `max_turns`, to see
what a slow backend does to a conversation.

## Probability lives inside the callback

`HookMatcher` has exactly three fields — `matcher`, `hooks`, `timeout`. There is
**no** `probability`. So per-tool probability is implemented inside the callback,
drawn from one `random.Random(seed + run)` created per run:

```python
if fault.probability < 1.0 and rng.random() >= fault.probability:
    continue
```

That is the whole reason `seed` is a top-level key. A flakiness test whose draws
cannot be replayed produces a bug report nobody can reproduce; with the seed and
the run index, the exact sequence of hits comes back.

Two more consequences of the hook mechanism:

- Matchers on the same event are dispatched **concurrently**, not in sequence,
  so no fault may depend on another fault having run first. The runner therefore
  installs one callback per event and walks the entries itself, in file order.
- The capture hook that feeds the trace is the same mechanism. A `PreToolUse`
  hook returning *allow* sees every tool call, whereas `can_use_tool` fires only
  when the CLI's rules evaluate to "ask" — under `allowed_tools` or
  `permission_mode="dontAsk"`, never. `include_hook_events=True` on its own
  emits nothing without a registered hook.

## What a fault run proves, and what it does not

It proves the agent's **recovery behaviour**: that it retried once and then
said so, that it did not loop, that it told the user which step failed, that it
did not invent a result. It does not prove the agent is correct — the happy-path
cases do that — and it must never be mixed into one. A fault in the happy path
makes a green suite mean two different things.

Rules that keep fault cases honest:

- **`probability: 1.0` in anything that gates a merge.** A dedicated case asserts
  one specific failure; a probability below 1 turns the gate into a coin flip.
  Sub-1.0 probabilities belong in a soak or nightly run, with several runs and
  pass@k.
- **One faults file per failure mode**, named after it, and one entry per tool.
- **Assert the fault fired.** A `hook_event` grader naming the fault's `id`:

  ```markdown
  ---
  type: hook_event
  event: PreToolUse
  fault_id: slow-lookup
  ---
  ```

  Without it, a typo in `tool` means the fault never matched, the agent had an
  ordinary good run, and the case passed — proving nothing. `validate_sim.py`
  warns (`SIM020`) when a plain tool name matches nothing in the project, but a
  regex it cannot evaluate is only caught by the grader.
- **Pair it with a terminal or budget grader.** "Recovered" and "spent eleven
  turns recovering" are different outcomes.

## Generating one

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/gen_faults.py <project> \
  --tool mcp__library__lookup_book --error "catalog service timed out" --dry-run
python3 ${CLAUDE_SKILL_DIR}/scripts/gen_faults.py <project> \
  --tool mcp__library__.* --latency-ms 2500 --probability 1.0
```

`--error` writes a `PostToolUse` / `error_output` entry; `--latency-ms` alone
writes a `PreToolUse` / `latency` entry; both together put both on one entry. It
refuses a probability outside `[0, 1]` (`SIM002`) and a fault that injects
nothing (`SIM021`), and prints the `fault_id` for the grader.

Sources: this plugin's runner —
`runner/agent_sdk_evals/faults.py` (`Fault`, `load_plan`, `build_hooks`,
`_apply`, `ACTIONS`, `CAPTURE_EVENTS`), `runner/agent_sdk_evals/loader.py`
(`read_faults`); `.dev/CONTRACTS.md` §1 (case key `faults`), §3 (the `hook`
trace event); `https://code.claude.com/docs/en/agent-sdk/hooks` (`HookMatcher`,
`hookSpecificOutput`, `permissionDecision`, `updatedInput`,
`updatedToolOutput`); `https://code.claude.com/docs/en/agent-sdk/python`
(`ClaudeAgentOptions.hooks`, `include_hook_events`).
