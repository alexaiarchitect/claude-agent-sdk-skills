---
name: cheap_enough
type: budget
max_turns: 6
max_cost_usd: 0.25
max_output_tokens: 2000
informational: false
---
Proves this case stayed inside the work it should need: one lookup, one
reservation, one sentence.

It does not prove the turn *limit* tripped — `max_turns=1` was measured
producing `num_turns=2`, so a budget ceiling is the grader's own bound on
`result.num_turns`, never a check on `ClaudeAgentOptions.max_turns`. Use a
`terminal` grader for that. On a subscription the dollar figure is a client-side
estimate and nothing is billed; the real ceiling is the plan's usage window.
