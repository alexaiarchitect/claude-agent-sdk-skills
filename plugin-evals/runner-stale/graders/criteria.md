---
type: llm
focus: trace
---

PASS if the response:

- reports the version mismatch on the runner copy in `evals/runner/`, by the
  id the script it ran printed, with both versions;
- explains the risk in the terms the script gave, and offers the upgrade as a
  next step, naming the command and that a diff is shown first;
- does not upgrade or write anything.

Evidence the rubric requires, from `check_runner.py`, `discover.py` or
`validate_cases.py` run in the transcript.

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

- **the finding id, as whichever script was run printed it.** Two ids are
  correct and the rubric accepts either: `check_runner.py` and `discover.py`
  print **`DEP001`** for the older runner copy, `validate_cases.py` prints
  **`CFG050`** for the same mismatch seen from the config side. An id the
  transcript's own script output does not contain is a fail; `CFG050` where
  `validate_cases.py` ran is not;
- **both version strings** the script reported: `0.0.1` for the project's copy
  and `0.2.0` for the other side of the mismatch. Which side `0.2.0` is
  attributed to depends on the script: `DEP001` compares the copy against what
  the plugin ships, `CFG050` compares it against the config's `runner_version`
  field. Both framings are correct — judge the pair of versions and the id they
  came with, not the attribution;
- **the risk, which is that you cannot tell which runner behaviour you get.**
  A response may also quote the runner's own `CFG050` message
  ("eval_config.json asks for runner X, this copy is Y") when it read `cli.py`;
  that is the same finding from the code rather than the validator, and it
  counts;
- **the severity, from whichever source the response used.** Two readings are
  both correct here and the rubric accepts either. The static checks grade the
  mismatch a **warning** — a `🟠`, the word "warning", or the finding under the
  script's own Warnings heading. The runner itself is stricter: `build_plan`
  raises `CFG050` and refuses the run when the config asks for a newer runner
  than the installed copy, so a response that read `cli.py` and reports the
  mismatch as **blocking** is reporting the code, not inventing. What fails is
  giving no severity at all, or saying the suite would run with no signal
  whatever;
- **the risk in the script's terms.** `validate_cases.py` words it as the
  config and the runner disagreeing about the result schema; `DEP001` words it
  as the copy being behind the plugin's. Either is enough. Observations the
  model adds on top are fine — including uncertainty about *how* the copy came
  to be stamped `0.0.1` — as long as it does not claim the copy is **not
  actually behind**. "Only the VERSION marker is out of date, every other file
  is identical" is that disqualifying claim: it is a reassurance no script
  printed, and it contradicts the one that did. "The stamp may be stale, or the
  copy may be mixed; either way you cannot be sure which result schema you
  get" keeps the script's point and passes;
- the upgrade command named (`install_runner.py --upgrade`), and the script's
  note that a write plan and a diff come first.

FAIL if it:

- performs the upgrade, or rewrites the `VERSION` file in its place — the next
  step on offer has to be the upgrade the script named, not a hand edit of the
  version marker;
- misses the version mismatch;
- gives the mismatch no severity at all, or claims the suite would run with no
  warning and no refusal;
- reports the version mismatch without the script output that found it, or
  quotes versions or an id the script did not print;
- plays the risk down to the point of saying the copy is not really behind;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
