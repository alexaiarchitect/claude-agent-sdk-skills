"""Ceilings, efficiency, and what a rate limit actually means.

Cost in this plugin is never one number, because on a subscription it is not one
thing. `ResultMessage.total_cost_usd` is a **client-side estimate** from a price
table the CLI bundles: with an API key it is roughly the bill, and on a Max
subscription nothing is billed at all — the real ceiling is the plan's five-hour
and seven-day usage windows. So every figure this module produces carries a
`cost_basis` (`subscription` | `api_key` | `provider`), and a report that says
"$0.63" without it is saying something it does not know.

Four measured facts shape :func:`check_budget`, and each one is a bug if ignored:

* **`total_cost_usd` is a session running total, not a per-turn cost.** Measured
  0.004991 then 0.0061734 across two turns of one session. So the case total is
  the *last* value, never the sum, and `cost_delta_usd` is what attributes spend
  to a turn.
* **`max_turns` does not bound `num_turns`.** `max_turns=1` produced
  `num_turns=2`, `subtype="success"`. A `budget` grader's `max_turns` is its own
  ceiling; asserting the option *tripped* is a `terminal` grader's job. To size
  the option itself, count each turn with tool calls plus one for the final
  text-only response (docs agent-loop, read 2026-10-29): one tool call under
  `max_turns=1` ends `error_max_turns` with `num_turns=2` and no final response.
* **The token keys are `*_input_tokens`.** `usage.cache_creation` is a nested
  dict of ephemeral TTL buckets, never a number — comparing it to an integer
  silently never fires.
* **A `RateLimitEvent` fired on all three measured runs**, at
  `status: "allowed_warning"`, with the 7-day window 83 % consumed. Treating any
  rate-limit event as a limit hit would have marked every healthy run
  inconclusive. Only `rejected` stops anything: see :func:`rate_limit_verdict`.

Two more, measured on 0.2.165 / CLI 2.1.294 (2026-10-11) and still so on
0.2.168 / CLI 2.1.301 (2026-10-17) and 0.2.174 / CLI 2.1.310 (2026-10-24):

* **`max_budget_usd` is a soft cap.** It refuses the *next* request once the
  estimate has passed the ceiling, so a session can and does finish over it.
  Every figure here is read as "what it cost", never "what it was allowed".
* **`model_usage` holds more than one model.** The CLI bills its own background
  work to `claude-haiku-5-5` without being asked, and the entries carry
  `costBasis` and `thinkingTokens`, neither of which the pinned `ModelUsage`
  TypedDict declares. So the readers below loop over every entry and use
  `.get()`: see :func:`models_billed` and :func:`cost_basis_is_list`.

The efficiency table is deliberately lower-is-better and deliberately separate
from pass/fail. A cheaper agent that fails is not better; but between two agents
that both pass, the one using half the turns is the one to keep, and nothing in a
pass rate shows that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .graders import BUDGET_CEILINGS, BUDGET_USAGE_KEYS
from .report import Finding
from .trace import TraceEvent, result_outcome

_SRC_RESULT = "claude_agent_sdk types.py:1695 ResultMessage (0.2.174) + measured VERIFIED-FACTS §2.2"
_SRC_TURNS = ("measured: VERIFIED-FACTS §8.1 — max_turns=1 produced num_turns=2; "
              "code.claude.com/docs/en/agent-sdk/agent-loop (read 2026-10-29, Claude Code 2.1.312)")
#: The documented "+1" rule for sizing `max_turns` (agent-loop page, read
#: 2026-10-29; measured the same day on CLI 2.1.310: one tool call under
#: `max_turns=1` ended `error_max_turns`, `stop_reason "tool_use"`, `num_turns 2`,
#: `result None`; under `max_turns=2` it succeeded with the answer).
MAX_TURNS_PLUS_ONE = ("count each turn with tool calls plus one for the final text-only "
                      "response; without that extra turn the run ends `error_max_turns` with "
                      "no final response (docs agent-loop, read 2026-10-29)")
_SRC_COST = "measured: VERIFIED-FACTS §8.2 — total_cost_usd is a session running total"
_SRC_RATE = "measured: VERIFIED-FACTS §9 — RateLimitEvent on every run at allowed_warning"
_SRC_STOP = ("code.claude.com/docs/en/agent-sdk/python (ResultMessage.is_error, read at Claude "
             "Code 2.1.310): on subtype=\"success\" check stop_reason first")

#: Statuses a rate-limit event may carry, and what each one means for a run.
RATE_LIMIT_VERDICTS = {
    "allowed": "keep",
    "allowed_warning": "warn",
    "rejected": "stop",
}

#: Ceilings compared against `result` fields rather than `usage` keys.
_DIRECT_CEILINGS = {
    "max_cost_usd": "total_cost_usd",
    "max_turns": "num_turns",
    "max_duration_ms": "duration_ms",
}

STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_NOT_EVALUATED = "NOT_EVALUATED"
STATUS_INFORMATIONAL = "INFORMATIONAL"

#: Text in an error result that names a usage limit rather than a rate limit.
_USAGE_LIMIT_MARKERS = (
    "usage limit", "usage_limit", "weekly limit", "5-hour limit", "five-hour limit",
    "session limit", "quota", "plan limit", "rate limit", "rate_limit",
    "resets at", "upgrade to", "too many requests",
)


@dataclass
class CeilingCheck:
    """One ceiling and what the run actually did."""

    name: str
    limit: float
    observed: float | None
    field: str
    ok: bool

    @property
    def status(self) -> str:
        if self.observed is None:
            return STATUS_NOT_EVALUATED
        return STATUS_PASSED if self.ok else STATUS_FAILED

    @property
    def headroom(self) -> float | None:
        if self.observed is None:
            return None
        return self.limit - self.observed

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "limit": self.limit, "observed": self.observed,
            "field": self.field, "ok": self.ok, "status": self.status,
            "headroom": self.headroom,
        }


@dataclass
class BudgetResult:
    """The verdict of one `budget` grader.

    `status` is `INFORMATIONAL` when the grader set `informational: true` — the
    numbers are recorded and reported but never fail the case. That is the right
    default for a new ceiling: watch it for a week, then decide where it belongs.
    """

    status: str
    score: float
    checks: list[CeilingCheck] = field(default_factory=list)
    reason: str = ""
    cost_basis: str | None = None
    informational: bool = False

    @property
    def failures(self) -> list[CeilingCheck]:
        return [c for c in self.checks if c.status == STATUS_FAILED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "score": round(self.score, 4), "reason": self.reason,
            "cost_basis": self.cost_basis, "informational": self.informational,
            "checks": [c.to_dict() for c in self.checks],
        }


def check_budget(
    result_event: TraceEvent | dict[str, Any] | None,
    ceilings: dict[str, Any],
    *,
    informational: bool = False,
) -> BudgetResult:
    """Compare one run's `result` event against a `budget` grader's ceilings.

    `result_event` is None for imported session evidence, and that is the
    important branch: a session file carries no cost, no `num_turns` and no
    duration, so the honest verdict is `NOT_EVALUATED`. Reporting `PASSED`
    because nothing exceeded a ceiling nobody measured would be a lie that reads
    as a green tick.

    Cost is read as the **case total** (`total_cost_usd`, a session running
    total), not as a sum of per-turn deltas. `cost_delta_usd` is available on the
    event for attribution but is never the thing a ceiling compares against.
    """
    data = _as_dict(result_event)
    declared = {k: v for k, v in (ceilings or {}).items() if k in BUDGET_CEILINGS}
    informational = bool(informational or (ceilings or {}).get("informational"))

    if not declared:
        return BudgetResult(
            status=STATUS_NOT_EVALUATED, score=0.0, informational=informational,
            reason="the grader declares no ceiling, so there is nothing to compare",
        )
    if data is None:
        return BudgetResult(
            status=STATUS_NOT_EVALUATED, score=0.0, informational=informational,
            reason="no result event: imported session evidence carries no cost, num_turns "
                   "or duration, so a budget ceiling cannot be evaluated",
        )

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    checks: list[CeilingCheck] = []
    for name, limit in declared.items():
        if isinstance(limit, bool) or not isinstance(limit, (int, float)):
            continue
        if name in _DIRECT_CEILINGS:
            field_name = _DIRECT_CEILINGS[name]
            observed = _number(data.get(field_name))
        else:
            field_name = f"usage.{BUDGET_USAGE_KEYS[name]}"
            observed = _number(usage.get(BUDGET_USAGE_KEYS[name]))
        checks.append(CeilingCheck(
            name=name, limit=float(limit), observed=observed, field=field_name,
            ok=observed is not None and observed <= float(limit),
        ))

    evaluated = [c for c in checks if c.observed is not None]
    unmeasured = [c for c in checks if c.observed is None]
    failures = [c for c in checks if c.status == STATUS_FAILED]

    if not evaluated:
        return BudgetResult(
            status=STATUS_NOT_EVALUATED, score=0.0, checks=checks, informational=informational,
            cost_basis=data.get("cost_basis"),
            reason="none of the declared ceilings has a value in this result: "
                   + ", ".join(c.field for c in unmeasured),
        )

    score = (len(evaluated) - len(failures)) / len(evaluated)
    if informational:
        status = STATUS_INFORMATIONAL
        reason = "informational: " + _describe(checks)
    elif failures:
        status = STATUS_FAILED
        reason = "over budget: " + ", ".join(
            f"{c.name} {_fmt(c.observed)} > {_fmt(c.limit)}" for c in failures)
    else:
        status = STATUS_PASSED
        reason = "within budget: " + _describe(checks)
    if unmeasured and status != STATUS_NOT_EVALUATED:
        reason += " (not measured: " + ", ".join(c.field for c in unmeasured) + ")"
    return BudgetResult(status=status, score=score, checks=checks, reason=reason,
                        cost_basis=data.get("cost_basis"), informational=informational)


def _as_dict(event: TraceEvent | dict[str, Any] | None) -> dict[str, Any] | None:
    if event is None:
        return None
    if isinstance(event, TraceEvent):
        return dict(event.data)
    if isinstance(event, dict):
        return event
    return None


def _number(value: Any) -> float | None:
    """A numeric reading, or None when the field is absent or not a number.

    `usage.cache_creation` is a nested dict of TTL buckets, so anything that is
    not a plain number returns None rather than comparing a dict to an int.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(value: float | None) -> str:
    """A number a human reads: cents keep their digits, token counts get commas."""
    if value is None:
        return "?"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if value != int(value) and abs(value) < 10:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:g}"


