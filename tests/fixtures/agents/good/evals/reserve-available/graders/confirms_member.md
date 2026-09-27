---
name: confirms_member
type: regex
pattern: "member-42"
match: contains
target: last_message
---
Proves the reply names the member the copy was reserved for, so a reader can
tell whose reservation was made.

It does not prove the reservation happened, and it does not prove the sentence
around the id says what you hope: "I could not reserve anything for member-42"
passes this grader. `follows_the_path` is what proves the action.
