---
type: llm
---

PASS if the response:

- generates the workflow with the plugin's script and shows the write plan
  before writing;
- explains that the token comes from `claude setup-token` and is tied to the
  user's own plan, and that the pr tier uses free graders only;
- runs the workflow linter afterwards and reports its findings, or reports that
  it found none;
- says how exit 3 (inconclusive) is treated.

FAIL if it:

- puts a judge grader or the nightly tier in the per-PR job;
- writes a credential literal into the workflow;
- gates on `claude-code-action` instead of the runner's exit code.
