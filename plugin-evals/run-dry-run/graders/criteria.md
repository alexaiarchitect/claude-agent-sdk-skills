---
type: llm
focus: trace
---

PASS if the response:

- states the command that would run, the credential the session would inherit
  and its cost basis (subscription or API key), and the interpreter or SDK
  version, as reported by the scripts;
- gives the arithmetic: how many cases, how many sessions, and whether any
  judge calls are involved in the pr tier;
- ends by asking whether to run, or offering the choice, rather than running.

Evidence the rubric requires, from the plugin's scripts run in the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the credential and its **`cost basis:`** as `check_env.py` or
  `check_runner.py` reported it (`subscription`, `api_key`, or none found);
- the interpreter and SDK version as the script reported them, or the script's
  own statement that they could not be verified;
- the case and session arithmetic taken from the dry-run output, with a cost
  tier on the choice offered.

FAIL if it:

- starts the suite;
- states a cost in dollars as a fact when the credential is a subscription,
  without calling it an estimate;
- invents numbers the scripts did not print;
- states a credential, cost basis, interpreter or SDK version that no script
  output in the transcript supports;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
