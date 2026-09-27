"""`file_exists`: did the run leave the artefact behind?

The path is a glob resolved against the run's own fresh working directory, so a
case can assert a side effect without trusting the agent's description of it.
Without a working directory — a replayed trace, an imported session — there is
nothing to look at and the grader abstains rather than failing.
"""

from __future__ import annotations

from typing import Any

from . import Evidence, GraderResult, not_evaluated, verdict


def grade_file_exists(grader: Any, evidence: Evidence) -> GraderResult:
    if evidence.run_cwd is None or not evidence.run_cwd.is_dir():
        return not_evaluated(
            grader,
            "no run working directory to look in (a replayed trace keeps no files; "
            "re-run the case with --keep-cwd to inspect them)",
        )
    pattern = str(grader.get("path") or "")
    if not pattern:
        return not_evaluated(grader, "`path` is empty")
    hits = sorted(str(p.relative_to(evidence.run_cwd)) for p in evidence.run_cwd.glob(pattern))
    minimum = int(grader.get("min") or 1)
    ok = len(hits) >= minimum
    return verdict(grader, ok,
                   f"{len(hits)} path(s) matched {pattern!r}"
                   + (f": {', '.join(hits[:5])}" if hits else " (nothing matched)"))
