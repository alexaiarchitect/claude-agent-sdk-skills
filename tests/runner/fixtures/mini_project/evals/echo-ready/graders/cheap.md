---
type: budget
max_cost_usd: 0.05
max_output_tokens: 200
informational: true
---
Reports what a one-word answer costs on this account, and never gates on it.

`max_cost_usd` is compared against the case total, which is the last
`total_cost_usd` the session reported — that field is a running total, not a
per-turn figure.
