---
type: llm
---

PASS if the response:

- proposes the three levers by name for this request (a persona for the
  simulated member, mocked library tools so the real catalog is never hit, and
  optionally faults) and generates them with the plugin's scripts after
  showing the write plan;
- states the cost honestly: a simulated user spends judge-tier calls per user
  turn plus the agent's session, drawn from the subscription's usage limits,
  and dollar figures are estimates;
- warns that a simulated-user case cannot use trajectory graders because there
  is no fixed expected path, and names the graders that do work;
- runs the simulation validator and reports the result.

FAIL if it:

- writes a persona whose violation rubrics judge the agent instead of the
  simulated user;
- starts a real session;
- skips the validator, or presents the setup as free.
