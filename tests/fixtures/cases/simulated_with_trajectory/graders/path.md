---
name: path
type: trajectory
match: EXACT
expected:
  - tool: mcp__library__lookup_book
  - tool: mcp__library__reserve_book
---
A fixed trajectory on a conversation the persona chooses the shape of. It fails
whenever the simulated user asks something the author did not foresee, which is
the whole reason to use a persona.