def _describe(checks: Sequence[CeilingCheck]) -> str:
    return ", ".join(
        f"{c.name} {_fmt(c.observed)}/{_fmt(c.limit)}" for c in checks if c.observed is not None
    )


def usage_of(result_event: TraceEvent | dict[str, Any] | None) -> dict[str, Any]:
    """The flat `usage` projection, defaulting missing keys to zero.

    Only the keys a grader or a table reads; `usage_raw` on the event keeps
    everything else, including `iterations` and `cache_creation`'s TTL buckets.
    """
    data = _as_dict(result_event) or {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return {
        "input_tokens": _number(usage.get("input_tokens")) or 0,
        "output_tokens": _number(usage.get("output_tokens")) or 0,
        "cache_read_input_tokens": _number(usage.get("cache_read_input_tokens")) or 0,
        "cache_creation_input_tokens": _number(usage.get("cache_creation_input_tokens")) or 0,
        "thinking_tokens": _number(usage.get("thinking_tokens")) or 0,
    }


def total_tokens(result_event: TraceEvent | dict[str, Any] | None) -> float:
    """Every token the run consumed, cache included.

    Cache reads are counted because on a subscription they still draw on the
    usage window, even though they cost a fraction of a fresh input token. A
    table that hides them makes an agent loading 20 000 tokens of ambient config
    look identical to one loading none — which is precisely the 17x difference
    the isolation defaults exist to prevent.
    """
    usage = usage_of(result_event)
    return sum(usage[k] for k in (
        "input_tokens", "output_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens"))


def model_usage_of(result_event: TraceEvent | dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """`model_usage` as a dict of dicts, defensively.

    The wire carries two keys the `ModelUsage` TypedDict (0.2.165, still on
    0.2.174) does not declare — `costBasis` and `thinkingTokens`, both measured 2026-10-11 — so
    every read of this mapping goes through `.get()` and never indexes a key.
    """
    data = _as_dict(result_event) or {}
    usage = data.get("model_usage")
    if not isinstance(usage, dict):
        return {}
    return {
        str(name): dict(entry) for name, entry in usage.items() if isinstance(entry, dict)
    }


def models_billed(result_event: TraceEvent | dict[str, Any] | None) -> list[str]:
    """Every model the session was billed for, sorted.

    Not "the model that ran": measured 2026-10-11 (CLI 2.1.294) and 2026-10-17
    (CLI 2.1.301) and again 2026-10-24 (CLI 2.1.310), the CLI bills its own
    background work to `claude-haiku-5-5` without being asked, so a cost note
    about "the agent's model" is wrong about the total. The runner records the
    same list on the `result` event as `models_billed`; this reads it back, and
    falls back to the keys of `model_usage` for an older trace.
    """
    data = _as_dict(result_event) or {}
    recorded = data.get("models_billed")
    if isinstance(recorded, (list, tuple)):
        return [str(name) for name in recorded]
    return sorted(model_usage_of(result_event))


def cost_basis_is_list(result_event: TraceEvent | dict[str, Any] | None) -> bool | None:
    """True when every billed model priced at list, None when nothing is known.

    `ModelUsage.costBasis` is `list | managed | unknown` and is absent from the
    pinned TypedDict, so an absent key counts as list pricing; a `managed` entry
    means a negotiated rate and the estimate is not the bill. The runner records
    the same answer as `cost_basis_list` on the `result` event.
    """
    data = _as_dict(result_event) or {}
    recorded = data.get("cost_basis_list")
    if isinstance(recorded, bool):
        return recorded
    usage = model_usage_of(result_event)
    if not usage:
        return None
    return all(entry.get("costBasis", "list") == "list" for entry in usage.values())


def model_thinking_tokens(result_event: TraceEvent | dict[str, Any] | None) -> float:
    """Thinking tokens summed over every billed model, zero when unreported.

    `thinkingTokens` is undeclared on `ModelUsage` as well, so it is read with
    `.get()`; `usage.thinking_tokens` is the per-session figure beside it.
    """
    return sum(
        _number(entry.get("thinkingTokens")) or 0
        for entry in model_usage_of(result_event).values()
    )


# ---------------------------------------------------------------------------
# the efficiency table
# ---------------------------------------------------------------------------

#: Columns of the efficiency table, all lower-is-better.
EFFICIENCY_COLUMNS = (
    "case", "runs", "turns", "tool_calls", "tokens", "cache_read", "duration_ms", "cost_usd",
)

#: Row keys the table does not print but a reader of the rows needs: which
#: models the cost is spread over, and whether the estimate used list prices.
EFFICIENCY_EXTRA_KEYS = ("models_billed", "cost_basis_list")


def efficiency_rows(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per case: how much it took to get the answer. Lower is better.

    `results` is a sequence of `<case>.result.json` documents. The numbers are
    averaged over the case's runs, because a single run's duration is mostly
    noise, and the point of the table is comparison between cases and between
    revisions — not a verdict. Pass/fail is deliberately a separate column so
    nobody reads "cheap" as "good": a failing run that ended early is the
    cheapest run there is.
    """
    rows: list[dict[str, Any]] = []
    for document in results or []:
        if not isinstance(document, dict):
            continue
        runs = [r for r in (document.get("runs") or []) if isinstance(r, dict)]
        measured = [r for r in runs if isinstance(r.get("result"), dict)]
        row: dict[str, Any] = {
            "case": document.get("case"),
            "category": document.get("category"),
            "runs": len(runs),
            "measured_runs": len(measured),
            "pass_rate": (document.get("summary") or {}).get("pass_rate"),
            "cost_basis": (document.get("config") or {}).get("cost_basis"),
        }
        if not measured:
            row.update({c: None for c in EFFICIENCY_COLUMNS if c not in ("case", "runs")})
            row.update({c: None for c in EFFICIENCY_EXTRA_KEYS})
            row["note"] = "no measured runs (imported evidence, or every run NOT_EVALUATED)"
            rows.append(row)
            continue

        row["turns"] = _mean(_number(r["result"].get("num_turns")) for r in measured)
        row["duration_ms"] = _mean(_number(r["result"].get("duration_ms")) for r in measured)
        row["tokens"] = _mean(total_tokens(r["result"]) for r in measured)
        row["cache_read"] = _mean(
            usage_of(r["result"])["cache_read_input_tokens"] for r in measured)
        row["output_tokens"] = _mean(usage_of(r["result"])["output_tokens"] for r in measured)
        # Cost is a session running total, so the case total is the last value of
        # each run, and the row averages those — never a sum across turns.
        row["cost_usd"] = _mean(_number(r["result"].get("total_cost_usd")) for r in measured)
        row["tool_calls"] = _mean(_number(r.get("tool_calls")) for r in measured)
        # Which models were billed, not which model ran: the CLI bills its own
        # background work to a model nobody asked for (measured: Haiku 5.5).
        billed: list[str] = []
        for run in measured:
            for name in models_billed(run["result"]):
                if name not in billed:
                    billed.append(name)
        row["models_billed"] = sorted(billed)
        bases = [cost_basis_is_list(r["result"]) for r in measured]
        row["cost_basis_list"] = all(b for b in bases) if any(b is not None for b in bases) else None
        rows.append(row)
    return rows


def _mean(values: Iterable[float | None]) -> float | None:
    numbers = [v for v in values if v is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 4)


def efficiency_table(rows: Sequence[dict[str, Any]]) -> str:
    """The efficiency rows as markdown, with the lower-is-better note."""
    header = "| case | runs | turns | tool calls | tokens | cache read | ms | est. USD |"
    lines = [header, "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            row.get("case") or "?", row.get("runs") or 0,
            _cell(row.get("turns")), _cell(row.get("tool_calls")),
            _cell(row.get("tokens")), _cell(row.get("cache_read")),
            _cell(row.get("duration_ms")), _cell(row.get("cost_usd"), places=4),
        ))
    bases = {row.get("cost_basis") for row in rows if row.get("cost_basis")}
    note = "_Lower is better. Averages over each case's measured runs._"
    if bases == {"subscription"}:
        note += (" _USD is a client-side estimate; on a subscription nothing is billed and "
                 "the real ceiling is the plan's usage windows._")
    lines.append("")
    lines.append(note)
    return "\n".join(lines)


def _cell(value: Any, *, places: int = 0) -> str:
    if value is None:
        return "—"
    if places:
        return f"{value:.{places}f}"
    return f"{value:,.0f}" if value >= 1000 else f"{value:g}"


# ---------------------------------------------------------------------------
# rate limits and usage limits
# ---------------------------------------------------------------------------

def rate_limit_verdict(status: str | None) -> str:
    """`keep` | `warn` | `stop` for one rate-limit status.

    The distinction is the whole rule, and getting it wrong is expensive in both
    directions. A `RateLimitEvent` fired on **every** measured run at
    `allowed_warning` with the 7-day window 83 % consumed: treating any event as
    a limit hit marks every healthy run inconclusive. Only `rejected` means the
    request was refused — then the run is `NOT_EVALUATED`, no further runs start,
    and the exit code is 3 with the reset time surfaced.

    An unknown status returns `warn`: something changed upstream, and neither
    ignoring it nor stopping the suite is right.
    """
    return RATE_LIMIT_VERDICTS.get(str(status or "").strip(), "warn")


def rate_limit_summary(events: Iterable[TraceEvent]) -> dict[str, Any] | None:
    """The last rate-limit state seen in a run, in the shape a result file keeps.

    `windows` (from `raw["unifiedWindows"]`) is the useful "how close am I"
    reading — better than the single top-level `utilization`, which reports only
    the window that tripped the threshold.
    """
    found = [e for e in events if e.type == "rate_limit"]
    if not found:
        return None
    last = found[-1]
    status = last.get("status")
    return {
        "status": status,
        "kind": last.get("kind") or "rate_limit",
        "verdict": rate_limit_verdict(status),
        "rate_limit_type": last.get("rate_limit_type"),
        "utilization": last.get("utilization"),
        "resets_at": last.get("resets_at"),
        "surpassed_threshold": last.get("surpassed_threshold"),
        "windows": last.get("windows") or {},
        "events": len(found),
    }


def usage_limit_from_result(result_event: TraceEvent | dict[str, Any] | None) -> dict[str, Any] | None:
    """Recognize a usage-limit hit in an error result.

    There is **no SDK message type for this** (CONTRACTS §11, gap 2): the plan
    assumed a distinct shape and none exists. It has to be inferred from an
    error result, and the three signals in order of reliability are:

    1. `api_error_status == 429` — unambiguous;
    2. `subtype`/`terminal_reason` naming an API error, plus limit wording in the
       result text or `errors`;
    3. limit wording alone in an error result.

    Returns None when the result is not a usage-limit hit, so a caller can treat
    "not recognized" as "this is an ordinary failure" without a second check.

    `stop_reason` is read before any of that: a refusal or a deferred tool missing
    on resume sets `is_error` on a `success` subtype without an API error (Python
    SDK docs, Claude Code 2.1.310), and a refusal's own text may well name a
    limit, so neither is ever read as a usage-limit hit.
    """
    data = _as_dict(result_event)
    if data is None:
        return None
    if result_outcome(data) in ("refusal", "tool_deferred"):
        return None
    is_error = bool(data.get("is_error")) or str(data.get("subtype") or "").startswith("error")
    status_code = data.get("api_error_status")
    text_parts = [str(data.get("result_text") or ""), str(data.get("result") or "")]
    errors = data.get("errors")
    if isinstance(errors, list):
        text_parts.extend(str(e) for e in errors)
    elif errors:
        text_parts.append(str(errors))
    haystack = " ".join(text_parts).lower()
    markers = [m for m in _USAGE_LIMIT_MARKERS if m in haystack]

    if status_code == 429:
        return {
            "kind": "usage_limit", "confidence": "certain",
            "api_error_status": 429, "matched": markers or ["api_error_status=429"],
            "status": "rejected", "verdict": "stop",
            "reason": "the API refused the request with 429; the run proves nothing about "
                      "the agent, so it is NOT_EVALUATED and the suite stops (exit 3)",
            "resets_at": data.get("resets_at"),
            "source": _SRC_RATE,
        }
    if is_error and markers:
        return {
            "kind": "usage_limit", "confidence": "likely",
            "api_error_status": status_code, "matched": markers,
            "status": "rejected", "verdict": "stop",
            "reason": "an error result whose text names a limit (" + ", ".join(markers[:3])
                      + "). There is no SDK message type for a usage-limit hit, so this is "
                        "inferred: record NOT_EVALUATED rather than FAILED, and say it was "
                        "inferred",
            "resets_at": data.get("resets_at"),
            "source": _SRC_RATE,
        }
    return None


# ---------------------------------------------------------------------------
# findings
# ---------------------------------------------------------------------------

def budget_findings(
    result_event: TraceEvent | dict[str, Any] | None,
    *,
    path: str | None = None,
) -> list[Finding]:
    """`RES` findings a single run's result event justifies on its own."""
    data = _as_dict(result_event)
    out: list[Finding] = []
    if data is None:
        return out
    limit = usage_limit_from_result(data)
    if limit is not None:
        out.append(Finding(
            id="RES011", severity="warn", area="results",
            message=f"a usage or rate limit stopped this run ({limit['confidence']}: "
                    + ", ".join(limit["matched"][:2]) + ")",
            path=path, fix=limit["reason"], source=limit["source"],
        ))
    outcome = result_outcome(data)
    if outcome == "refusal":
        out.append(Finding(
            id="RES012", severity="warn", area="results",
            message="the model refused this run (stop_reason=refusal; is_error is set on "
                    f"subtype={data.get('subtype')!r}, but it is not an API error)",
            path=path,
            fix="read the refusal text before blaming the agent or the API: either the case "
                "asks for something the model declines, or the prompt makes an ordinary "
                "request read that way. Not a usage limit and not a retryable error.",
            source=_SRC_STOP,
        ))
    elif outcome == "tool_deferred":
        out.append(Finding(
            id="RES013", severity="warn", area="results",
            message="a deferred tool was unavailable when the session resumed "
                    "(stop_reason=tool_deferred_unavailable; is_error on a success subtype)",
            path=path,
            fix="resume with the same tools the deferring session had (the deferred call is "
                "in `deferred_tool_use`); this is a harness problem, not an agent failure.",
            source=_SRC_STOP,
        ))
    subtype = str(data.get("subtype") or "")
    if subtype == "error_max_budget_usd":
        out.append(Finding(
            id="RES020", severity="warn", area="results",
            message=f"the cost ceiling stopped this run at "
                    f"${_number(data.get('total_cost_usd')) or 0:.4f}",
            path=path,
            fix="partial results are inconclusive, not failing (exit 3). Either the agent is "
                "doing too much work or the ceiling is too low for this case — check for a "
                "loop signature before raising it.",
            source=_SRC_RESULT,
        ))
    if subtype == "error_max_turns" or str(data.get("terminal_reason") or "") == "max_turns":
        out.append(Finding(
            id="RES010", severity="warn", area="results",
            message=f"the turn limit stopped this run at num_turns="
                    f"{data.get('num_turns')}",
            path=path,
            fix="read it as inconclusive: a cut-off run's answer proves nothing. When sizing "
                "the option, " + MAX_TURNS_PLUS_ONE + ". Note that "
                "num_turns can exceed the option's value without the limit tripping, so "
                "assert the limit with a `terminal` grader, not a `budget` one.",
            source=_SRC_TURNS,
        ))
    return out


def cost_label(cost: float | None, cost_basis: str | None) -> str:
    """A cost figure with the honesty its basis requires."""
    if cost is None:
        return "cost unknown"
    if cost_basis == "subscription":
        return (f"est. ${cost:.4f} API-equivalent (subscription: not billed; the real "
                "ceiling is your plan's usage windows)")
    if cost_basis == "api_key":
        return f"est. ${cost:.4f} (API key: billed)"
    if cost_basis == "provider":
        return f"est. ${cost:.4f} (cloud provider: billed by the provider, not this table)"
    return f"est. ${cost:.4f} (basis unknown)"


def total_cost(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Cost across a whole run series, with its basis and what is missing."""
    total = 0.0
    counted = 0
    missing = 0
    bases: set[str] = set()
    for document in results or []:
        if not isinstance(document, dict):
            continue
        basis = (document.get("config") or {}).get("cost_basis")
        if basis:
            bases.add(str(basis))
        for run in document.get("runs") or []:
            if not isinstance(run, dict):
                continue
            result = run.get("result")
            value = _number((result or {}).get("total_cost_usd")) if isinstance(result, dict) else None
            if value is None:
                missing += 1
            else:
                total += value
                counted += 1
    return {
        "cost_usd": round(total, 6),
        "runs_counted": counted,
        "runs_without_cost": missing,
        "cost_basis": sorted(bases)[0] if len(bases) == 1 else ("mixed" if bases else None),
        "label": cost_label(round(total, 6) if counted else None,
                            sorted(bases)[0] if len(bases) == 1 else None),
    }
