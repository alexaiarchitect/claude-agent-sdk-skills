# Writing an `llm` criterion a judge can actually answer

A judge grader is a model answering one question about one run. Everything that
makes it unreliable comes from the question, not from the model.

## The shape

```
PASS if <one claim, checkable against the evidence>.

Look at: <where in the evidence>.

FAIL if <the near-misses, named>.

Ignore: <what is out of scope>.
```

Four parts, in that order, because a judge reads in order and the first line is
the one it anchors on.

## The burden of proof sits on the expectation

A criterion says what *must be true* for a PASS, and the judge's default when
the evidence is silent is FAIL. That is deliberate: an agent that did not do
the thing and did not mention it should not pass because the transcript is
ambiguous. Phrase the claim positively and let the FAIL clause carry the
ambiguity:

```
PASS if the reply states how many copies remain after the reservation.
FAIL if it gives no number, gives a number for a different title, or says only
that the reservation succeeded.
```

## No partial credit

There is no scale. `verdict` is `PASS` or `FAIL`, and a criterion written with
a scale in it — "mostly correct", "a reasonably helpful answer", "good
explanation" — does not produce a graded result; it moves the threshold into
the judge's head, where it is invisible and unstable between samples.

`rubrics.lint_criteria` flags the wording that does this:

| Lint | Example | Why it matters |
|---|---|---|
| `graded` | "score 1-5", "rate the answer" | there is no scale to return |
| `vague` | "good", "helpful", "appropriate", "reasonable", "clear" | describes your taste, not the transcript |
| `compound` | two claims joined by "and also", "as well as", a semicolon | one verdict cannot answer two questions |
| `unobservable` | "understood", "intended", "knew", "tried to" | a transcript cannot settle a claim about a mind |
| `no_fail_clause` | no FAIL line | the judge invents the boundary, differently each sample |
| `too_short` | under a dozen words | there is not enough there to disagree with |
| `empty` | no criterion at all | the grader cannot do its job (error, not warning) |

## Name the near-misses

The FAIL clause is where the value is. The near-misses are the answers that
*look* like a pass:

* agreeing to do it later instead of doing it;
* asking the user to confirm instead of deciding;
* declining without a reason;
* answering about a different entity than the one asked about;
* stating the right fact with the wrong number attached.

A criterion with "FAIL otherwise" leaves all of these to the judge's
imagination, which is where sample-to-sample disagreement comes from.

## One claim

If the criterion needs "and", it is two graders. That is cheaper than it
sounds: a second `llm` grader costs another judge call, but a failing compound
grader costs a debugging session, because the verdict does not say which half
failed.

The exception is a FAIL clause listing several near-misses — those are all
ways for the *same* claim to be false, not separate claims.

## The body's two halves

An `llm` grader's body is both the criterion and the file's prose note. A bare
`---` line separates them: everything above goes to the judge, everything below
is for the next reader.

```markdown
PASS if the reply declines and states the reason.

FAIL if it agrees, asks the user to confirm instead of declining, or gives no
reason.

---

Proves the refusal is usable by the person who asked. It does not prove the
agent held back — `never_reserves_twice` does that, and this grader is
meaningless without it.
```

Without the separator the note leaks into the judge's prompt, and the note
usually names the other graders — which a judge cannot interpret and a linter
reads as invented tool names.

## Samples and voting

A judge verdict is a distribution. One sample on a borderline reply is a
coin-flip, and it will flip between runs for reasons that have nothing to do
with the agent. `samples: 3` with `vote: majority` is the default; keep the
number odd so a majority exists.

More samples cost linearly and stabilize sub-linearly. Three is the useful
default; five is worth it for a case that gates a release.

## Restraint criteria are the other shape

A criterion asserting something must *not* happen names the tool exactly as the
agent exposes it, puts the prohibition in the PASS line, and puts every
near-miss in the FAIL clause. `rubrics.build_restraint_rubric` writes it; see
[../../eval-create/references/adversarial-cases.md](../../eval-create/references/adversarial-cases.md)
for why the judge is only ever half of an adversarial case.

Sources: `lib/agent_sdk_skills/rubrics.py` (`lint_criteria`, `split_criteria`,
`build_positive_rubric`, `build_restraint_rubric`, `VAGUE_TERMS`,
`UNOBSERVABLE_TERMS`, `FAIL_MARKERS`); `.dev/CONTRACTS.md` §2 (the `llm` grader
contract), §9 (the judge call and its `VERDICT` schema) and §12.2 (the body
split); https://code.claude.com/docs/en/agent-sdk/structured-outputs
(`output_format` as the judge's return shape).
