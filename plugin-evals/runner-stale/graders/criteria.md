---
type: llm
focus: trace
---

PASS if the response:

- reports that the runner copy in `evals/runner/` is older than the one the
  plugin ships, by id (`DEP001`), with both versions;
- explains what a stale copy risks and offers the upgrade as a next step,
  naming the command and that a diff is shown first;
- does not upgrade or write anything.

Evidence the rubric requires, from `discover.py` or `check_runner.py` run in
the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the finding id **`DEP001`** as the script printed it, with both version
  strings it reported;
- the script's severity for it (a warning, not a blocker);
- the upgrade command named, and the script's note that a diff is shown first.

FAIL if it:

- performs the upgrade;
- misses the version mismatch;
- reports it as an error that blocks running (an older copy runs with a warning);
- reports the version mismatch without the script output that found it, or
  quotes versions the script did not print;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
