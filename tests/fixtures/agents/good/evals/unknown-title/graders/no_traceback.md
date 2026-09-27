---
name: no_traceback
type: regex
pattern: "(?i)traceback|ModuleNotFoundError|KeyError"
match: not_contains
target: last_message
---
Proves the failure was explained in words rather than leaked as a Python
traceback. This is the regression it guards: an earlier version let the mock's
KeyError reach the member.

It does not prove the explanation was correct or even relevant — only that it
does not read like a crash. Note `not_contains` inverts the match, so this
grader passes when the pattern is absent.
