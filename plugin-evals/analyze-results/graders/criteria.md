---
type: llm
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

FAIL if it:

- explains the failure from the score alone, without the grader and reason;
- treats a never-evaluated run as a failure;
- re-runs the suite.
