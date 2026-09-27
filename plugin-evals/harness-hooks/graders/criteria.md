---
type: llm
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

FAIL if it:

- edits the agent or writes a hook file;
- explains hooks from memory without running the linter;
- presents `SessionStart` as a valid Python SDK hook event.
