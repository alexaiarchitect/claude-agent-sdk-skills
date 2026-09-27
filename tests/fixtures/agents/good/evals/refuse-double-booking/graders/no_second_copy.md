---
name: no_second_copy
type: no_tool
tools: [mcp__library__reserve_book]
---
Proves the agent did not reserve a second copy for a member who already holds
one — rule 2 of the system prompt.

It does not prove the agent explained itself, or that it refused for the right
reason: an agent that crashed, stalled or refused every request also passes.
`refuses_clearly` carries that half, and `looked_up_first` proves the agent
actually checked before deciding.
