"""Compare what the agent did against what it should have done, and name the shape.

A trajectory is the ordered list of tool calls, with arguments. Comparing it
answers a different question from "was the answer right", and the difference is
the whole point: an agent can produce a correct-looking answer while skipping the
check that made it correct, and only the trajectory shows that. The quadrant at
the bottom of this module is how to read the two answers together.

Three match modes:

``EXACT``
    same calls, same arguments, same order, nothing extra. The mode an
    adversarial case needs — anything looser lets the forbidden call slip in
    between the expected ones.
``IN_ORDER`` (the default)
    every expected call appears in the expected relative order; extra calls in
    between are allowed. Right when a retry or a self-correction is legitimate.
``ANY_ORDER``
    every expected call appears; order irrelevant.

And three argument modes: ``exact`` (dicts must be equal), ``subset`` (the
default: the expected keys must match, extra actual keys are fine) and ``ignore``.
`subset` is the default because an expectation written by hand rarely lists every
argument the model will send, and a grader that fails on an extra optional field
teaches people to delete the grader.

When a comparison fails the useful output is not "mismatch" but the **first
divergence**: the earliest call where the two part company. Everything after it
is downstream noise, and fixing the last symptom fixes nothing.

:func:`detect_signatures` names six failure shapes, each with a different root
cause and therefore a different repair — `loop`, `oscillation`, `stall`,
`unknown_tool`, `error_cascade`, and the terminal shapes `max_turns` /
`max_budget`. A run can carry several.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from . import SYNTHETIC_TOOLS
from .graders import normalize_tool_name
from .trace import TraceEvent, result_event, tool_calls

MATCH_EXACT = "EXACT"
MATCH_IN_ORDER = "IN_ORDER"
MATCH_ANY_ORDER = "ANY_ORDER"
MATCH_MODES = (MATCH_EXACT, MATCH_IN_ORDER, MATCH_ANY_ORDER)
#: What a `trajectory` grader uses when it says nothing.
DEFAULT_MATCH = MATCH_IN_ORDER

ARGS_EXACT = "exact"
ARGS_SUBSET = "subset"
ARGS_IGNORE = "ignore"
ARGS_MODES = (ARGS_EXACT, ARGS_SUBSET, ARGS_IGNORE)
DEFAULT_ARGS_MATCH = ARGS_SUBSET

#: Three identical consecutive calls is a loop; two is a retry.
LOOP_THRESHOLD = 3
#: Two consecutive error results is a cascade; one is a tool doing its job.
ERROR_CASCADE_THRESHOLD = 2


def normalize_match(value: str | None) -> str:
    if not value:
        return DEFAULT_MATCH
    return str(value).upper().replace("-", "_").replace(" ", "_")


def normalize_args_match(value: str | None) -> str:
    if not value:
        return DEFAULT_ARGS_MATCH
    return str(value).lower().strip()


@dataclass
class Call:
    """One tool call. `synthetic` marks a call the CLI fabricated.

    The tool name is normalized on the way in, so `Task` and `Agent` compare
    equal: they are the same tool reported under two names, and a grader written
    against the docs (`Agent`) must match a trace written by the CLI (`Task`).
    """

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False

    def __post_init__(self) -> None:
        self.tool = normalize_tool_name(self.tool)
        if not self.synthetic and self.tool in SYNTHETIC_TOOLS:
            self.synthetic = True

    def key(self, *, args_match: str = DEFAULT_ARGS_MATCH) -> tuple:
        if args_match == ARGS_IGNORE:
            return (self.tool,)
        return (self.tool, _freeze(self.args))

    def short(self, *, width: int = 72) -> str:
        """A one-line form that keeps whole key/value pairs rather than cutting
        mid-value, so a truncated call is still readable."""
        if not self.args:
            return f"{self.tool}()"
        parts: list[str] = []
        used = 0
        for index, (key, value) in enumerate(self.args.items()):
            piece = f"{key}={value!r}"
            if used + len(piece) > width and parts:
                parts.append(f"+{len(self.args) - index} more")
                break
            parts.append(piece)
            used += len(piece) + 2
        return f"{self.tool}({', '.join(parts)})"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"tool": self.tool, "args": self.args}
        if self.synthetic:
            out["synthetic"] = True
        return out


def _freeze(value: Any) -> Any:
    """Hashable, key-order-insensitive view of a JSON value."""
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _args_equal(expected: dict[str, Any], actual: dict[str, Any], mode: str) -> bool:
    if mode == ARGS_IGNORE:
        return True
    if mode == ARGS_SUBSET:
        return all(_freeze(actual.get(k)) == _freeze(v) for k, v in expected.items())
    return _freeze(expected) == _freeze(actual)


def to_calls(
    raw: Iterable[Any],
    *,
    include_synthetic: bool = False,
) -> list[Call]:
    """Normalize anything call-shaped into `Call`s.

    Accepts trace events, `{tool, args}` mappings, `{name, input}` mappings
    (the SDK's own spelling) and bare tool names. Synthetic calls are dropped
    unless asked for — that is the `StructuredOutput` rule, and it lives here so
    every grader and every signature detector gets it for free.
    """
    calls: list[Call] = []
    for item in raw or []:
        call: Call | None = None
        if isinstance(item, Call):
            call = item
        elif isinstance(item, TraceEvent):
            if item.type != "tool_use":
                continue
            call = Call(tool=item.tool or "?", args=item.input, synthetic=item.synthetic)
        elif isinstance(item, dict):
            tool = item.get("tool") or item.get("name") or "?"
            args = item.get("args")
            if args is None:
                args = item.get("input")
            call = Call(tool=str(tool), args=args if isinstance(args, dict) else {},
                        synthetic=bool(item.get("synthetic")))
        elif isinstance(item, str):
            call = Call(tool=item)
        if call is None:
            continue
        if call.synthetic and not include_synthetic:
            continue
        calls.append(call)
    return calls


def calls_from_events(
    events: Sequence[TraceEvent], *, include_synthetic: bool = False
) -> list[Call]:
    """The trajectory of a run, read from its trace."""
    return to_calls(tool_calls(events, include_synthetic=include_synthetic),
                    include_synthetic=include_synthetic)


def expected_from_grader(meta: dict[str, Any]) -> list[Call]:
    """The expected trajectory a `trajectory` grader declares.

    `expected: [{tool: x, args: {...}}, ...]`, with a bare string accepted as a
    tool name with no argument expectation. A synthetic tool named here is kept:
    naming it is how a case asserts that structured output was produced.
    """
    raw = meta.get("expected")
    if not isinstance(raw, list):
        return []
    return to_calls(raw, include_synthetic=True)


@dataclass
class ArgMismatch:
    index: int
    tool: str
    expected: dict[str, Any]
    actual: dict[str, Any]

    @property
    def differing_keys(self) -> list[str]:
        keys = set(self.expected) | set(self.actual)
        return sorted(k for k in keys
                      if _freeze(self.expected.get(k)) != _freeze(self.actual.get(k)))

    def to_dict(self) -> dict[str, Any]:
        keys = self.differing_keys
        return {
            "index": self.index, "tool": self.tool, "differing_keys": keys,
            "expected": {k: self.expected.get(k) for k in keys},
            "actual": {k: self.actual.get(k) for k in keys},
        }


@dataclass
class Diff:
    """The result of one comparison, including its score.

    `score` is 1.0 on a match and otherwise the fraction of expected calls that
    were found, so a `threshold` on a `trajectory` grader has something
    continuous to compare against. `forbidden` lists calls the expectation did
    not name under EXACT — that is the field an adversarial case cares about.
    """

    match: bool
    match_mode: str
    args_match: str
    expected: list[Call]
    actual: list[Call]
    score: float = 0.0
    first_divergence: int | None = None
    divergence_kind: str | None = None     # missing | extra | wrong_tool | arg_mismatch
    missing: list[Call] = field(default_factory=list)
    extra: list[Call] = field(default_factory=list)
    forbidden: list[Call] = field(default_factory=list)
    arg_mismatches: list[ArgMismatch] = field(default_factory=list)

    def explain(self) -> str:
        if self.match:
            return f"trajectory matches ({self.match_mode}, args {self.args_match})"
        if self.first_divergence is None:
            return f"trajectory differs ({self.match_mode})"
        index = self.first_divergence
        expected = self.expected[index].short() if index < len(self.expected) else "(nothing)"
        actual = self.actual[index].short() if index < len(self.actual) else "(nothing)"
        return (f"first divergence at call {index + 1}: expected {expected}, got {actual} "
                f"[{self.divergence_kind}]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "match": self.match, "match_mode": self.match_mode, "args_match": self.args_match,
            "score": round(self.score, 4),
            "expected": [c.short() for c in self.expected],
            "actual": [c.short() for c in self.actual],
            "first_divergence": self.first_divergence,
            "divergence_kind": self.divergence_kind,
            "missing": [c.short() for c in self.missing],
            "extra": [c.short() for c in self.extra],
            "forbidden": [c.short() for c in self.forbidden],
            "arg_mismatches": [m.to_dict() for m in self.arg_mismatches],
            "explanation": self.explain(),
        }


def diff(
    actual: Iterable[Any],
    expected: Iterable[Any],
    match: str = DEFAULT_MATCH,
    args_match: str = DEFAULT_ARGS_MATCH,
) -> Diff:
    """Compare an actual trajectory against an expected one.

    Argument order is `(actual, expected)` because that is the order a grader
    has them in: the run happened, then it is judged.
    """
    mode = normalize_match(match)
    arg_mode = normalize_args_match(args_match)
    exp = to_calls(expected, include_synthetic=True)
    act = to_calls(actual, include_synthetic=True)
    result = Diff(match=False, match_mode=mode, args_match=arg_mode, expected=exp, actual=act)

    if mode == MATCH_ANY_ORDER:
        _diff_any_order(result, exp, act, arg_mode)
    elif mode == MATCH_IN_ORDER:
        _diff_in_order(result, exp, act, arg_mode)
    else:
        _diff_exact(result, exp, act, arg_mode)

    found = len(exp) - len(result.missing)
    result.score = 1.0 if result.match else (found / len(exp) if exp else 0.0)
    return result


def _matches(expected: Call, actual: Call, arg_mode: str) -> bool:
    return expected.tool == actual.tool and _args_equal(expected.args, actual.args, arg_mode)


def _diff_any_order(result: Diff, exp: list[Call], act: list[Call], arg_mode: str) -> None:
    remaining = list(act)
    for call in exp:
        for index, candidate in enumerate(remaining):
            if _matches(call, candidate, arg_mode):
                remaining.pop(index)
                break
        else:
            result.missing.append(call)
    result.extra = remaining
    result.match = not result.missing
    if result.missing:
        result.divergence_kind = "missing"
        first = result.missing[0]
        for index, call in enumerate(exp):
            if call is first:
                result.first_divergence = index
                break


def _diff_in_order(result: Diff, exp: list[Call], act: list[Call], arg_mode: str) -> None:
    cursor = 0
    consumed: set[int] = set()
    for call in exp:
        found = False
        while cursor < len(act):
            if _matches(call, act[cursor], arg_mode):
                consumed.add(cursor)
                cursor += 1
                found = True
                break
            cursor += 1
        if not found:
            result.missing.append(call)
    result.extra = [call for index, call in enumerate(act) if index not in consumed]
    result.match = not result.missing
    if result.missing:
        first = result.missing[0]
        result.divergence_kind = "missing"
        for index, call in enumerate(exp):
            if call is first:
                result.first_divergence = index
                break
        # The right tool with the wrong arguments is the more precise story than
        # "missing": it says the agent tried and got the input wrong.
        if arg_mode != ARGS_IGNORE:
            for index, call in enumerate(act):
                if call.tool == first.tool and not _args_equal(first.args, call.args, arg_mode):
                    result.divergence_kind = "arg_mismatch"
                    result.arg_mismatches.append(ArgMismatch(
                        index=index, tool=call.tool, expected=first.args, actual=call.args))
                    break


def _diff_exact(result: Diff, exp: list[Call], act: list[Call], arg_mode: str) -> None:
    for index in range(max(len(exp), len(act))):
        expected_call = exp[index] if index < len(exp) else None
        actual_call = act[index] if index < len(act) else None
        if expected_call is None and actual_call is not None:
            result.extra.append(actual_call)
            result.forbidden.append(actual_call)
            if result.first_divergence is None:
                result.first_divergence, result.divergence_kind = index, "extra"
            continue
        if actual_call is None and expected_call is not None:
            result.missing.append(expected_call)
            if result.first_divergence is None:
                result.first_divergence, result.divergence_kind = index, "missing"
            continue
        assert expected_call is not None and actual_call is not None
        if expected_call.tool != actual_call.tool:
            if result.first_divergence is None:
                result.first_divergence, result.divergence_kind = index, "wrong_tool"
            result.missing.append(expected_call)
            result.extra.append(actual_call)
            result.forbidden.append(actual_call)
        elif not _args_equal(expected_call.args, actual_call.args, arg_mode):
            result.arg_mismatches.append(ArgMismatch(
                index=index, tool=expected_call.tool,
                expected=expected_call.args, actual=actual_call.args))
            if result.first_divergence is None:
                result.first_divergence, result.divergence_kind = index, "arg_mismatch"
    result.match = (
        result.first_divergence is None and not result.missing
        and not result.extra and not result.arg_mismatches
    )


# ---------------------------------------------------------------------------
# failure signatures
# ---------------------------------------------------------------------------

@dataclass
class Signature:
    """One named failure shape, with the layer it belongs to and the repair.

    `layer` says where the fix goes — `tool` (the tool's schema or its error
    text), `prompt` (the system prompt's rules), `model` (the model invented
    something), `budget` (a ceiling did its job), `eval` (the case is wrong).
    Naming the layer is what stops a prompt tweak being applied to a tool bug.
    """

    kind: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    layer: str = "prompt"
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_signatures(
    events: Sequence[TraceEvent],
    *,
    known_tools: Iterable[str] | None = None,
) -> list[Signature]:
    """Name the shapes of a misbehaving run from its trace.

    ``loop``
        the same tool with the same arguments three or more times in a row.
        Nothing changed between attempts, so no new information arrived: usually
        a tool error message the model cannot act on, or a missing stop condition.
    ``oscillation``
        two calls alternating A-B-A-B without moving on. The prompt's ordering
        rules are circular.
    ``stall``
        the run ended with no tool call and no final text. The prompt left this
        input with no safe path.
    ``unknown_tool``
        a call to something `init.tools` does not list: the model invented a
        capability.
    ``error_cascade``
        two or more consecutive error results. The agent is building on failures.
    ``max_turns`` / ``max_budget``
        a ceiling stopped the run. Not a bug — but the run proves nothing about
        the agent's answer, so it must not be read as a content failure.
    """
    calls = calls_from_events(events)
    signatures: list[Signature] = []
    signatures.extend(_loops(calls))
    signatures.extend(_oscillation(calls))
    signatures.extend(_unknown_tools(calls, events, known_tools))
    signatures.extend(_error_cascade(events))
    signatures.extend(_stall(calls, events))
    signatures.extend(_terminal(events))
    return signatures


def _loops(calls: Sequence[Call]) -> list[Signature]:
    out: list[Signature] = []
    run_length, run_start = 1, 0
    for index in range(1, len(calls) + 1):
        same = index < len(calls) and calls[index].key() == calls[index - 1].key()
        if same:
            run_length += 1
            continue
        if run_length >= LOOP_THRESHOLD:
            call = calls[run_start]
            out.append(Signature(
                kind="loop",
                detail=f"{call.tool} called {run_length} times in a row with identical arguments",
                evidence=[call.short()], layer="tool",
                fix="identical arguments mean nothing new came back. Make the tool's error "
                    "result say what to change, and give the prompt an explicit retry limit; "
                    "a `budget` grader on max_turns will catch the regression.",
            ))
        run_length, run_start = 1, index
    return out


def _oscillation(calls: Sequence[Call]) -> list[Signature]:
    names = [call.tool for call in calls]
    for index in range(len(names) - 3):
        a, b, c, d = names[index:index + 4]
        if a == c and b == d and a != b:
            return [Signature(
                kind="oscillation",
                detail=f"alternates between {a} and {b} without moving on",
                evidence=names[index:index + 4], layer="prompt",
                fix=f"the ordering rules are circular. State the progression explicitly: "
                    f"once {b} has answered, move on rather than revisiting {a}.",
            )]
    return []


def _unknown_tools(
    calls: Sequence[Call], events: Sequence[TraceEvent], known_tools: Iterable[str] | None
) -> list[Signature]:
    if known_tools is None:
        from .trace import known_tool_names
        known = known_tool_names(events)
        if not known:
            return []                     # no init.tools: cannot tell invented from real
    else:
        known = {normalize_tool_name(str(t)) for t in known_tools}
        if not known:
            return []
    known |= {normalize_tool_name(t) for t in SYNTHETIC_TOOLS}
    invented = sorted({call.tool for call in calls if call.tool not in known})
    if not invented:
        return []
    return [Signature(
        kind="unknown_tool",
        detail="called tool(s) the run did not have: " + ", ".join(invented),
        evidence=invented, layer="model",
        fix="the model invented a capability. Name the available tools in the system prompt, "
            "and check the case is not asking for something the agent cannot do — an "
            "impossible case fails forever and teaches nothing.",
    )]


def _error_cascade(events: Sequence[TraceEvent]) -> list[Signature]:
    from .trace import tool_results

    results = tool_results(events)
    streak, best, start = 0, 0, 0
    best_start = 0
    for index, event in enumerate(results):
        if event.is_error:
            if streak == 0:
                start = index
            streak += 1
            if streak > best:
                best, best_start = streak, start
        else:
            streak = 0
    if best < ERROR_CASCADE_THRESHOLD:
        return []
    evidence = [
        f"{str(e.get('content') or '')[:80]}" for e in results[best_start:best_start + best]
    ]
    return [Signature(
        kind="error_cascade",
        detail=f"{best} tool results in a row came back as errors",
        evidence=[e for e in evidence if e], layer="tool",
        fix="the agent is building on failures. Check whether the error text tells it what "
            "to do differently — `is_error` with an opaque message is the most common cause "
            "of both this and the loop signature. Note `is_error` is null on success, not "
            "false, so a check written as `is_error is False` finds nothing.",
    )]


def _stall(calls: Sequence[Call], events: Sequence[TraceEvent]) -> list[Signature]:
    from .trace import final_text

    result = result_event(events)
    if result is None:
        return []
    if calls or final_text(events).strip():
        return []
    return [Signature(
        kind="stall",
        detail="the run ended with no tool call and no final text",
        evidence=[f"subtype={result.get('subtype')}",
                  f"terminal_reason={result.get('terminal_reason')}"],
        layer="prompt",
        fix="the prompt leaves this input with no safe path: the agent had nothing it was "
            "allowed to do and nothing it was told to say. Define the default action for an "
            "unmatched or ambiguous request, and assert it with a `final_text` grader.",
    )]


def _terminal(events: Sequence[TraceEvent]) -> list[Signature]:
    result = result_event(events)
    if result is None:
        return []
    subtype = str(result.get("subtype") or "")
    reason = str(result.get("terminal_reason") or "")
    out: list[Signature] = []
    if subtype == "error_max_turns" or reason == "max_turns":
        out.append(Signature(
            kind="max_turns",
            detail=f"the turn limit stopped the run (subtype={subtype or 'n/a'}, "
                   f"terminal_reason={reason or 'n/a'}, num_turns={result.get('num_turns')})",
            evidence=[f"num_turns={result.get('num_turns')}"], layer="budget",
            fix="the run was cut off, so its answer proves nothing: read it as inconclusive, "
                "not as a content failure. Either the agent needs more turns or it is "
                "looping — check for a `loop` signature before raising the limit.",
        ))
    if subtype == "error_max_budget_usd":
        out.append(Signature(
            kind="max_budget",
            detail=f"the cost ceiling stopped the run at "
                   f"${result.get('total_cost_usd') or 0:.4f}",
            evidence=[f"total_cost_usd={result.get('total_cost_usd')}"], layer="budget",
            fix="same reading as max_turns: inconclusive, not failed. If the ceiling is "
                "right, the agent is doing too much work; if the work is right, the ceiling "
                "is too low for this case.",
        ))
    if subtype == "error_during_execution" or reason == "api_error":
        out.append(Signature(
            kind="api_error",
            detail=f"the run ended in an error (subtype={subtype or 'n/a'}, "
                   f"api_error_status={result.get('api_error_status')})",
            evidence=[str(result.get("errors") or result.get("result_text") or "")[:120]],
            layer="eval",
            fix="an error result is not a failing eval. A 429 is a rate limit (record "
                "NOT_EVALUATED and stop); anything else needs the error text before the "
                "agent is blamed.",
        ))
    return out


def cascade_suspect(result: Diff) -> Signature | None:
    """An early argument mistake that later calls build on.

    The hardest failure to read, because every call looks right: the sequence is
    right, the outcome is wrong, and the reason is that step one normalized an
    input badly and nothing revalidated it. Worth its own signature because the
    instinct is to fix the last call.
    """
    if result.match or not result.arg_mismatches:
        return None
    first = min(result.arg_mismatches, key=lambda m: m.index)
    later = len(result.actual) - first.index - 1
    if later < 2:
        return None
    return Signature(
        kind="cascade_suspect",
        detail=(f"arguments first diverge at call {first.index + 1} ({first.tool}, keys: "
                f"{', '.join(first.differing_keys)}), and {later} later call(s) build on it"),
        evidence=[f"{first.tool}: expected {first.expected}, got {first.actual}"],
        layer="tool",
        fix="fix the first divergence, not the last symptom. Tighten that argument's schema "
            "or its description, and add a `trajectory` grader with `args_match: exact` on "
            "the first call so the regression is caught where it starts.",
    )


# ---------------------------------------------------------------------------
# the trajectory x answer quadrant
# ---------------------------------------------------------------------------

QUADRANTS = {
    "Q1": {
        "label": "trajectory and answer both good",
        "reading": "the agent did the right things and said them well",
        "action": "nothing to fix; keep the case as a regression guard",
    },
    "Q2": {
        "label": "good trajectory, weak answer",
        "reading": "the work was right, the wording was not — a presentation problem, "
                   "not a logic one",
        "action": "fix the prompt's output format, or relax a brittle text check: "
                  "`final_text` with `mode: rouge1` compares word overlap, not meaning",
    },
    "Q3": {
        "label": "weak trajectory, good answer",
        "reading": "the answer reads well but the agent skipped or reordered the work to get "
                   "there. Every text-only grader passes this, which is what makes it the "
                   "dangerous quadrant",
        "action": "treat it as a real failure: was the answer grounded in tool output at all? "
                  "Strengthen the prompt's ordering and refusal rules, and keep the "
                  "trajectory grader that caught it",
    },
    "Q4": {
        "label": "both weak",
        "reading": "a plain logic failure, and the easiest to act on",
        "action": "start at the first divergence in the trajectory and stop reading there",
    },
}


def quadrant(trajectory_ok: bool | None, answer_ok: bool | None) -> dict[str, Any]:
    """Place a case in the trajectory x answer quadrant.

    Either input may be None — which is itself the finding: a suite with no
    trajectory grader cannot tell Q1 from Q3, and Q3 is the failure that passes
    every text check.
    """
    if trajectory_ok is None or answer_ok is None:
        missing = "a trajectory check" if trajectory_ok is None else "an answer check"
        return {
            "quadrant": None,
            "label": "not enough signal",
            "reading": f"this case has no {missing}, so a right-looking answer reached by the "
                       "wrong route is indistinguishable from a correct run",
            "action": f"add {missing} — a `trajectory`/`tool_order` grader, or an `llm`/"
                      "`final_text` grader — if you want this diagnosis",
        }
    key = "Q1" if trajectory_ok and answer_ok else "Q2" if trajectory_ok \
        else "Q3" if answer_ok else "Q4"
    return {"quadrant": key, **QUADRANTS[key]}
