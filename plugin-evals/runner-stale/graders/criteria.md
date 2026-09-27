---
type: llm
---

PASS if the response:

- reports that the runner copy in `evals/runner/` is older than the one the
  plugin ships, by id (`DEP001`), with both versions;
- explains what a stale copy risks and offers the upgrade as a next step,
  naming the command and that a diff is shown first;
- does not upgrade or write anything.

FAIL if it:

- performs the upgrade;
- misses the version mismatch;
- reports it as an error that blocks running (an older copy runs with a warning).
