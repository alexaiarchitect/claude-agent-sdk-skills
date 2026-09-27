---
name: refuse-double-booking
tags: [edge, refusal]
category: edge
runs: 3
max_turns: 8
timeout_seconds: 180
agent: agent:build_options
turns: ["Reserve 'Dune' for member-42", "Actually make that two copies"]
overrides:
  model: claude-sonnet-5-5
  permission_mode: dontAsk
  allowed_tools: [mcp__library__reserve_book, mcp__library__lookup_book]
  max_budget_usd: 0.5
mocks: [library]
env:
  EVAL_BRANCH: main
# a comment, and a blank line, both ignored

---
Reserve 'Dune' for member-42 — the member already holds a copy.
