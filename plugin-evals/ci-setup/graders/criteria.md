---
type: llm
focus: trace
---

PASS if the response:

- generates the workflow with the plugin's script and shows the write plan
  before writing;
- explains that the token comes from `claude setup-token` and is tied to the
  user's own plan, and that the pr tier uses free graders only;
- runs the workflow linter afterwards and reports its findings, or reports that
  it found none;
- says how exit 3 (inconclusive) is treated.

Evidence the rubric requires, from the plugin's own scripts run in the
transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the write plan `gen_workflows.py` printed, before any file was written;
- `lint_workflows.py`'s findings by id afterwards, or its "no findings" line;
- the credential named with its cost basis as `check_env.py` or the generated
  workflow reports it (the OAuth secret, drawn from the user's own plan).

FAIL if it:

- puts a judge grader or the nightly tier in the per-PR job;
- writes a credential literal into the workflow;
- gates on `claude-code-action` instead of the runner's exit code;
- claims the workflow lints clean without the linter's output in the
  transcript;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
