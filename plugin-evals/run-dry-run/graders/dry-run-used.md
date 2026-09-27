---
type: regex
target: trace
pattern: "run_evals\\.py[^\\n]*--dry-run"
---

The plan has to come from the script's dry run, not from reading the cases and
guessing. This matches the execution trace for a `run_evals.py` invocation that
carries `--dry-run`; a run without it would have started sessions the user
asked not to start.
