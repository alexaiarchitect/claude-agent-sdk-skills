---
type: regex
target: trace
pattern: "\"(?:Edit|Write)\"[^\\n]*evals/(?:reserve-available|refuse-double-booking|no-cancel-unasked|two-turn-memory|unknown-title)/"
match: not_contains
---

New cases belong in new directories. This matches the execution trace and
fails if any `Edit` or `Write` call names one of the five existing case
directories. It does not prove byte-equality; the checksums the scaffold
writes to `.scaffold/protected.sha256` exist for that, for a human reading the
sandbox afterwards with `--keep-temp`. No grader can read them: `file_exists`
counts only files Claude created during the run.
