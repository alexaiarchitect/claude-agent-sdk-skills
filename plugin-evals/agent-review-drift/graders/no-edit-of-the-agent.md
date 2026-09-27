---
type: regex
target: trace
pattern: "\"(?:Edit|Write)\"[^\\n]*agent\\.py"
match: not_contains
---

`Write` and `Edit` are granted to this case on purpose, so "it did not edit" is
a choice the model made rather than a tool it was denied. This matches the
execution trace and fails if any `Edit` or `Write` call names `agent.py`. It
does not prove byte-equality: a write through `Bash` would not appear as an
`Edit`, which is why `Bash` here is restricted to `python3` and the plugin's own
read-only scripts.
