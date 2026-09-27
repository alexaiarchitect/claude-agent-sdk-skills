---
type: regex
pattern: "\\bready\\b"
flags: i
match: contains
target: last_message
---
Proves the model emitted the word `ready` somewhere in its final message.

Does not prove it said *only* that word, and does not prove it understood the
instruction — a model that answered "I am ready to help!" also passes. Use a
`final_text` grader with `mode: exact` when the exact string matters.
