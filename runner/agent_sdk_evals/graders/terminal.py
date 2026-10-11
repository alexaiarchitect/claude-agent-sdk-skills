"""`terminal`: how the session ended.

This is the grader that asserts a limit tripped, which `budget` deliberately
cannot: `subtype: error_max_turns` or `terminal_reason: max_turns` is the honest
way to say "the turn ceiling stopped it", because `num_turns` can exceed
`max_turns` on a successful run.

`terminal_reason` is `null` on older CLIs and on local slash commands, so a
grader that asks for one and gets nothing abstains instead of failing. The same
goes for a result synthesised from an imported session's `cost-state` line
(`imported_cost: true`): it carries the cost and nothing else, so this grader
abstains on one outright.
"""

from __future__ import annotations

from typing import Any

from . import Evidence, GraderResult, not_evaluated, verdict


def grade_terminal(grader: Any, evidence: Evidence) -> GraderResult:
    result = evidence.result
    if result is None:
        return not_evaluated(
            grader,
            "no result message: an imported session has no terminal state to assert on",
        )
    if result.get("imported_cost"):
        return not_evaluated(
            grader,
            "the result was synthesised from an imported session's `cost-state` line: it "
            "carries the session cost but no subtype, terminal_reason or num_turns, so a "
            "`budget` grader can be decided on it and this one cannot",
        )
    problems: list[str] = []
    observed: list[str] = []

    wanted_subtype = grader.get("subtype")
    if wanted_subtype is not None:
        allowed = [str(s) for s in (wanted_subtype if isinstance(wanted_subtype, list) else [wanted_subtype])]
        actual = result.get("subtype")
        observed.append(f"subtype={actual!r}")
        if str(actual) not in allowed:
            problems.append(f"subtype {actual!r} is not one of {allowed}")

    wanted_reason = grader.get("terminal_reason")
    if wanted_reason is not None:
        allowed = [str(s) for s in (wanted_reason if isinstance(wanted_reason, list) else [wanted_reason])]
        actual = result.get("terminal_reason")
        observed.append(f"terminal_reason={actual!r}")
        if actual is None:
            return not_evaluated(
                grader,
                "`terminal_reason` is null (older CLI, or a local slash command), so the grader "
                "cannot be decided; assert on `subtype` instead",
            )
        if str(actual) not in allowed:
            problems.append(f"terminal_reason {actual!r} is not one of {allowed}")

    if not grader.get("allow_error") and result.get("is_error"):
        problems.append("the result is flagged is_error and the grader does not set allow_error")
        observed.append("is_error=True")

    return verdict(grader, not problems,
                   ("; ".join(problems)) if problems else "terminal state as expected (" + ", ".join(observed) + ")")
