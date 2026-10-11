---
type: llm
focus: trace
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

Evidence the rubric requires, from the plugin's scripts run in the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the write plan shown before the persona and mocks were written;
- `validate_sim.py`'s findings by id afterwards, or its "no findings" line;
- the cost stated as a tier plus the credential's cost basis as a script
  reported it, with judge-tier calls counted per user turn.

FAIL if it:

- writes a persona whose violation rubrics judge the agent instead of the
  simulated user;
- starts a real session;
- skips the validator, or presents the setup as free;
- claims the persona or the mocks are valid without the validator's output in
  the transcript;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
