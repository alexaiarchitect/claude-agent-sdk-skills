# Reviewing a suite for quality, not just validity

Validation says the files parse and the fields are right. It cannot say whether
the suite is any good. These are the questions a person has to ask, and the
order to ask them in.

## 1. Does each case test one behaviour?

The signals that a case is really two:

* the name contains "and";
* two of its graders can fail for unrelated reasons;
* the prompt asks for more than one thing;
* explaining a failure takes a sentence about *which part* broke.

The cost of splitting is one more run per tier. The cost of not splitting is a
failure report nobody can act on — which is the same as no test at all, but
more expensive.

## 2. Is the id the first thing a reader sees?

A failing case's name is the diagnosis. `refuse-double-booking` tells a reader
what broke before they open anything; `edge-case-3` sends them to the file, and
then to the graders, and then to the trace.

The same applies to grader names: `never_reserves_twice.md` names its claim,
`grader_2.md` names its position in a list that has since changed.

## 3. Could this case pass while the agent is broken?

The three ways it usually can:

* **A grader that asserts nothing.** `no_tool` naming a tool the agent does not
  have; a `regex` that matches any text; a `tool_used` on a tool every run
  calls anyway. `crosscheck_tools.py` finds the first kind.
* **A restraint case scored only on the reply.** A model that called the tool
  and then apologized passes an `llm` grader about the apology (`EVC041`).
* **A case with no graders at all** (`EVC060`), which is usually a case that
  was half-written and committed.

## 4. Could this case fail while the agent is fine?

Brittleness is the other failure mode, and it costs more in attention than in
money:

* an `EXACT` trajectory over a long path — every future run must reproduce it
  exactly;
* a `final_text` grader with `mode: exact` on a generated sentence;
* a `regex` on a phrasing rather than on a fact;
* a `budget` grader with a hard ceiling near the observed cost, which will fire
  on the next price-table update;
* a single-sample `llm` grader on a borderline criterion.

A case that fails for an uninteresting reason twice gets ignored the third
time, and then it is not a test.

## 5. Do the cases and the agent change together?

This is the one that decays. The rules in a system prompt get edited in a pull
request that touches no case; the cases get written in a pull request that
touches no prompt. Nothing enforces the connection.

Two habits that work:

* run `coverage_matrix.py` when the system prompt changes, not on a schedule —
  the diff tells you which rule is new;
* when a case is added for a behaviour, name the rule in the case's
  frontmatter or its first line. The matrix then matches on a phrase you chose
  rather than one it guessed.

## 6. Is the adversarial share holding?

Happy cases are the easy ones to write, and nobody decides to stop writing
adversarial ones — the share just drifts down as the suite grows. The target is
20%, and `coverage_matrix.py` reports the ratio every time.

A suite that is 90% happy paths proves the agent works when nothing goes wrong,
which is not the failure anybody reports.

## 7. Would a stranger understand why this grader exists?

Every grader file's body is two paragraphs: what it proves, and what it does
not. The second one is the one that earns its place — it tells the next person
which other grader has to exist beside this one, and it is the only defence
against a suite of narrow checks with a hole in the middle.

A grader whose body is empty, or is a restatement of its frontmatter, is a
grader nobody will dare to change.

## The review loop

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/validate_cases.py <project> --strict
python3 ${CLAUDE_SKILL_DIR}/scripts/crosscheck_tools.py <project>
python3 ${CLAUDE_SKILL_DIR}/scripts/coverage_matrix.py <project>
```

Validity, then consistency, then coverage. The first two are machine-checkable
and should be clean before the third is worth discussing — there is no point
arguing about which rule needs a case while a grader in the suite asserts
nothing.

Sources: `lib/agent_sdk_skills/evalcase.py` (`EVC041`, `EVC060`, the restraint
detection); `lib/agent_sdk_skills/coverage.py` (`shape`, `n_plus_one_gaps`,
`tool_coverage`); `lib/agent_sdk_skills/graders.py` (the `not_proven` text each
grader type carries); `skills/agent-sdk/references/interaction-protocol.md`
(report before advice).
