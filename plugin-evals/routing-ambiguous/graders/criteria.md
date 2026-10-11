---
type: llm
focus: trace
---

PASS if the response:

- reports what it actually found in this project (the entry point, the eval
  cases and their count, the credential or cost basis, the runner copy) rather
  than giving generic advice about testing agents;
- names specific gaps in this project, not gaps in general;
- offers a small number of concrete next steps, each naming a skill, with a
  cost tier (free, run, judge) on each.

Evidence the rubric requires, all of it from `discover.py`'s own output in the
transcript. Judge the facts, not the wording: the response may put them in its
own words, but each of them has to be the one the script printed, and the
script's output has to be in the transcript to check it against.

- the entry point from the script's `## Found` block (`entry_point`), and the
  number of eval cases it counted (`case_count`);
- the credential state the script reported (`credential`: a key, a
  subscription, or none found) and what it means for cost — the script's
  `cost_basis` where it has one, or that no cost basis can be established yet
  where the script reported it unknown;
- the gaps the script's `## Missing` block listed, or an explicit statement
  that it printed none;
- at least one finding id from the script's `## Errors`, `## Warnings` or
  `## Notes` block (`ENV001`, `ENV010`, `DEP003`, …), as the script printed it;
- a cost tier on every next step it offers, in the sense the script's
  `## Options` section uses `cost:` — `free` for something that only reads,
  `run` for something that executes the agent, `judge` for something that adds
  judge calls. The response may offer more or fewer steps than that section
  listed; what the rubric asks is that each one carries its tier.

FAIL if it:

- gives advice before inspecting the project;
- starts writing eval cases, configs or running the suite without being asked;
- states a credential or SDK version it did not verify with a script;
- names a gap, an entry point, a case count, a credential or a finding id that
  the script's output does not support;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
