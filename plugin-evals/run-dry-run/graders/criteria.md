---
type: llm
focus: trace
---

PASS if the response:

- states the command that would run and the credential the session would
  inherit, as the dry run reported them;
- gives the session arithmetic the dry run printed: how many cases, how many
  sessions, and whether any judge calls are involved in the pr tier;
- states what the scripts said about the interpreter and the SDK, in their
  terms, including that it was not verified;
- offers the choice with a cost tier, and does not start the suite.

Evidence the rubric requires, from `run_evals.py --dry-run` (and
`check_runner.py` or `check_env.py` if quoted) run in the transcript.

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

- **the credential as the script reported it.** The dry run prints a
  `credential:` line; in this sandbox there is none, so `none found` (with the
  places it looked) is the correct and expected answer, and the response has to
  give what the script gave rather than a cost basis no output shows. The
  prompt's own premise about a plan may be accepted on top of it, provided the
  response says the credential was not found and that any dollar figure is
  therefore an estimate;
- **the session arithmetic as the dry run now prints it**: the case count and
  the `sessions_total` figure, with how it is reached (the tier's runs, and the
  cases that pin their own `runs`, which the dry run reports in parentheses and
  `--json` itemises per case). The total has to be the one the dry run printed.
  Spelling out the per-case sum beside it is fine and welcome — what fails is a
  total that no dry run printed, reasoned out of `cli.py` or a reference's
  worked example instead;
- **the interpreter and SDK statement in the script's words.** Either half
  satisfies this: the dry run's `interpreter:` line with its own
  `(unverified - claude_agent_sdk not checked)` qualification, or
  `check_runner.py`'s probe line, whose result ("No interpreter with
  claude_agent_sdk", with the venv fix it suggests) may be reported as it
  stands — saying the machine has no interpreter carrying the SDK is that
  probe's finding, not an overstatement. What fails is naming an SDK *version*
  no script printed, or presenting the SDK as verified present when the only
  line in the transcript says it was not checked;
- **a cost tier on the choice offered**: the pr tier and the nightly tier
  both named, each with what it spends in the tier words the scripts use
  (`free` graders versus `judge` calls). The pr figures come from the dry run.
  Nightly's may come from a second dry run, or from the config's own tier block
  (its `graders` and `runs`) read in the transcript — either is script or file
  output, and the response should say which. What fails is a nightly session or
  judge-call count with neither behind it.

The response does not have to end with a question. Offering the choice, or
saying plainly what it would take to proceed, both satisfy the last PASS item;
what it must not do is start the suite.

FAIL if it:

- starts the suite;
- states a cost in dollars as a fact when the credential is a subscription,
  without calling it an estimate;
- invents numbers the scripts did not print, including a session or judge-call
  count that matches no dry-run or config figure in the transcript;
- states a credential, cost basis, interpreter or SDK version that no script
  output in the transcript supports, or overstates what the probe checked;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
