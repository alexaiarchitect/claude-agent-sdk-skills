---
type: llm
focus: trace
---

PASS if the response:

- reports pass@1 per case from the script's table, and the verdict
  (reliable, marginal, unreliable) for each;
- names the flaky case and says its pass@1 is what production will see, not
  its pass@k;
- says how many runs the figures rest on and what that resolution can and
  cannot distinguish.

Evidence the rubric requires, from `pass_at_k.py` run in the transcript.

Judge the ids and the facts, not the wording: the response may use its own
words, but each item below has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the pass@1 figures and verdicts read from the script's table, per case;
- the run count the script printed, used as the resolution claim;
- the flaky case named as the script named it.

FAIL if it:

- presents a single run's result as reliability;
- averages scores across runs instead of counting passes;
- calls a case that passes 2 runs in 5 "mostly working";
- reports a pass@1 figure or a verdict that the script's table does not
  contain;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
