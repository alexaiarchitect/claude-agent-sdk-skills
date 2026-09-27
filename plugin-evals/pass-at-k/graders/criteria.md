---
type: llm
---

PASS if the response:

- reports pass@1 per case from the script's table, and the verdict
  (reliable, marginal, unreliable) for each;
- names the flaky case and says its pass@1 is what production will see, not
  its pass@k;
- says how many runs the figures rest on and what that resolution can and
  cannot distinguish.

FAIL if it:

- presents a single run's result as reliability;
- averages scores across runs instead of counting passes;
- calls a case that passes 2 runs in 5 "mostly working".
