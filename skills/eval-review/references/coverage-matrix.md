# The coverage matrix: rules against cases

Cases get written from what the agent *does*. Rules get written from what it
*must*. Nothing in the repository connects the two, so the connection has to be
made deliberately and periodically, or a suite grows past twenty cases without
touching the rule that matters most.

## How the matrix is built

1. **Read the system prompt** with `ast` — never by importing the agent. A
   module-level `SYSTEM_PROMPT = "..."`, or a literal `system_prompt=` keyword.
2. **Extract the rules**: numbered or bulleted items, an indented line
   continuing the one above. A prompt written as prose has no markers, so
   sentences carrying an obligation word (`must`, `never`, `only`, `before
   you`) are used instead — and marked `kind: sentence`, because that fallback
   is a guess and the report should say which it is looking at.
3. **Flag each rule**: `is_refusal` (`never`, `refuse`, `do not`, `must not`,
   `without`), `is_ordering` (`before`, `only after`, `first`, `until`).
4. **Summarize each case**: its prompt, its turns, its tags, its grader bodies
   and the tool names its graders assert about.
5. **Match**: a rule is *aimed at* by a case when the case mentions one of the
   rule's tools, or **two** of its key phrases. Two, because one phrase is a
   coincidence — "book" appears in every case of a library agent.

## What "covered" does and does not mean

Covered means *somebody wrote a case for this rule*. It does not mean the rule
holds, that the case would catch a violation, or that the grader is any good.
The matrix prints the matched tools and phrases for every row precisely so you
can disagree with it on a specific line.

That is also why gaps are advice: `coverage_matrix.py` exits 0 with gaps unless
you pass `--strict`. A rule the matrix calls uncovered may be covered by a case
that words it differently, and only a person can tell.

## When the prompt cannot be read

If the system prompt is built at runtime — an f-string over a database, a file
read, a `{"type": "preset"}` mapping — there are no rules to extract. The
report says `unknown`, not zero, and raises a gap explaining the difference.
Reporting "0 of 0 rules covered" as a pass would be the worst possible answer.

The fix, if you want the matrix: move the static part of the prompt into a
module-level constant. That also makes it reviewable in a pull request, which
is worth more than the matrix.

## Suite shape

Two targets, both defaults:

* **one case of each category** — `happy`, `edge`, `adversarial`, `memory`,
  `regression`. A missing category is a missing claim.
* **adversarial cases at 20% or more.** This is the one that decays. Happy
  cases are the easy ones to write, and nobody decides to stop writing
  adversarial ones; the share just drifts down.

Cases with no `category` are reported separately: they are invisible to both
the tier filter and this report.

## The n+1 rule

For n rules you need n cases that exercise them, plus **one case per refusal
rule that attempts the forbidden action**. The matrix reports two distinct
failures here:

* `no_case` — nothing aims at this refusal rule at all.
* `no_trace_check` — a case aims at it, but only the reply is scored. A model
  that called the tool and then apologized passes. The fix is to add a
  `no_tool` grader, or set the trajectory grader's `match: EXACT` — keeping the
  `llm` grader, which proves the explanation.

## Tool coverage

Every tool the agent exposes should be named by at least one grader. A tool no
case asserts about can be removed, renamed or broken with nothing noticing, and
its behaviour is unspecified by definition.

When the tool list cannot be read statically the report says `unknown` and
skips the check, rather than reporting every tool as untested.

## Using it

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/coverage_matrix.py <project>
```

Read it before writing a case, not after. The highest-value case to write next
is almost always an adversarial one for a refusal rule in the `n+1` list —
those are the rules that fail silently, and the ones a model upgrade is most
likely to take away.

Sources: `lib/agent_sdk_skills/coverage.py` (`read_system_prompt`,
`extract_rules`, `matrix`, `shape`, `n_plus_one_gaps`, `tool_coverage`, and the
20% target); `lib/agent_sdk_skills/evalcase.py` (`CATEGORIES`, `case_summary`);
`lib/agent_sdk_skills/options_ast.py` (`system_prompt_kind`, which reports the
kind of prompt but not its text);
https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts (the three
forms a system prompt can take).
