---
type: llm
focus: trace
---

PASS if the response:

- reports the planted defect by id: an `overrides` key that is not a
  `ClaudeAgentOptions` field (`permision_mode`, EVC003), with the file and the
  fix;
- reports the rest of the suite's findings from the validator, or that there
  are none, rather than guessing;
- explains that the mistyped override would have been refused before any
  session started, and offers the correction without applying it.

Evidence the rubric requires, from `validate_cases.py` (or
`validate_config.py`) run in the transcript. Judge the ids and the facts, not
the wording: the explanation is the response's own, the ids, the file and the
key have to be the validator's, and its output has to be in the transcript to
check them against.

- the finding id **`EVC003`**, with the file it named and the offending key as
  it spelled it;
- every other finding id the validator printed (`CFG013`, …), or its
  "no findings" line if it printed none;
- the correction the validator's `Fix:` line gives for `EVC003`, offered as a
  next step and not applied.

FAIL if it:

- pronounces the file valid or invalid without running the validator;
- edits the case;
- describes the problem without the finding id;
- names `EVC003` (or any other id) without the validator's output in the
  transcript to support it;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
