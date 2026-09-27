---
name: confirms
type: regex
pattern: "member-42"
match: contains
target: last_message
---
Proves the reply names the member it acted for, so a user can tell whose
reservation was made.

It does not prove the reservation happened — only that the id appears in the
text. `tool_used` on reserve_book is what proves the action.
