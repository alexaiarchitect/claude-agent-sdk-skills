---
type: llm
focus: trace
---

PASS if the response:

- names the failing case and the grader that failed, with the reason the
  result file recorded;
- places the failure in the trajectory-versus-answer quadrant, or says why it
  cannot be placed;
- reports any never-evaluated run separately from the failure, with its cause;
- reports cost apart from the verdicts and calls it an estimate if the result
  files say the credential was a subscription;
- points at a next step: the trace to read, a re-run to establish flakiness, or
  a regression case.

Evidence the rubric requires, from `summarize_results.py` (and `pass_at_k.py`
if reliability is discussed) run in the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the failing case and the failing grader named as the script printed them,
  with the reason it recorded for the failure;
- the never-evaluated count taken from the script's own tally, not inferred;
- the cost figure as the script reported it, with its cost basis.

FAIL if it:

- explains the failure from the score alone, without the grader and reason;
- treats a never-evaluated run as a failure;
- re-runs the suite;
- reports a case, grader, count or cost figure that the script's output does
  not contain;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
