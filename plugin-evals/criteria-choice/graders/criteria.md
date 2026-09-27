---
type: llm
---

PASS if the response:

- recommends graders for this agent's actual tools and cases (looked up, not
  generic), naming free ones for the per-change tier and an `llm` grader only
  where a deterministic check cannot express the behaviour;
- states the cost of each kind: free graders spend nothing beyond the run,
  `llm` graders spend one judge call per sample, and on a subscription all of
  it draws on plan usage limits with dollar figures as estimates;
- says why a refusal case needs `no_tool` or an `EXACT` trajectory;
- ends by offering to generate the chosen graders, and does not generate them.

FAIL if it:

- writes any grader or config file;
- recommends an `llm` grader for something a `no_tool` or `trajectory`
  grader can check;
- presents judge calls as free on a subscription.
