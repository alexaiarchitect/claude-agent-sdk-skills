---
type: llm
focus: trace
---

PASS if the response:

- reports the hook findings by id from the linter output, and among them the
  synchronous callback, the callback whose return lacks `hookSpecificOutput`
  with a matching `hookEventName`, and the event name the Python SDK does not
  support;
- explains the correct callback shape for a PreToolUse deny (async, the
  `hookSpecificOutput` dict with `permissionDecision` and a reason) and cites
  the hooks documentation;
- offers to generate a corrected hook with the plugin's generator as a next
  step, and does not write it.

Evidence the rubric requires, from `lint_harness.py` run in the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- each hook defect named by the id the script printed (`HOK001` for the
  synchronous callback, `HOK002` for the unreadable return, `HOK020` for the
  unsupported event), with the script's locator;
- the script's own `Source:` line for the callback contract;
- the generator offered by name (`gen_hook.py`) and not run.

FAIL if it:

- edits the agent or writes a hook file;
- explains hooks from memory without running the linter;
- presents `SessionStart` as a valid Python SDK hook event;
- names a hook finding id without the linter's output in the transcript, or
  invents an id the linter does not define;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
