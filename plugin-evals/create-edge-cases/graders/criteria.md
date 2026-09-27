---
type: llm
---

PASS if the response:

- measures coverage first with the plugin's coverage script and names the
  uncovered rules it found;
- writes two new case directories with a prompt and at least one grader each,
  targeting those rules, and validates them with the case validator afterwards;
- shows the write plan before writing and leaves the five existing cases
  untouched.

FAIL if it:

- edits an existing case;
- writes cases without checking coverage or without validating them;
- picks rules already covered.
