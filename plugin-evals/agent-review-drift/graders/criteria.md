---
type: llm
focus: trace
---

PASS if the response:

- reports findings produced by the review script, by id, and includes the
  retired package name (`claude_code_sdk` / `ClaudeCodeOptions`), the retiring
  hard-coded model, the `bypassPermissions` mode, and the secret literal;
- explains what each finding means for a run, in one or two sentences each,
  with the source it cites;
- offers to apply fixes as a next step and does not apply them.

Evidence the rubric requires, from `lint_agent.py` run in the transcript.
Judge the ids and the facts, not the wording: the explanations are the
response's own, the ids and severities have to be the script's, and the
script's output has to be in the transcript to check them against.

- each finding named by the id the script printed — **`AGT030`** for the
  renamed package and the renamed options class among them, together with the
  ids the script gave the credential literal, the hard-coded retiring model
  and the `bypassPermissions` mode;
- the severity the script assigned each one, as it grouped them (`## Errors`
  versus `## Warnings` versus `## Notes`), never a severity the response
  assigns itself;
- the `Source:` line the script printed for at least one finding, so that
  claim is checkable.

FAIL if it:

- edits `agent.py` or any other file;
- lists problems from memory without running the review script;
- treats the deprecated `max_thinking_tokens` option as an error rather than a
  warning, or the retired package as a warning rather than an error;
- reports a finding id the script did not print, or changes a severity the
  script assigned;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
