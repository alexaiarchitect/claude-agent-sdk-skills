"""The `llm` grader: the only judge-tier family, and the only one that spends.

The criteria are the grader's **body**, not a frontmatter field, so a rubric can
be as long as it needs to be and still read as prose. `focus` narrows it,
`samples` overrides the config's vote count, `model` overrides the judge model
for this one grader.

`target` chooses the evidence: `last_message` (default), `trace` (the whole
event stream, which is what a "did it follow the right process" rubric needs),
or `{source: file, path: ...}` for something the run wrote.
"""

from __future__ import annotations

from typing import Any

from .. import INFORMATIONAL, PASSED
from . import Evidence, GraderResult, not_evaluated
from .text import target_text


def criteria_of(grader: Any) -> str:
    """The judge's criteria: the body above a bare `---` line.

    A grader body serves two audiences (CONTRACTS §12.2): everything above a
    bare `---` goes to the judge, everything below is the reader's note about
    what the check proves. Without a separator the whole body is the criteria.
    """
    body = (grader.body or "").strip() or str(grader.get("criteria") or "")
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[:index]).strip()
    return body.strip()


async def grade_llm(grader: Any, evidence: Evidence, judge: Any) -> GraderResult:
    if judge is None:
        return not_evaluated(grader, "the judge tier was not selected for this run")
    criteria = criteria_of(grader)
    if not criteria:
        return not_evaluated(grader, "the grader body carries no criteria")
    text, why = target_text(grader.get("target") or "last_message", evidence)
    if text is None:
        return not_evaluated(grader, why)
    if not text.strip():
        return not_evaluated(grader, "the evidence for this grader is empty, so there is nothing to judge")
    outcome = await judge.run(
        criteria, text,
        focus=grader.get("focus"),
        samples=grader.get("samples"),
        model=grader.get("model"),
    )
    status = outcome.status
    if grader.get("informational") and status == PASSED:
        status = INFORMATIONAL
    return GraderResult(
        name=grader.name, type=grader.type, status=status,
        score=1.0 if status == PASSED else 0.0,
        reason=outcome.reason, votes=outcome.votes or None,
        tier="judge", cost_usd=outcome.cost_usd,
    )
