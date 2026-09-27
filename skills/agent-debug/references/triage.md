# Triage: from a symptom to a layer

A misbehaving agent shows one of a few shapes, and each shape points at a
layer. Triage is deciding which layer before touching anything, and the
evidence is a trace, not a memory of what it "usually does".

## Step 0 — rule out the evaluation

Before blaming the agent, check the case: a `trajectory` grader with `EXACT`
where the prompt allows a lookup first; a `regex` on wording; a `no_tool`
naming the wrong `mcp__server__tool`; a `budget` ceiling below the measured
mean. `/agent-sdk:eval-review` finds most of these for free. A case that
failed only after a grader change is a grader problem until proven otherwise.

## Step 1 — read what already exists (free)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/analyze_trace.py --trace evals/results/<ts>/<case>.1.trace.jsonl --case-dir evals/<case>
python3 ${CLAUDE_SKILL_DIR}/scripts/analyze_trace.py --session ~/.claude/projects/<dir>/<id>.jsonl
```

The script names the failure shape, the first divergence from the expected
trajectory when the case has one, the tool errors, the terminal reason, the
rate-limit state and the cost. Read that before deciding anything.

## Step 2 — establish deterministic or stochastic (spends)

One failing run is one sample. Ask the user before re-running:
`/agent-sdk:eval-run --case <name> --runs 5` starts five sessions. If every
run fails the same way, the cause is in the prompt, the tools or the options
and a fix is testable. If some pass, the case is flaky, the fix is about
robustness (tool descriptions, ordering rules, a `fallback_model`), and the
measure of success is pass@1 going up, not one green run.

## Step 3 — assign the layer

| Evidence | Layer | Typical fix |
|---|---|---|
| the right tools were available but the wrong one was called, or in the wrong order | system prompt | ordering and refusal rules; name the tool to use first |
| a tool was called with wrong arguments, then everything downstream went wrong | tool description or schema | tighten the parameter description; validate in the tool and return an error the model can act on |
| a tool result was an error and the agent kept going as if it were not | prompt + tool | say what to do on error; make errors unmistakable (`is_error`) |
| the same call repeated, or A-B-A-B | prompt, `max_turns` | tell the agent when to stop; cap turns; return progress in tool results |
| no tool call and no answer (stall) | options or permissions | a denied permission the agent could not see; `permission_mode`, `allowed_tools`; check `permission_denials` in the result |
| an unknown tool name | MCP wiring | the server name in `mcp_servers` versus the `mcp__server__tool` the prompt mentions; a mock named differently |
| ended by `max_turns` or `max_budget_usd` | budget or a loop | raise the cap only after ruling out a loop |
| `NOT_EVALUATED` with a `rejected` rate limit or 429 | quota | wait for `resets_at`; nothing to fix in the agent |
| passes with `setting_sources` loaded, fails isolated | context | the agent depended on the developer's `CLAUDE.md` or settings; put the instruction in the system prompt |

## Step 4 — close the loop

Fix in the layer named, write the failing trace into a regression case
(`/agent-sdk:eval-create`'s `trace_to_case.py`), re-run that case, then the
full `pr` tier. A fix that is not pinned by a case will be undone by the next
prompt edit.

---

Sources: this plugin's `lib/agent_sdk_skills/trajectory.py` (signatures) and
`skills/agent-debug/scripts/analyze_trace.py`; permission behaviour per
`https://code.claude.com/docs/en/agent-sdk/permissions`; turn and budget caps
per `https://code.claude.com/docs/en/agent-sdk/agent-loop`.
