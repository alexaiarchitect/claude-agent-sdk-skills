---
type: llm
---

PASS if the response:

- states the command that would run, the credential the session would inherit
  and its cost basis (subscription or API key), and the interpreter or SDK
  version, as reported by the scripts;
- gives the arithmetic: how many cases, how many sessions, and whether any
  judge calls are involved in the pr tier;
- ends by asking whether to run, or offering the choice, rather than running.

FAIL if it:

- starts the suite;
- states a cost in dollars as a fact when the credential is a subscription,
  without calling it an estimate;
- invents numbers the scripts did not print.
