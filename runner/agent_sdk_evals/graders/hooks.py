"""`hook_event`: assert on what the hooks saw.

Measured: `include_hook_events=True` on its own emits nothing. Hook events exist
only for events that actually have a callback registered, so this grader is
NOT_EVALUATED — never FAILED — when the runner's capture hook was not installed
for the event the grader names. A FAILED there would be a lie about the agent.

Only the 10 events in the Python SDK's `HookEvent` literal are valid.
`SessionStart` and `SessionEnd` are not among them (HOK020) even though a
`SessionStartHookSpecificOutput` type exists, so a grader naming one abstains
with that id in its reason.
"""

from __future__ import annotations

from typing import Any

from .. import PYTHON_HOOK_EVENTS
from . import Evidence, GraderResult, not_evaluated, verdict
from .tools import name_matches


def grade_hook_event(grader: Any, evidence: Evidence) -> GraderResult:
    event = str(grader.get("event") or "")
    if event not in PYTHON_HOOK_EVENTS:
        return not_evaluated(
            grader,
            f"HOK020: {event!r} is not one of the Python SDK's hook events "
            f"({', '.join(PYTHON_HOOK_EVENTS)})",
        )
    if event not in evidence.hook_events_installed:
        return not_evaluated(
            grader,
            f"no capture hook was installed for {event}, so the trace carries no evidence either "
            "way; `include_hook_events=True` alone emits nothing",
        )
    records = [r for r in evidence.hook_records() if r.get("event") == event]
    matcher = grader.get("matcher")
    if matcher:
        records = [
            r for r in records
            if r.get("matcher") == matcher or name_matches(str(r.get("tool") or ""), str(matcher))
        ]
    decision = grader.get("decision")
    if decision:
        records = [r for r in records if str(r.get("decision") or "") == str(decision)]
    # Two phases are emitted per firing (`hook_started`, `hook_response`); count firings.
    firings = [r for r in records if r.get("phase") != "hook_started"] or records
    count = len(firings)
    minimum = grader.get("min")
    minimum = 1 if minimum is None else int(minimum)
    maximum = grader.get("max")
    maximum = None if maximum is None else int(maximum)
    ok = count >= minimum and (maximum is None or count <= maximum)
    detail = f"{event} fired {count}x"
    if matcher:
        detail += f" for matcher {matcher!r}"
    if decision:
        detail += f" with decision {decision!r}"
    ceiling = "" if maximum is None else f" and at most {maximum}"
    return verdict(grader, ok, f"{detail}; expected at least {minimum}{ceiling}")
