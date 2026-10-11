---
type: llm
focus: trace
---

PASS if the response:

- recommends graders for this agent's actual tools and cases (looked up, not
  generic), naming free ones for the per-change tier and an `llm` grader only
  where a deterministic check cannot express the behaviour;
- states the cost of each kind: free graders spend nothing beyond the run,
  `llm` graders spend one judge call per sample, and on a subscription all of
  it draws on plan usage limits with dollar figures as estimates;
- says why a refusal case needs `no_tool` or an `EXACT` trajectory;
- ends by offering to generate the chosen graders, and does not generate them.

Evidence the rubric requires, from the plugin's scripts run in the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the grader types taken from `grader_info.py`'s catalog output, including its
  "does not prove" column for the ones recommended;
- the agent's actual tool names as a discovery or crosscheck script reported
  them;
- a cost tier (`free`, `run`, `judge`) stated for every recommendation, and the
  credential's cost basis as a script reported it.

FAIL if it:

- writes any grader or config file;
- recommends an `llm` grader for something a `no_tool` or `trajectory`
  grader can check;
- presents judge calls as free on a subscription;
- recommends a grader type that is not in the catalog the script printed;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
