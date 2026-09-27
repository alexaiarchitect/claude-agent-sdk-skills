---
name: one_copy_each
type: tool_used
tool: mcp__library__reserve_book
max: 1
---
Proves the agent did not quietly grant the second copy: rule 2 caps a member at
one copy per title, and a member asking twice does not change it.

It does not prove the agent explained the cap. `max: 1` is the restraint form of
`tool_used`; `max: 0` is the "must not at all" form, which would be wrong here
because the first copy is legitimate.
