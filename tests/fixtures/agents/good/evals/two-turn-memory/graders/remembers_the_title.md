---
name: remembers_the_title
type: final_text
reference: Dune
mode: contains
target: last_message
---
Proves the agent carried the title from turn 1 into its answer to turn 2, where
the member never said "Dune" again. That is the whole point of a memory case: the
second turn is only answerable using the first.

It does not prove the agent did the right thing with it — a refusal that names
Dune passes. `mode: contains` is a substring test, not a meaning test; `rouge1`
would compare word overlap, which is still not meaning.
