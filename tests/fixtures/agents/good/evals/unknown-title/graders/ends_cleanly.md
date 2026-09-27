---
name: ends_cleanly
type: terminal
subtype: success
terminal_reason: completed
allow_error: false
---
Proves an unknown title is handled, not crashed on: the run finishes normally
rather than ending in `error_during_execution` or being cut off.

It does not prove the agent said anything useful — `subtype: success` means only
that the loop finished without erroring. This is the grader to use when you want
to assert *how* a run ended; a `budget` grader cannot do it, because `num_turns`
can exceed the option's value without the limit tripping.
