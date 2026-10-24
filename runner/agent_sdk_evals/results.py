"""Write the trace, the per-case result and the aggregate (CONTRACTS 5-7).

The four statuses are counted separately and never merged, because merging them
is how an eval suite starts lying: a NOT_EVALUATED run that is counted as a
failure invents a regression, and one counted as a pass hides an outage. The
`pass_rate` denominator is therefore the gating runs only (PASSED + FAILED), and
`not_evaluated` is reported beside it.

`pass_at_k` is the fraction of k-run samples in which at least one run passed;
with `k == runs` it is simply "did any run pass".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import (
    FAILED,
    INFORMATIONAL,
    NOT_EVALUATED,
    PASSED,
    RUNNER_VERSION,
    SCHEMA_AGGREGATE,
    SCHEMA_RESULT,
)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def result_projection(result: dict[str, Any] | None) -> dict[str, Any]:
    """The compact result block a `<case>.result.json` run carries."""
    result = result or {}
    usage = result.get("usage") or {}
    return {
        "subtype": result.get("subtype"),
        "terminal_reason": result.get("terminal_reason"),
        # Read before `is_error`: `refusal` / `tool_deferred_unavailable` set
        # `is_error` on a `success` subtype without any API error (0.1.4).
        "stop_reason": result.get("stop_reason"),
        "is_error": bool(result.get("is_error")),
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "total_cost_usd": result.get("total_cost_usd"),
        "cost_delta_usd": result.get("cost_delta_usd"),
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        },
    }


def rate_limit_projection(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        "status": payload.get("status"),
        "utilization": payload.get("utilization"),
        "resets_at": payload.get("resets_at"),
    }


@dataclass
class RunRecord:
    run: int
    trace: str
    status: str
    graders: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    rate_limit: dict[str, Any] | None = None
    error: str | None = None
    mock_calls: int = 0
    cwd: str | None = None
    simulated_user_turns: list[str] = field(default_factory=list)
    rubric_checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run": self.run, "trace": self.trace, "status": self.status,
            "graders": self.graders, "result": self.result,
        }
        if self.rate_limit:
            payload["rate_limit"] = self.rate_limit
        if self.error:
            payload["error"] = self.error
        if self.mock_calls:
            payload["mock_calls"] = self.mock_calls
        if self.cwd:
            payload["cwd"] = self.cwd
        if self.simulated_user_turns:
            payload["simulated_user_turns"] = self.simulated_user_turns
        if self.rubric_checks:
            payload["rubric_checks"] = self.rubric_checks
        return payload


@dataclass
class CaseResult:
    case: str
    category: str | None
    config: dict[str, Any]
    runs: list[RunRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def grader_counts(self) -> dict[str, int]:
        counts = {PASSED: 0, FAILED: 0, NOT_EVALUATED: 0, INFORMATIONAL: 0}
        for run in self.runs:
            for grader in run.graders:
                status = grader.get("status")
                if status in counts:
                    counts[status] += 1
        return counts

    @property
    def cost_usd(self) -> float:
        total = 0.0
        for run in self.runs:
            total += float(run.result.get("total_cost_usd") or 0.0)
            total += sum(float(g.get("cost_usd") or 0.0) for g in run.graders)
        return round(total, 6)

    @property
    def gating_runs(self) -> list[RunRecord]:
        return [r for r in self.runs if r.status in (PASSED, FAILED)]

    @property
    def pass_rate(self) -> float:
        gating = self.gating_runs
        if not gating:
            return 0.0
        return round(sum(1 for r in gating if r.status == PASSED) / len(gating), 4)

    def pass_at_k(self, k: int | None = None) -> float:
        gating = self.gating_runs
        if not gating:
            return 0.0
        if not k or k >= len(gating):
            return 1.0 if any(r.status == PASSED for r in gating) else 0.0
        windows = [gating[i:i + k] for i in range(0, len(gating) - k + 1)]
        hits = sum(1 for window in windows if any(r.status == PASSED for r in window))
        return round(hits / len(windows), 4)

    def summary(self) -> dict[str, Any]:
        counts = self.grader_counts()
        return {
            "passed": sum(1 for r in self.runs if r.status == PASSED),
            "failed": sum(1 for r in self.runs if r.status == FAILED),
            "not_evaluated": sum(1 for r in self.runs if r.status == NOT_EVALUATED),
            "informational": counts[INFORMATIONAL],
            "pass_rate": self.pass_rate,
            "cost_usd": self.cost_usd,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": SCHEMA_RESULT,
            "case": self.case,
            "category": self.category,
            "config": self.config,
            "runs": [r.to_dict() for r in self.runs],
            "summary": self.summary(),
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass
class Aggregate:
    tier: str
    started: str = field(default_factory=now_iso)
    finished: str = ""
    cases: list[CaseResult] = field(default_factory=list)
    credential: dict[str, Any] = field(default_factory=dict)
    sdk_version: str = ""
    cli_version: str = ""
    rate_limit: dict[str, Any] | None = None
    stopped: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0
    exit_code: int = 0

    def totals(self) -> dict[str, Any]:
        runs = [r for case in self.cases for r in case.runs]
        return {
            "cases": len(self.cases),
            "runs": len(runs),
            "passed": sum(1 for r in runs if r.status == PASSED),
            "failed": sum(1 for r in runs if r.status == FAILED),
            "not_evaluated": sum(1 for r in runs if r.status == NOT_EVALUATED),
            "cost_usd": round(sum(case.cost_usd for case in self.cases), 6),
            "cost_basis": self.credential.get("cost_basis", "unknown"),
            "duration_ms": self.duration_ms,
        }

    def to_dict(self, *, pass_k: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA_AGGREGATE,
            "started": self.started,
            "finished": self.finished or now_iso(),
            "tier": self.tier,
            "cases": [
                {
                    "case": case.case,
                    "pass_rate": case.pass_rate,
                    "pass_at_k": case.pass_at_k(pass_k),
                    "cost": case.cost_usd,
                    "not_evaluated": case.summary()["not_evaluated"],
                }
                for case in self.cases
            ],
            "totals": self.totals(),
            "exit_code": self.exit_code,
            "runner_version": RUNNER_VERSION,
            "sdk_version": self.sdk_version,
            "cli_version": self.cli_version,
            "credential": self.credential,
        }
        if self.rate_limit:
            payload["rate_limit"] = {
                "status": self.rate_limit.get("status"),
                "windows": self.rate_limit.get("windows") or {},
                "resets_at": self.rate_limit.get("resets_at"),
                "utilization": self.rate_limit.get("utilization"),
            }
        if self.stopped:
            payload["stopped"] = self.stopped
        if self.warnings:
            payload["warnings"] = self.warnings
        return payload


class Writer:
    """Puts the files where `eval-analyze` expects them."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)

    def ensure(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self.out_dir

    def trace_name(self, case: str, run: int) -> str:
        return f"{case}.{run}.trace.jsonl"

    def write_trace(self, case: str, run: int, jsonl: str) -> str:
        self.ensure()
        name = self.trace_name(case, run)
        (self.out_dir / name).write_text(jsonl, encoding="utf-8")
        return name

    def write_case(self, result: CaseResult) -> Path:
        self.ensure()
        path = self.out_dir / f"{result.case}.result.json"
        path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def write_aggregate(self, aggregate: Aggregate, *, pass_k: int | None = None) -> Path:
        self.ensure()
        path = self.out_dir / "aggregate.json"
        path.write_text(json.dumps(aggregate.to_dict(pass_k=pass_k), indent=2) + "\n", encoding="utf-8")
        return path


def exit_code_for(aggregate: Aggregate, threshold: float, *, rejected: bool = False,
                  cost_ceiling_hit: bool = False) -> int:
    """0 every case at or above threshold; 1 any below; 3 inconclusive."""
    totals = aggregate.totals()
    if rejected:
        return 3
    if totals["runs"] == 0:
        return 3
    below = [case for case in aggregate.cases if case.gating_runs and case.pass_rate < threshold]
    if below:
        return 1
    if not any(case.gating_runs for case in aggregate.cases):
        return 3
    if cost_ceiling_hit:
        return 3
    if totals["not_evaluated"] and totals["passed"] == 0:
        return 3
    return 0
