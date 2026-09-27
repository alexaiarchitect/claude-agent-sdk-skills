---
type: regex
target: trace
pattern: "\"(?:Edit|Write)\"[^\\n]*agent\\.py"
match: not_contains
---

The user has not decided whether to change anything, and `Write`/`Edit` are
granted on purpose. Fails if any edit names the agent file. A `gen_hook.py`
run with `--dry-run` is fine; one without it that writes a file would also be
caught by `criteria.md`.
