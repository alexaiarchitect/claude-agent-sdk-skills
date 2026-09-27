---
type: regex
target: trace
pattern: "lint_harness\\.py|lint_agent\\.py"
---

The diagnosis has to come from the linter, not from reading the file and
recognising the shapes. This matches the execution trace for a run of either
harness or agent linter.
