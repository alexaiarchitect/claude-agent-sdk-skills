---
type: llm
focus: trace
---

PASS if the response:

- reports pass@1 per case from the script's table, and the verdict
  (`RELIABLE`, `MARGINAL`, `UNRELIABLE`) the table gave each one;
- names the flaky case as the script named it, and keeps its single-run pass
  rate distinct from its pass@k — one attempt per request is not the same
  number as "at least one of k attempts passed";
- says how many runs the figures rest on and what that resolution can and
  cannot distinguish.

Evidence the rubric requires, from `pass_at_k.py` run in the transcript.

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

- **pass@1 and the verdict per case**, read from the script's table;
- **the run count the script printed**, used as the resolution claim, with the
  script's own caveat about what that many runs can and cannot separate;
- **the flaky case named** as the script named it;
- **the single-run rate held apart from pass@k for that case.** The table gives
  both: a pass@1 and a pass@k that is higher. The response has to show it knows
  they answer different questions — one shot versus a retry rescuing it — and
  not quote the pass@k figure as the case's reliability. Saying so in its own
  words counts, including as a failure rate ("it fails 2 requests in 5");
  stating only one number and calling it reliability does not.

FAIL if it:

- presents a single run's result as reliability;
- averages scores across runs instead of counting passes;
- calls a case that passes 2 runs in 5 "mostly working";
- quotes the case's pass@k as the number to plan around, or never separates it
  from pass@1 at all;
- reports a pass@1 figure or a verdict that the script's table does not
  contain;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
