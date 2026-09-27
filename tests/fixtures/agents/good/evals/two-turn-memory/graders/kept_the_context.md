---
name: kept_the_context
type: tool_order
before: mcp__library__lookup_book
after: mcp__library__reserve_book
---
Proves the agent still looked before it reserved, across a two-turn
conversation — the rule has to survive the second turn as well as the first.

It does not prove which title or member the second turn acted on, and it does
not prove the second request was handled at all: `tool_order` only asserts that
one call preceded another somewhere in the trace.
