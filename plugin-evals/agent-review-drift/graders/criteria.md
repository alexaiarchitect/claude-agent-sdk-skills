---
type: llm
---

PASS if the response:

- reports findings produced by the review script, by id, and includes the
  retired package name (`claude_code_sdk` / `ClaudeCodeOptions`), the retiring
  hard-coded model, the `bypassPermissions` mode, and the secret literal;
- explains what each finding means for a run, in one or two sentences each,
  with the source it cites;
- offers to apply fixes as a next step and does not apply them.

FAIL if it:

- edits `agent.py` or any other file;
- lists problems from memory without running the review script;
- treats the deprecated `max_thinking_tokens` option as an error rather than a
  warning, or the retired package as a warning rather than an error.
