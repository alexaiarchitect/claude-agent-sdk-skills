"""The grader registry and the evidence every grader reads.

One module per family: `text` (regex, final_text), `tools` (tool_used,
tool_order, no_tool, trajectory), `files` (file_exists), `output`
(structured_output), `budget`, `hooks` (hook_event), `terminal`, and `llm` (the
only judge-tier family, the only one that spends anything).

Four statuses, never merged: PASSED, FAILED, NOT_EVALUATED (the evidence the
grader needs does not exist — an imported session has no cost, a `hook_event`
grader ran without its hook installed, a judge call errored) and INFORMATIONAL
(a `budget` grader with `informational: true`: reported, never a gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .. import FAILED, INFORMATIONAL, NOT_EVALUATED, PASSED


@dataclass
class Evidence:
    """Everything a grader may look at, assembled once per run."""

    last_message: str = ""
    assistant_texts: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    run_cwd: Path | None = None
    case_dir: Path | None = None
    mock_calls: list[dict[str, Any]] = field(default_factory=list)
    hook_events_installed: set[str] = field(default_factory=set)
    case_cost_usd: float = 0.0
    simulated_user_turns: list[str] = field(default_factory=list)
    from_session: bool = False

    def tool_uses(self, *, include_synthetic: bool = False) -> list[dict[str, Any]]:
        return [
            e for e in self.events
            if e.get("type") == "tool_use" and (include_synthetic or not e.get("synthetic"))
        ]

    def hook_records(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("type") == "hook"]

    @property
    def structured_output(self) -> Any:
        return (self.result or {}).get("structured_output")


@dataclass
class GraderResult:
    """One grader's verdict, as it appears in `<case>.result.json`."""

    name: str
    type: str
    status: str
    score: float = 0.0
    reason: str = ""
    votes: list[str] | None = None
    tier: str = "free"
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name, "type": self.type, "status": self.status, "score": self.score,
        }
        if self.votes is not None:
            payload["votes"] = self.votes
        if self.reason:
            payload["reason"] = self.reason
        if self.cost_usd:
            payload["cost_usd"] = round(self.cost_usd, 6)
        return payload

    @property
    def gating(self) -> bool:
        """INFORMATIONAL and NOT_EVALUATED never decide a run's status."""
        return self.status in (PASSED, FAILED)


def verdict(grader: Any, ok: bool, reason: str, *, score: float | None = None) -> GraderResult:
    """Build a PASSED/FAILED result, honouring `informational: true`."""
    if grader.get("informational"):
        status = INFORMATIONAL
    else:
        status = PASSED if ok else FAILED
    return GraderResult(
        name=grader.name, type=grader.type, status=status,
        score=(1.0 if ok else 0.0) if score is None else score,
        reason=reason, tier=grader.tier,
    )


def not_evaluated(grader: Any, reason: str) -> GraderResult:
    return GraderResult(name=grader.name, type=grader.type, status=NOT_EVALUATED,
                        score=0.0, reason=reason, tier=grader.tier)


def _registry() -> dict[str, Callable[..., GraderResult]]:
    from . import budget as _budget
    from . import files as _files
    from . import hooks as _hooks
    from . import output as _output
    from . import terminal as _terminal
    from . import text as _text
    from . import tools as _tools

    return {
        "regex": _text.grade_regex,
        "final_text": _text.grade_final_text,
        "tool_used": _tools.grade_tool_used,
        "tool_order": _tools.grade_tool_order,
        "no_tool": _tools.grade_no_tool,
        "trajectory": _tools.grade_trajectory,
        "file_exists": _files.grade_file_exists,
        "structured_output": _output.grade_structured_output,
        "budget": _budget.grade_budget,
        "hook_event": _hooks.grade_hook_event,
        "terminal": _terminal.grade_terminal,
    }


def grade_free(grader: Any, evidence: Evidence) -> GraderResult:
    """Run one free grader. Unknown types never crash a suite; they abstain."""
    handler = _registry().get(grader.type)
    if handler is None:
        return not_evaluated(grader, f"no free grader implements type {grader.type!r}")
    try:
        return handler(grader, evidence)
    except Exception as exc:  # a grader bug must not lose the run's evidence
        return not_evaluated(grader, f"grader raised {type(exc).__name__}: {exc}")


__all__ = [
    "Evidence", "GraderResult", "grade_free", "verdict", "not_evaluated",
    "PASSED", "FAILED", "NOT_EVALUATED", "INFORMATIONAL",
]
