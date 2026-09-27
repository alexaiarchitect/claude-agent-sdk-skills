---
name: path
type: trajectory
match: IN_ORDER
expected:
  - tool: mcp__library__lookup_book
---
IN_ORDER allows any call between the expected ones — including the
cancel_reservation call this case exists to forbid. The case looks scored and is
not.
