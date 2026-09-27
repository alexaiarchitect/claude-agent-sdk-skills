"""Tool graders: `tool_used`, `tool_order`, `no_tool`, `trajectory`.

Two measured facts shape every grader here.

1. **`StructuredOutput` is a phantom.** The CLI delivers `output_format` results
   as a synthetic `ToolUseBlock` named `StructuredOutput`. Every grader in this
   module therefore skips names in `SYNTHETIC_TOOLS` unless the grader asks for
   one by name; without that a `no_tool` grader fails on a case that called no
   tool at all.
2. **The subagent tool has two names.** The CLI reports `Task`; the SDK and the
   docs say `Agent`. A grader naming either matches both.

Name matching is also suffix-aware for MCP tools: a grader may write `reserve`
or the full `mcp__library__reserve`, because a case author reading the agent's
`@tool("reserve", ...)` should not have to know the server prefix.
"""

from __future__ import annotations

from typing import Any

from .. import SUBAGENT_TOOL_NAMES, SYNTHETIC_TOOLS
from . import Evidence, GraderResult, not_evaluated, verdict


def aliases(name: str) -> set[str]:
    """Every name that means the same tool as `name`."""
    out = {name}
    if name in SUBAGENT_TOOL_NAMES:
        out.update(SUBAGENT_TOOL_NAMES)
    return out


def name_matches(observed: str, wanted: str) -> bool:
    observed = observed or ""
    for candidate in aliases(wanted):
        if observed == candidate:
            return True
        # `reserve` matches `mcp__library__reserve`, never `unreserve`.
        if observed.startswith("mcp__") and observed.endswith("__" + candidate):
            return True
    return False


def names_wanted(grader: Any) -> list[str]:
    """Every tool name the grader mentions, so a synthetic one can be honoured."""
    mentioned: list[str] = []
    for key in ("tool", "before", "after"):
        value = grader.get(key)
        if isinstance(value, str):
            mentioned.append(value)
    for value in (grader.get("tools") or []):
        mentioned.append(str(value))
    for step in (grader.get("expected") or []):
        if isinstance(step, dict) and step.get("tool"):
            mentioned.append(str(step["tool"]))
    return mentioned


def calls(evidence: Evidence, grader: Any) -> list[dict[str, Any]]:
    """The tool calls this grader may see: synthetic ones only when named."""
    named_synthetic = {n for n in names_wanted(grader) if n in SYNTHETIC_TOOLS}
    out = []
    for event in evidence.tool_uses(include_synthetic=True):
        if event.get("synthetic") and event.get("tool") not in named_synthetic:
            continue
        out.append(event)
    return out


def _subset(expected: Any, actual: Any) -> bool:
    """Is `expected` contained in `actual`? Dicts by key, lists by prefix-free
    membership, scalars by equality (strings case-insensitively contained)."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _subset(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(_subset(item, other) for other in actual) for item in expected)
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() in actual.strip().lower()
    return expected == actual


def input_matches(wanted: Any, actual: dict[str, Any], mode: str = "subset") -> bool:
    if wanted in (None, {}, []):
        return True
    if mode == "ignore":
        return True
    if mode == "exact":
        return wanted == actual
    return _subset(wanted, actual)


def grade_tool_used(grader: Any, evidence: Evidence) -> GraderResult:
    wanted = str(grader.get("tool"))
    minimum = grader.get("min")
    minimum = 1 if minimum is None else int(minimum)
    maximum = grader.get("max")
    maximum = None if maximum is None else int(maximum)
    match_input = grader.get("input_match")
    observed = [
        call for call in calls(evidence, grader)
        if name_matches(str(call.get("tool")), wanted)
        and input_matches(match_input, call.get("input") or {})
    ]
    if grader.get("target") == "mock_calls":
        observed = [
            call for call in evidence.mock_calls
            if name_matches(str(call.get("tool")), wanted)
            and input_matches(match_input, call.get("input") or {})
        ]
    count = len(observed)
    ok = count >= minimum and (maximum is None or count <= maximum)
    ceiling = "" if maximum is None else f" and at most {maximum}"
    return verdict(grader, ok, f"{wanted} called {count}x; expected at least {minimum}{ceiling}")


def grade_tool_order(grader: Any, evidence: Evidence) -> GraderResult:
    before, after = str(grader.get("before")), str(grader.get("after"))
    sequence = [str(call.get("tool")) for call in calls(evidence, grader)]
    first_before = next((i for i, name in enumerate(sequence) if name_matches(name, before)), None)
    first_after = next((i for i, name in enumerate(sequence) if name_matches(name, after)), None)
    if first_before is None or first_after is None:
        missing = [n for n, i in ((before, first_before), (after, first_after)) if i is None]
        return verdict(grader, False, f"never called: {', '.join(missing)} (observed: {sequence or 'no calls'})")
    ok = first_before < first_after
    return verdict(grader, ok,
                   f"{before} at index {first_before}, {after} at index {first_after}"
                   + ("" if ok else " — the order is reversed"))


def grade_no_tool(grader: Any, evidence: Evidence) -> GraderResult:
    banned = [str(t) for t in (grader.get("tools") or [])]
    observed = [str(call.get("tool")) for call in calls(evidence, grader)]
    hits = [name for name in observed if any(name_matches(name, b) for b in banned)]
    return verdict(grader, not hits,
                   "none of the banned tools were called" if not hits
                   else f"called {', '.join(sorted(set(hits)))}")


def grade_trajectory(grader: Any, evidence: Evidence) -> GraderResult:
    expected = [step for step in (grader.get("expected") or []) if isinstance(step, dict)]
    if not expected:
        return not_evaluated(grader, "`expected` is empty or not a list of {tool, args?} mappings")
    if evidence.simulated_user_turns:
        return not_evaluated(
            grader,
            "EVC040: a trajectory grader cannot hold on a simulated-user case — the user's turns "
            "are generated, so the tool sequence is not reproducible",
        )
    mode = str(grader.get("match") or "IN_ORDER").upper()
    args_mode = str(grader.get("args_match") or "subset")
    threshold = grader.get("threshold")
    observed = calls(evidence, grader)
    names = [str(call.get("tool")) for call in observed]

    def step_matches(step: dict[str, Any], call: dict[str, Any]) -> bool:
        return name_matches(str(call.get("tool")), str(step.get("tool"))) and input_matches(
            step.get("args"), call.get("input") or {}, args_mode
        )

    matched = 0
    if mode == "ANY_ORDER":
        pool = list(observed)
        for step in expected:
            for index, call in enumerate(pool):
                if step_matches(step, call):
                    matched += 1
                    pool.pop(index)
                    break
    elif mode == "EXACT":
        # Position for position, and no extra calls (checked below).
        for index, step in enumerate(expected):
            if index < len(observed) and step_matches(step, observed[index]):
                matched += 1
    else:  # IN_ORDER: the expected steps appear in order, extras allowed between
        cursor = 0
        for step in expected:
            while cursor < len(observed) and not step_matches(step, observed[cursor]):
                cursor += 1
            if cursor < len(observed):
                matched += 1
                cursor += 1
    score = matched / len(expected)
    ok = score >= (1.0 if threshold is None else float(threshold))
    detail = f"{matched}/{len(expected)} expected step(s) matched {mode}"
    if mode == "EXACT" and len(observed) != len(expected):
        ok = False
        detail += f"; EXACT wants exactly {len(expected)} call(s), saw {len(observed)}"
    return verdict(grader, ok, f"{detail}. Observed: {names or 'no calls'}", score=score)
