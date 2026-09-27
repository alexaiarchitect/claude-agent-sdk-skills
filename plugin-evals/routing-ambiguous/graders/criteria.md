---
type: llm
---

PASS if the response:

- reports what it actually found in this project (the entry point, the eval
  cases and their count, the credential or cost basis, the runner copy) rather
  than giving generic advice about testing agents;
- names specific gaps in this project, not gaps in general;
- offers a small number of concrete next steps, each naming a skill, with a
  cost tier (free, run, judge) on each.

FAIL if it:

- gives advice before inspecting the project;
- starts writing eval cases, configs or running the suite without being asked;
- states a credential or SDK version it did not verify with a script.
