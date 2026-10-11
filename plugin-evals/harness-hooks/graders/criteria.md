---
type: llm
focus: trace
---

PASS if the response:

- reports the hook findings by id from the linter output, and among them the
  synchronous callback, the callback whose return lacks `hookSpecificOutput`
  with a matching `hookEventName`, and the event name the Python SDK does not
  support;
- explains the correct callback shape for a PreToolUse deny (async, the
  `hookSpecificOutput` dict with `permissionDecision` and a reason) and cites
  the hooks documentation;
- offers to generate a corrected hook with the plugin's generator as a next
  step, and does not write it.

Evidence the rubric requires, from `lint_harness.py` run in the transcript.

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

- each hook defect named by the id the script printed (`HOK001` for the
  synchronous callback, `HOK002` for the unreadable return, `HOK020` for the
  unsupported event), with the script's locator — the linter prints these as
  `agent.py line 41`, `agent.py line 47` and `agent.py hooks[SessionStart] line
  106`, so a bare line number is the locator and satisfies this; a defect
  described in prose with no id at all does not;
- the script's own `Source:` line for the callback contract, which the linter
  prints on `HOK002` (the hooks `#outputs` documentation URL, and the SDK's
  `types.py` line range);
- the generator offered by name (`gen_hook.py`) and not run. This one is the
  skill's next step rather than a line the linter prints, so it is satisfied by
  the response naming the generator; hand-written replacement code offered in
  its place is not.

FAIL if it:

- edits the agent or writes a hook file;
- explains hooks from memory without running the linter;
- presents `SessionStart` as a valid Python SDK hook event;
- names a hook finding id without the linter's output in the transcript, or
  invents an id the linter does not define;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
