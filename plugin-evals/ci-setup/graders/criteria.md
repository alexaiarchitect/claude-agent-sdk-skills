---
type: llm
focus: trace
---

PASS if the response:

- generates the workflow with the plugin's script, and the generator's own
  write plan is in the transcript;
- explains that the token comes from `claude setup-token` and is tied to the
  user's own plan, and that the pr tier uses free graders only;
- runs the workflow linter afterwards and reports its findings, or reports that
  it found none;
- says how exit 3 (inconclusive) is treated.

Evidence the rubric requires, from the plugin's own scripts run in the
transcript.

**What the judge can see.** The trace reaches the judge as its **first 12 and
last 12 messages**; everything between them is elided. An elided middle is not
evidence that a script was never run. Count an item as evidenced when either

- the script's invocation, or its output, is visible somewhere in that window;
  or
- the response states the item with the specificity only that script's output
  has — a finding id, a verbatim reason or `Fix:` string, an exact figure or
  table cell — and nothing visible in the window contradicts it.

This test applies only to the items **this rubric names**. A named item the
model could equally have produced from its own knowledge of the SDK, with
neither of those behind it, is not evidenced and fails. Everything else in the
answer — background, an aside, a rough order-of-magnitude figure the response
labels as its own estimate — is neither required nor penalised here unless a
FAIL clause below names it.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, evidenced as
the paragraph above defines.

- **`gen_workflows.py`'s own write plan.** The generator prints a
  `## Write plan` block with a `**create**` line per file. Either form
  satisfies this: a separate `--dry-run` invocation before the writing one, or
  the write plan the writing invocation itself printed. The prompt pre-approves writing, so a
  missing confirmation step is not a fail here — a hand-written workflow file,
  with no generator plan in the transcript at all, is;
- `lint_workflows.py`'s findings by id afterwards, or its summary line saying
  it found none;
- **the credential named with its cost basis.** The generator's plan prints the
  OAuth secret with "(subscription plan quota)" and the `claude setup-token`
  note; that is the cost basis to carry over. The sandbox has no credential of
  its own, so a `check_env.py` line reading `none found` is not a contradiction
  and the prompt's own premise ("my Claude subscription") may be taken as
  given — but then the dollar side of it is an estimate and has to be called
  one.

FAIL if it:

- puts a judge grader or the nightly tier in the per-PR job;
- writes a credential literal into the workflow;
- gates on `claude-code-action` instead of the runner's exit code;
- hand-writes the workflow instead of generating it;
- claims the workflow lints clean without the linter's output in the
  transcript;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
