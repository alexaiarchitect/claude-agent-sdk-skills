---
type: tool_order
before: lookup_book
after: reserve_book
---
Proves the agent never reserved a title it had not looked up.

Both tools must appear for this to hold; if the agent correctly declined to
reserve anything, this grader fails, which is why it lives on a case whose prompt
asks for a lookup only when a reservation is also expected.
