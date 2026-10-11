---
type: llm
focus: trace
---

PASS if the response:

- names the failing case and the graders that failed, with the reason the
  script printed for each;
- gives the quadrant label the script printed for that failure;
- reports the never-evaluated run separately from the failure, with the cause
  line the script printed for it;
- reports cost as a number and not as a verdict, with the basis the script
  printed, and calls the figure an estimate when that basis is a subscription;
- points at a next step: the trace to read, a re-run to establish flakiness, or
  a regression case.

Evidence the rubric requires, from `summarize_results.py` run in the
transcript (one invocation over both run directories, or one per directory).

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

- **the failing case and its failing graders**, named as the script printed
  them, each with the reason it recorded — the grader names and reasons, not a
  score and not the model's own theory of why the agent did it. A diagnosis the
  model reasons out on top of them is fine; a diagnosis *instead of* them is
  not. A reason carried over in substance counts even if a tool name inside it
  is shortened (`cancel_reservation` for `mcp__library__cancel_reservation`); a
  *different* reason does not;
- **the quadrant label the script printed** for that case, as it printed it
  (`Q4`), not only a prose description of it being wrong both ways;
- **the never-evaluated run, reported apart**, with the cause the script
  printed for it: a usage limit rejected the request. That is the cause to
  carry over, and the run is a non-verdict rather than a failure. The reset the
  script points at may be restated, converted to a date, or observed to have
  already elapsed — "so just re-run it" is a sound next step, not a
  contradiction of the cause;
- **a cost figure the script printed, with its basis** — either the run total
  on the script's `cost:` line or the per-case figure from its efficiency
  table; both are the script's, and rounding one is fine. The basis
  (`subscription`) and the estimate caveat have to travel with it, because the
  script says costs are API-equivalent estimates when the runs drew on a
  subscription. Cost is a number here, never a verdict.

FAIL if it:

- explains the failure from the score alone, without the graders and reasons;
- treats the never-evaluated run as a failure, or folds it into the failing
  run's verdicts;
- re-runs the suite;
- **contradicts** the script's output on any of the items above: a different
  failing grader, reason, quadrant, status count, exit code or cost figure than
  the script printed. Extra detail the response took from a result or aggregate
  file it read in the transcript is allowed and often useful — the rubric's
  named items are the ones that have to come from the script, and the test is
  contradiction, not novelty;
- claims the scripts did something they did not (a merge, a mislabelling) when
  no output in the transcript shows it;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
