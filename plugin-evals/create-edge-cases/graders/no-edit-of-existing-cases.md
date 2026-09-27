---
type: regex
target: trace
pattern: "\"(?:Edit|Write)\"[^\\n]*evals/(?:reserve-available|refuse-double-booking|no-cancel-unasked|two-turn-memory|unknown-title)/"
match: not_contains
---

New cases belong in new directories. This matches the execution trace and
fails if any `Edit` or `Write` call names one of the five existing case
directories. It does not prove byte-equality; the `scaffold-intact` sentinel
and the protected checksums in `.scaffold/` exist for that.
