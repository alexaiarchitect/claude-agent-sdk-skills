---
type: llm
focus: trace
---

PASS if the response:

- measures coverage first with the plugin's coverage script and reports what
  the matrix actually said, naming the rules it targeted from that output;
- writes two new case directories with a prompt and at least one grader each,
  generated with the plugin's case generator, and validates them with the case
  validator afterwards;
- shows the generator's write plan and leaves the five existing cases
  untouched.

Evidence the rubric requires, from the plugin's scripts run in the transcript.

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
A generated lever also counts as evidenced when the response **names the
generator and quotes a line of its plan** — "`gen_persona.py` planned
**create** `evals/personas/x.json`" — even if that invocation fell in the
elided middle. Naming no generator at all does not: "I wrote the persona" is
indistinguishable from a hand-written file.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, evidenced as
the paragraph above defines.

- **`coverage_matrix.py`'s output, read as it stands.** On this project it
  reports `rule_coverage: 4/4` and lists at least one case against every rule,
  so there are no uncovered rules to name, and the rubric does not ask for any.
  What it asks is that the choice of rules comes from that output: that the
  response says the matrix shows every rule covered, and then names the
  thinnest rules — the ones with the fewest cases in the matrix's own rule
  table — as the ones it targeted. A gap the model argues for from its own
  reading of the existing prompts, with no matrix figure behind it, does not
  satisfy this; the same gap presented as "the matrix gives this rule the
  fewest cases" does;
- **`gen_cases.py`'s write plan** for the two new cases. The generator prints a
  `## Write plan` block with a `**create**` line per file; the plan from a
  `--dry-run` pass or from the writing invocation itself both count. The prompt
  pre-approves writing, so no confirmation step is needed — hand-written case
  files with no generator plan in the transcript are a fail;
- **`validate_cases.py` run afterwards, with its output shown as the script
  printed it**: the findings, or the summary line that counts them. Unfiltered
  — a run piped through `sed` or `grep` so only part of the report reaches the
  transcript does not satisfy this, because what was cut is exactly what the
  rubric is checking.

FAIL if it:

- edits an existing case;
- writes cases without checking coverage or without validating them;
- hand-writes the case files instead of generating them;
- names an uncovered rule the coverage script's output does not list, or
  reports a coverage figure it did not print;
- shows the validator's output only through a filter, or only as its own
  paraphrase;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
