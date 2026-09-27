---
name: looked_up_first
type: tool_order
before: mcp__library__lookup_book
after: mcp__library__reserve_book
---
Proves the agent checked availability before committing a copy — the rule the
system prompt states first.

It does not prove the lookup's answer was used: an agent that looks up Ulysses
and then reserves Dune passes this. Pair it with a `trajectory` grader when the
arguments matter.
