---
type: llm
focus: trace
---

PASS if the response:

- recommends graders for this agent's actual tools and cases (looked up, not
  generic), naming free ones for the per-change tier and an `llm` grader only
  where a deterministic check cannot express the behaviour;
- states the cost of each kind in the script's tier words: free graders spend
  nothing beyond the run, `llm` graders spend one judge call per sample, and on
  a subscription all of it draws on plan usage limits with dollar figures as
  estimates;
- says why a refusal case needs `no_tool` or an `EXACT` trajectory rather than
  a looser match;
- ends by offering to generate the chosen graders, and does not generate them.

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

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, evidenced as
the paragraph above defines.

- **the grader types taken from `grader_info.py`'s catalog output**, and for
  each type it recommends, that type's **"does not prove"** point from the
  catalog — the script prints one per type under "What each does not prove",
  and that column is the argument for pairing graders. The catalog's point
  applied to this agent's case counts (its `tool_used` line is that the call's
  arguments and success are unproven, so "this does not prove the refusal was
  explained" is that gap in context). A "does not prove" line about something
  else entirely, with the type's own limit never carried over, does not;
- **the agent's actual tool names as a script reported them**, by
  `crosscheck_tools.py` or `discover.py` (`mcp__library__lookup_book`,
  `mcp__library__reserve_book`, `mcp__library__cancel_reservation`); the
  recommendations have to be tied to those names. Tool names read out of grader
  files with `cat` are not script output;
- **a cost tier for every recommendation, in the script's own words** —
  `grader_info.py` labels each type `free` or `judge`, and `validate_sim.py`
  and the skill's options use `free`, `run`, `judge` for what an action spends.
  "No extra cost" or "judge calls" as a paraphrase of the right tier is fine; a
  recommendation carrying no tier at all is not;
- **why `no_tool` or `EXACT` and not a looser trajectory match**, as the
  decision rules put it: `IN_ORDER` and `ANY_ORDER` tolerate extra calls, so
  the forbidden call can happen in between and still pass, whereas `no_tool`
  asserts the absence itself and `EXACT` asserts the whole call list. Pairing
  it with a judge grader on the explanation, because restraint alone could also
  be an agent that crashed or refused everything, is the other half;
- **the credential as a script reported it, plus the prompt's premise.** The
  sandbox has no credential, so `validate_config.py` reporting `credential:
  none found` is the honest line and has to be the one stated. The response may
  then accept the prompt's own premise that this is a subscription — "no
  credential was found here; you say it is a subscription, so the dollar
  figures are estimates" is exactly right. Asserting a script-reported
  subscription that no output shows is a fail.

FAIL if it:

- writes any grader or config file;
- recommends an `llm` grader for something a `no_tool` or `trajectory`
  grader can check;
- presents judge calls as free on a subscription;
- recommends a grader type that is not in the catalog the script printed;
- names the agent's tools without a discovery or crosscheck script's output in
  the transcript;
- states a credential or cost basis no script output supports;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
