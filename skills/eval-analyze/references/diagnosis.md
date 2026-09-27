# Diagnosis: the quadrant and the divergence point

## The quadrant

Two kinds of grader look at two different things. Trajectory graders
(`trajectory`, `tool_used`, `tool_order`, `no_tool`, `hook_event`) judge the
path: which tools ran, in what order, with what arguments, and which did not
run. Answer graders (`llm`, `regex`, `final_text`, `structured_output`) judge
the last message. Cross them:

| Quadrant | Path | Answer | What it usually means | Where the fix belongs |
|---|---|---|---|---|
| Q1 | good | good | the case is a guard; keep it | nowhere |
| Q2 | good | weak | the work was done and the answer under-reports it; often the grader is too strict on wording | the grader, or the prompt's answer format |
| Q3 | weak | good | the answer reads well and the agent skipped, reordered or invented the work behind it | the system prompt's ordering and refusal rules; check whether the answer was grounded in tool output at all |
| Q4 | weak | weak | a plain logic failure | the agent |

Q3 is the reason trajectory graders exist: every answer-only grader passes it.
A refusal case that scored with `IN_ORDER` or `ANY_ORDER` cannot land in Q3
because those match types allow extra calls; the reviewer warns about that
combination (`EVC041`).

A case with graders of only one kind cannot be placed. The summary prints
"n/a" and the fix is to add the other kind, usually a `trajectory` grader
generated from a reviewed trace by `/agent-sdk:eval-create`.

## The divergence point

The first tool call where the actual trajectory parts from the expected one.
Everything after it is downstream noise, so that is where a fix belongs. Four
kinds:

| Kind | The actual run | Typical cause |
|---|---|---|
| `missing` | never made an expected call | the prompt does not require it, or an earlier result satisfied the agent |
| `extra` | made a call that was not expected | the prompt does not forbid it; a lenient match type hides it |
| `wrong_tool` | a different tool at that position | tool descriptions overlap |
| `arg_mismatch` | the right tool with different arguments | normalization, a value taken from the wrong place |

An early `arg_mismatch` followed by correct-looking calls is a **cascading
error**: step one normalized something wrong and nothing revalidated it. The
symptom is at the end; the cause is at the start.

`/agent-sdk:agent-debug`'s `analyze_trace.py` computes the divergence from the
trace and the case's `trajectory` grader; this skill tells you which trace to
hand it (the worst run's `trace` field in the result file).

## Signatures worth recognising in a trace

- **loop**: the same tool with the same arguments three or more times running;
- **oscillation**: A, B, A, B;
- **stall**: a result with no tool call and no final text;
- **unknown tool**: a call to a name the agent does not have (often a mock
  named differently from the real server);
- **error cascade**: two or more consecutive tool results with `is_error`;
- **capped**: `terminal_reason` of `max_turns` or a `max_budget_usd` subtype.

---

Sources: this plugin's `lib/agent_sdk_skills/trajectory.py` and
`skills/eval-analyze/scripts/summarize_results.py`; the trajectory-versus-outcome
framing follows Anthropic's engineering post
`https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents`.
