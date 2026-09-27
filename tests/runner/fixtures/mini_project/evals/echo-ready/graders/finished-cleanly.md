---
type: terminal
subtype: success
terminal_reason: completed
---
Proves the session ended on its own terms rather than by hitting a ceiling or
erroring.

`terminal_reason` is the honest place to assert a limit tripped; `num_turns`
is not, because a successful run measured `num_turns=2` under `max_turns=1`.
