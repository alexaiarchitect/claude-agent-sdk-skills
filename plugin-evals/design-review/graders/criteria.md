---
type: llm
focus: trace
---

PASS if the response:

- reports the design findings by id from `design_check.py` output, and among
  them the list tool with no limit (`DSG003` on `list_books`), the overlapping
  tools (`DSG005` on `lookup`, `find_book`, `search_books`) and the ambiguous
  `id` parameter (`DSG002` on `lookup`);
- states a keep-or-fold decision for the `catalog-search` subagent, with a
  reason tied to context — whether the search needs a fresh, parallel or
  disposable context window and returns a compact result — rather than to
  problem type ("search is a separate concern"); either decision passes when
  the reason is context-based;
- cites at least one Anthropic article (by title or URL) and the Agent SDK
  subagents documentation (`code.claude.com/docs/en/agent-sdk/subagents`);
- offers any change as a next step and writes nothing.

Evidence the rubric requires, from `design_check.py` or `design_brief.py` run in
the transcript.

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

- each named finding by the id the script printed (`DSG003` for `list_books`,
  `DSG005` for the overlap, `DSG002` for the `id` parameter), with the script's
  locator or tool name — the script prints `agent.py line 59` and
  `agent.py line 64`, so a bare line number or the tool's name satisfies this; a
  defect described in prose with no id at all does not;
- the article citation: the script prints a `Source:` line per finding naming
  the article's title, date and URL, and `design_brief.py` prints a `Sources:`
  line; the subagents documentation URL appears on `DSG007`'s `Source:` line and
  in the brief. Naming them in the response from that output satisfies this;
- the keep-or-fold decision is the response's own reasoning, not a line the
  script prints, so it is satisfied by the response stating it with a
  context-based reason; `design_brief.py`'s keep-or-fold table is the expected
  basis but quoting it is not required.

FAIL if it:

- edits `agent.py` or writes any file;
- reviews the tool set from memory without running the design script;
- decides keep or fold on problem type alone ("search is a different job", "a
  separate team owns it") with no context-based reason;
- names a `DSG` id without the script's output in the transcript, or invents an
  id the script does not define;
- gives advice, or a verdict, without running the plugin's script: anything
  the rubric above asks for by name has to come from script output shown in
  the transcript, not from the model's own knowledge of the SDK.
