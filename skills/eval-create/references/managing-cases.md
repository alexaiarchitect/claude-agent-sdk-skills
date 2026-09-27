# Keeping a suite maintainable

A suite is a directory of directories, so every maintenance operation is a file
move. `manage_cases.py` exists because three of them are easy to get subtly
wrong by hand.

## A case's identity is its `name`

Result files are keyed by the `name` in the frontmatter, not by the directory.
Rename the directory and leave `name:` alone and you get two cases that look
distinct in a listing and overwrite each other's results — and `validate_suite`
reports `EVC002` ("two cases are both named …") only when both still exist.

`manage_cases.py rename --from A --to B` moves the directory *and* rewrites the
frontmatter, which is the only safe order.

Directory names stay lowercase and hyphenated: `--case` on the runner and `-k`
in pytest both take them as literal strings, and a name with a space or a
capital behaves differently in different shells.

## Deleting a case deletes evidence

A case is the record that someone once decided a behaviour mattered. Deleting
it is not the same as deleting a test that duplicates another — it removes the
only trace of that decision.

So `delete` and `rename` refuse without `--yes` and print what they would do
instead. When a case is genuinely obsolete, consider two alternatives first:

* **Move it to `regression`.** A case for a behaviour that is no longer a
  headline feature is still worth one run a night.
* **Narrow it.** A case failing for a reason you no longer care about usually
  has one grader too many, not one case too many.

## Duplicates

`dedupe` compares **normalized prompt bodies** — whitespace-insensitive,
case-insensitive — and nothing else. Two cases with the same prompt cost twice
per run and prove one thing.

It deliberately does not fuzzy-match. A one-word difference between two prompts
is often the whole point of the second case, and a deduplicator that guesses
will delete cases people meant to keep.

It also **never merges graders**. When two duplicates assert different things,
the right outcome is one case carrying both graders, and that is an edit a
person should make and read. `dedupe --yes` keeps the first of each group in
directory order and removes the rest; without `--yes` it reports and exits 1.

## When a case should be split

One behaviour per case. The signals that a case is two:

* The name has an "and" in it.
* Two graders can fail for unrelated reasons.
* The prompt asks for more than one thing.
* A failure report requires a sentence to explain *which part* broke.

The cost of splitting is one more run per tier. The cost of not splitting is a
failure nobody can act on.

## When a case should be deleted

* It asserts something the agent no longer does, by decision rather than by
  regression — and the decision is recorded somewhere else.
* It is a duplicate whose graders are a subset of another case's.
* It never fails and never could: a case whose graders are all trivially true
  (`no_tool` naming a tool the agent does not have, a `regex` matching
  anything). `validate_cases.py` finds these as `EVC020` and `EVC060`.

## Reviewing the suite periodically

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/manage_cases.py <project> list
python3 ${CLAUDE_SKILL_DIR}/../eval-review/scripts/validate_cases.py <project>
python3 ${CLAUDE_SKILL_DIR}/../eval-review/scripts/coverage_matrix.py <project>
```

The three questions, in order: what is here, is it valid, and does it cover the
rules the agent is supposed to follow. The third is the one that quietly drifts
— cases are added when a feature ships and rules are added when a prompt is
edited, and nothing connects the two but a periodic look.

Sources: `lib/agent_sdk_skills/evalcase.py` (`iter_cases`, `case_summary`,
`validate_suite`, the duplicate-name `EVC002` and the no-graders `EVC060`);
`lib/agent_sdk_skills/coverage.py` (`summarize_cases`, `shape`);
`.dev/CONTRACTS.md` §1 (the `name` key and how results are keyed).
