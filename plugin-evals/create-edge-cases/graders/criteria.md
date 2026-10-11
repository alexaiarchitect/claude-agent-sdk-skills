---
type: llm
focus: trace
---

PASS if the response:

- measures coverage first with the plugin's coverage script and names the
  uncovered rules it found;
- writes two new case directories with a prompt and at least one grader each,
  targeting those rules, and validates them with the case validator afterwards;
- shows the write plan before writing and leaves the five existing cases
  untouched.

Evidence the rubric requires, from the plugin's scripts run in the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- `coverage_matrix.py`'s output, with the uncovered rules named as the script
  named them;
- the write plan shown before the two case directories were written;
- `validate_cases.py` run afterwards, with its findings or its "no findings"
  line for the two new cases.

FAIL if it:

- edits an existing case;
- writes cases without checking coverage or without validating them;
- picks rules already covered;
- names an uncovered rule that the coverage script's output does not list;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
