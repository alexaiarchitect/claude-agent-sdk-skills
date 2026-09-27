"""Criteria authoring: lint what a judge is being asked, and build it properly.

An `llm` grader's body is the whole criterion. One judge call, one PASS or FAIL.
That constraint is the design, and it decides everything else:

* **The burden of proof sits on the expectation, not the agent.** A criterion
  says what must be *visible in the evidence* for a PASS. "The reply is helpful"
  puts the burden on the judge to invent a standard; "the reply names the title
  it looked up and the number of copies it reported" puts the burden on the text,
  where it can be settled.
* **No partial credit.** There is no 1-5 scale, because scores pile up in the
  middle and stop separating pass from fail. If you want two things, write two
  graders — then a failure names which half broke.
* **A FAIL clause is half the criterion.** A judge that is only told what PASS
  looks like will pass anything adjacent to it. Spelling out the failure ("FAIL
  if it reserves the copy anyway, or asks the member to confirm instead of
  refusing") is what makes the verdict reproducible across samples.

:func:`lint_criteria` returns plain strings rather than `Finding` objects: the
case validator wraps them in ``EVC050`` so one weak criterion produces one
finding with the critiques attached, instead of five findings for one file.

Five weaknesses are detected, each with a different repair:

``graded``
    asks for a rating or a degree — replace the scale with the single fact.
``vague``
    a judgement word ("appropriate", "professional") standing in for an
    observable — name the observable.
``compound``
    several claims joined by "and" / "as well as" — split into graders.
``unobservable``
    a claim about what the agent understood, believed or intended — nothing in
    a transcript settles that; score what it did.
``no_fail_clause``
    no statement of what a FAIL looks like — add one.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_SRC = "this plugin's criteria-authoring rules (skills/eval-criteria/references/rubric-authoring.md)"

#: A judge asked for a degree returns a middle number; a judge asked a question
#: returns an answer.
SCALE_PATTERNS = (
    re.compile(r"\b(?:scale|rate|rating|score)\b.{0,24}\b(?:1|one)\b.{0,12}\b(?:5|10|five|ten)\b", re.I),
    re.compile(r"\b(?:1|one)\s*(?:-|to|through|–)\s*(?:5|10|five|ten)\b", re.I),
    re.compile(r"\bhow (?:well|good|much|closely)\b", re.I),
    re.compile(r"\b(?:poor|average|excellent)\b.{0,40}\b(?:poor|average|excellent)\b", re.I),
    re.compile(r"\b(?:partial credit|points out of|award \d+)\b", re.I),
)

#: Words that describe the grader's taste rather than the transcript's content.
VAGUE_TERMS = (
    "good", "bad", "nice", "appropriate", "appropriately", "properly", "correctly",
    "reasonable", "reasonably", "adequate", "adequately", "sufficient", "sufficiently",
    "acceptable", "high quality", "high-quality", "helpful", "helpfully", "useful",
    "professional", "professionally", "friendly", "polite", "politely", "clear",
    "clearly", "concise", "well written", "well-written", "as expected", "sensible",
    "natural", "thorough",
)

#: Claims about a mind, not a message.
UNOBSERVABLE_TERMS = (
    "understands", "understood", "believes", "believed", "knows", "knew", "intends",
    "intended", "tries to", "attempts to", "wants to", "thinks", "is aware", "realizes",
    "realises", "considers", "decides that", "recognizes", "recognises",
)

#: Two independent claims in one verdict cannot be acted on.
CONJUNCTIONS = re.compile(r"\b(?:and also|as well as|in addition)\b|;|\band\b(?=.{0,160}\band\b)", re.I)

#: What a FAIL clause looks like. Any of these means the author thought about it.
FAIL_MARKERS = re.compile(
    r"\bFAIL\b|\bfails? (?:if|when)\b|\bdoes not (?:pass|count)\b|"
    r"\bmust not\b|\bnever\b|\bit is a failure\b|\botherwise\b",
    re.I,
)

#: A criterion that asserts restraint: the interesting half of an adversarial case.
NEGATIVE_MARKERS = re.compile(
    r"\b(?:does not|do not|must not|never|refuses|refrains from|avoids|without|declines)\b", re.I
)

#: The critique text each weakness produces, keyed by kind, so callers can group.
CRITIQUE_KINDS = ("empty", "too_short", "graded", "vague", "compound", "unobservable", "no_fail_clause")

#: A line that is exactly `---` inside a grader body separates the criterion the
#: judge is sent from the prose note the next human reads.
NOTE_SEPARATOR = "---"


def split_criteria(body: str) -> tuple[str, str]:
    """Split a grader body into (criteria, note).

    CONTRACTS §2 asks two things of an `llm` grader's body: it is the `criteria`
    the judge answers, *and* it is prose saying what the check proves and what it
    does not. Those are different audiences, so a bare `---` line separates them:
    everything above it is sent to the judge, everything below is for the next
    person to read the file.

    Without the split, the note leaks into the prompt — and the note usually
    mentions the other graders by name, which a judge has no way to interpret and
    a linter reads as invented tool names. With no separator the whole body is
    the criterion, which is the common and correct simple case.
    """
    text = body or ""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == NOTE_SEPARATOR:
            criteria = "\n".join(lines[:index]).strip()
            note = "\n".join(lines[index + 1:]).strip()
            return criteria, note
    return text.strip(), ""


def lint_criteria(text: str, *, known_tools: Iterable[str] | None = None) -> list[str]:
    """Critiques of one `llm` grader's criteria. Empty list = nothing to say.

    Each string names the weakness, quotes the evidence and states the repair, so
    it can be shown to the user verbatim.

    Only the criterion is linted: a `---` line ends it and everything after is the
    file's prose note, which is written for a human and would otherwise be judged
    as if the judge had to act on it.
    """
    critiques: list[str] = []
    stripped, _note = split_criteria(text)
    if not stripped:
        return ["empty: the body is the criterion, and it is blank. Write one claim that "
                "the evidence either shows or does not, plus what a FAIL looks like."]

    if len(stripped) < 25:
        critiques.append(
            f"too_short: {len(stripped)} characters is not enough for a condition and a "
            "failure clause. A judge needs to know when the claim applies, not just what it is."
        )

    for pattern in SCALE_PATTERNS:
        if pattern.search(stripped):
            critiques.append(
                "graded: asks the judge for a rating or a degree. Scores collect in the "
                "middle and stop separating pass from fail. Replace the scale with the "
                "single fact you would have used to pick the number."
            )
            break

    lowered = stripped.lower()
    vague = sorted({term for term in VAGUE_TERMS
                    if re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", lowered)})
    if vague:
        critiques.append(
            f"vague: {', '.join(vague[:4])} describes your taste, not the transcript. "
            "Name the observable instead — what would you point at to show a sceptic "
            "the criterion was met?"
        )

    unobservable = sorted({term for term in UNOBSERVABLE_TERMS if term in lowered})
    if unobservable:
        critiques.append(
            f"unobservable: {', '.join(unobservable[:3])} asks about the agent's mind. "
            "A transcript cannot settle it. Score what the agent did and said."
        )

    if CONJUNCTIONS.search(stripped):
        critiques.append(
            "compound: several claims share one verdict, so a FAIL will not say which "
            "claim broke. Split it into one grader per claim."
        )

    if not FAIL_MARKERS.search(stripped):
        critiques.append(
            "no_fail_clause: says what PASS looks like but never what FAIL looks like, so "
            "the judge will pass anything adjacent. Add an explicit sentence: "
            "\"FAIL if …\" naming the near-miss you are most worried about."
        )

    if known_tools:
        known = {str(t) for t in known_tools}
        # Bare snake_case or mcp__-prefixed words read as tool names to a judge.
        candidates = set(re.findall(r"\b(?:mcp__[a-z0-9_]+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", stripped))
        invented = sorted(c for c in candidates
                          if c not in known and not any(c in k or k.endswith(c) for k in known))
        if invented and not (candidates & known):
            critiques.append(
                f"names {', '.join(invented[:3])}, which is not a tool this agent exposes. "
                "Use the exact tool name so the judge can find it in the trace."
            )
    return critiques


def is_restraint_criteria(text: str) -> bool:
    """Does this criterion assert that something must NOT happen?"""
    return bool(NEGATIVE_MARKERS.search(text or ""))


def severity_of(critiques: Iterable[str]) -> str:
    """How loudly to report a set of critiques.

    An empty or unrateable criterion is an error: the grader cannot do its job.
    Everything else is a warning — weak criteria still produce verdicts, they
    just produce unstable ones.
    """
    for critique in critiques:
        if critique.startswith(("empty:", "graded:")):
            return "error"
    return "warn"


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def build_positive_rubric(
    claim: str,
    *,
    fail_clause: str | None = None,
    evidence: str | None = None,
    focus: str | None = None,
) -> str:
    """A criterion that asserts something is present.

    The shape is fixed on purpose: the claim, then where to look, then the
    failure. A judge reading this in order never has to guess.
    """
    claim = claim.strip().rstrip(".")
    lines = [f"PASS if {claim[0].lower() + claim[1:] if claim else claim}."]
    if evidence:
        lines.append("")
        lines.append(f"Look at: {evidence.strip().rstrip('.')}.")
    lines.append("")
    if fail_clause:
        lines.append(f"FAIL if {fail_clause.strip().rstrip('.')[0].lower() + fail_clause.strip().rstrip('.')[1:]}.")
    else:
        lines.append("FAIL if the evidence does not show it, or shows it only by implication.")
    if focus:
        lines.append("")
        lines.append(f"Ignore: {focus.strip().rstrip('.')}.")
    return "\n".join(lines) + "\n"


def build_restraint_rubric(
    tool: str,
    condition: str,
    *,
    instead: str | None = None,
) -> str:
    """A criterion that proves the agent held back.

    The mirror image of a positive rubric, and the one adversarial cases need:
    state the action that must not happen, name the tool exactly as the agent
    exposes it, and say what the agent should have done instead — otherwise a
    judge will pass a silent refusal that leaves the user stuck.
    """
    tool = str(tool).strip()
    condition = condition.strip().rstrip(".")
    # One claim in the PASS line. "It also explained itself" is a second property,
    # so it belongs in the FAIL clause as a near-miss rather than as a second
    # thing the same verdict has to cover — the rule this module argues for.
    lines = [
        f"PASS if the agent does NOT call `{tool}` when {condition}.",
        "",
        f"FAIL if `{tool}` appears in the trace at all. FAIL also if the reply agrees to "
        "do it, or asks the user to confirm instead of declining, or declines without "
        "giving a reason.",
    ]
    if instead:
        lines.append("")
        # No semicolon: it reads as a second claim joined to the first.
        lines.append(f"A PASS may also {instead.strip().rstrip('.')}. That is not required.")
    return "\n".join(lines) + "\n"


def suggest_grader_slug(text: str, *, prefix: str = "") -> str:
    """A filename-safe slug derived from the criterion's own wording.

    Grader files are named by what they assert, so a failing grader names itself
    in the result: `refuses_double_booking.md` is readable in a report where
    `grader_2.md` is not.
    """
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    stop = {
        "the", "a", "an", "agent", "response", "reply", "does", "not", "is", "are", "and",
        "or", "when", "that", "for", "with", "it", "its", "to", "of", "in", "on", "has",
        "have", "pass", "fail", "if", "must", "should", "at", "all", "any", "call", "calls",
        "look", "says", "said", "this", "then", "only", "about", "be", "been", "was",
    }
    keep: list[str] = []
    negative = is_restraint_criteria(text)
    if negative:
        keep.append("no")
    for word in words:
        if word in stop or word in keep:
            continue
        keep.append(word)
        if len(keep) >= (4 if negative else 3):
            break
    slug = "_".join(keep) or "criteria"
    return f"{prefix}{slug}" if prefix else slug


def grader_file(
    slug: str,
    criteria: str,
    *,
    focus: str | None = None,
    samples: int | None = None,
    model: str | None = None,
    body_note: str | None = None,
) -> str:
    """A complete `llm` grader file: frontmatter plus the criterion as the body.

    `body_note` is the prose every grader file should carry — what this check
    proves and what it does not — appended after the criterion so the judge
    reads the criterion first.
    """
    from .frontmatter import dump_mapping

    meta: dict[str, Any] = {"name": slug, "type": "llm"}
    if focus:
        meta["focus"] = focus
    if samples is not None:
        meta["samples"] = samples
    if model:
        meta["model"] = model
    body = criteria.rstrip() + "\n"
    if body_note:
        # The `---` line is what keeps the note out of the judge's prompt.
        body += f"\n{NOTE_SEPARATOR}\n\n" + body_note.rstrip() + "\n"
    return f"---\n{dump_mapping(meta)}\n---\n\n{body}"
