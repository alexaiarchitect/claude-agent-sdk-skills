---
type: llm
---

PASS if the response:

- reports the planted defect by id: an `overrides` key that is not a
  `ClaudeAgentOptions` field (`permision_mode`, EVC003), with the file and the
  fix;
- reports the rest of the suite's findings from the validator, or that there
  are none, rather than guessing;
- explains that the mistyped override would have been refused before any
  session started, and offers the correction without applying it.

FAIL if it:

- pronounces the file valid or invalid without running the validator;
- edits the case;
- describes the problem without the finding id.
