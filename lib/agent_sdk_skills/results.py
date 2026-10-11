"""Read the runner's result files.

The runner writes one directory per invocation, ``evals/results/<timestamp>/``,
holding ``<case>.result.json`` per case, ``<case>.<n>.trace.jsonl`` per run and
one ``aggregate.json`` (shapes: `.dev/CONTRACTS.md` §5–§7, schema strings
``agent-sdk-skills.result/1`` and ``agent-sdk-skills.aggregate/1``).

Four statuses, always counted separately:

===============  ==================================================
PASSED           every grader met its threshold
FAILED           at least one grader failed
NOT_EVALUATED    a grader could not run: judge unreachable, usage limit
                 rejected, imported session without cost, hook not installed
INFORMATIONAL    a `budget` grader marked `informational`: a value, no verdict
===============  ==================================================

`NOT_EVALUATED` is not a regression: the fix is configuration, credentials or
quota, not the agent. Reliability needs samples, so this module can gather the
statuses of one case across the runs inside a result file **and** across
several result directories (``--runs 3`` once, or ``--runs 1`` three times give
the same three samples).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

RESULT_SCHEMA = "agent-sdk-skills.result/1"
AGGREGATE_SCHEMA = "agent-sdk-skills.aggregate/1"
RESULT_SUFFIX = ".result.json"
AGGREGATE_NAME = "aggregate.json"
STATUSES = ("PASSED", "FAILED", "NOT_EVALUATED", "INFORMATIONAL")


@dataclass
class GraderVerdict:
    name: str
    type: str
    status: str
    score: float | None = None
    votes: list[str] = field(default_factory=list)
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def tier(self) -> str:
        return "judge" if self.type == "llm" else "free"

    def to_dict(self) -> dict[str, Any]:
        data = {"name": self.name, "type": self.type, "status": self.status, "score": self.score,
                "tier": self.tier}
        if self.votes:
            data["votes"] = self.votes
        if self.reason:
            data["reason"] = self.reason
        return data


@dataclass
class RunRecord:
    """One execution of one case."""

    run: int
    status: str
    trace: str | None = None
    graders: list[GraderVerdict] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    rate_limit: dict[str, Any] | None = None
    error: str | None = None

    @property
    def cost_usd(self) -> float:
        value = self.result.get("total_cost_usd")
        return float(value) if isinstance(value, (int, float)) else 0.0

    @property
    def num_turns(self) -> int | None:
        value = self.result.get("num_turns")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def usage(self) -> dict[str, Any]:
        usage = self.result.get("usage")
        return usage if isinstance(usage, dict) else {}

    @property
    def model_usage(self) -> dict[str, dict[str, Any]]:
        """Per-model usage, defensively. Never indexed: the wire carries keys
        (`costBasis`, `thinkingTokens`) the pinned `ModelUsage` TypedDict does
        not declare, so every read goes through `.get()`."""
        usage = self.result.get("model_usage")
        if not isinstance(usage, dict):
            return {}
        return {str(k): dict(v) for k, v in usage.items() if isinstance(v, dict)}

    @property
    def models_billed(self) -> list[str]:
        """Every model this run was billed for, not the model that ran.

        Measured 2026-10-11: CLI 2.1.294 bills its own background work to
        `claude-haiku-5-5` unasked, so the cost is spread over more than one
        model and a reader must loop rather than take the first entry.
        """
        recorded = self.result.get("models_billed")
        if isinstance(recorded, (list, tuple)):
            return [str(name) for name in recorded]
        return sorted(self.model_usage)

    @property
    def cost_basis_list(self) -> bool | None:
        """True when every billed model priced at list; None when unknown.

        `costBasis` is `list | managed | unknown`; absent counts as list.
        """
        recorded = self.result.get("cost_basis_list")
        if isinstance(recorded, bool):
            return recorded
        usage = self.model_usage
        if not usage:
            return None
        return all(entry.get("costBasis", "list") == "list" for entry in usage.values())

    @property
    def thinking_tokens(self) -> float:
        """Thinking tokens: the session figure, else summed over billed models."""
        value = self.usage.get("thinking_tokens")
        if isinstance(value, (int, float)):
            return float(value)
        return sum(
            float(entry.get("thinkingTokens") or 0) for entry in self.model_usage.values()
        )

    def failed_graders(self) -> list[GraderVerdict]:
        return [g for g in self.graders if g.status == "FAILED"]

    def not_evaluated_graders(self) -> list[GraderVerdict]:
        return [g for g in self.graders if g.status == "NOT_EVALUATED"]

    def informational_graders(self) -> list[GraderVerdict]:
        return [g for g in self.graders if g.status == "INFORMATIONAL"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run, "status": self.status, "trace": self.trace,
            "graders": [g.to_dict() for g in self.graders],
            "cost_usd": round(self.cost_usd, 6), "num_turns": self.num_turns,
            "terminal_reason": self.result.get("terminal_reason"),
            "subtype": self.result.get("subtype"),
            "models_billed": self.models_billed,
            "cost_basis_list": self.cost_basis_list,
            "rate_limit": self.rate_limit, "error": self.error,
        }


@dataclass
class CaseResult:
    path: str
    case: str
    category: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    runs: list[RunRecord] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    schema: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def statuses(self) -> list[str]:
        return [run.status for run in self.runs]

    def count(self, status: str) -> int:
        return sum(1 for run in self.runs if run.status == status)

    @property
    def pass_rate(self) -> float:
        return self.count("PASSED") / len(self.runs) if self.runs else 0.0

    @property
    def cost_usd(self) -> float:
        return round(sum(run.cost_usd for run in self.runs), 6)

    @property
    def worst_run(self) -> RunRecord | None:
        order = {"FAILED": 0, "NOT_EVALUATED": 1, "INFORMATIONAL": 2, "PASSED": 3}
        return min(self.runs, key=lambda r: order.get(r.status, 9), default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "case": self.case, "category": self.category,
            "config": self.config, "runs": [run.to_dict() for run in self.runs],
            "summary": self.summary, "pass_rate": round(self.pass_rate, 4),
            "cost_usd": self.cost_usd, "error": self.error,
        }


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"unreadable: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(doc, dict):
        return None, "top level is not an object"
    return doc, None


def parse_result(path: Path | str) -> CaseResult:
    file = Path(path)
    result = CaseResult(path=str(file), case=file.name[: -len(RESULT_SUFFIX)] if file.name.endswith(RESULT_SUFFIX) else file.stem)
    doc, error = _load_json(file)
    if error:
        result.error = error
        return result
    result.schema = doc.get("schema")
    if result.schema != RESULT_SCHEMA:
        result.error = f"unknown schema {result.schema!r} (expected {RESULT_SCHEMA})"
        return result
    result.case = str(doc.get("case") or result.case)
    result.category = doc.get("category")
    result.config = doc.get("config") if isinstance(doc.get("config"), dict) else {}
    result.summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    for index, raw in enumerate(doc.get("runs") or [], start=1):
        if not isinstance(raw, dict):
            continue
        graders = []
        for entry in raw.get("graders") or []:
            if not isinstance(entry, dict):
                continue
            graders.append(GraderVerdict(
                name=str(entry.get("name", "?")), type=str(entry.get("type", "?")),
                status=str(entry.get("status", "UNKNOWN")).upper(),
                score=entry.get("score") if isinstance(entry.get("score"), (int, float)) else None,
                votes=[str(v) for v in entry.get("votes") or []],
                reason=entry.get("reason"),
                detail={k: v for k, v in entry.items() if k not in ("name", "type", "status", "score", "votes", "reason")},
            ))
        result.runs.append(RunRecord(
            run=int(raw.get("run") or index), status=str(raw.get("status", "UNKNOWN")).upper(),
            trace=raw.get("trace"), graders=graders,
            result=raw.get("result") if isinstance(raw.get("result"), dict) else {},
            rate_limit=raw.get("rate_limit") if isinstance(raw.get("rate_limit"), dict) else None,
            error=raw.get("error"),
        ))
    return result


@dataclass
class Aggregate:
    path: str
    tier: str | None = None
    started: str | None = None
    finished: str | None = None
    cases: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = None
    runner_version: str | None = None
    sdk_version: str | None = None
    cli_version: str | None = None
    credential: dict[str, Any] = field(default_factory=dict)
    rate_limit: dict[str, Any] | None = None
    stopped: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def cost_basis(self) -> str | None:
        return self.totals.get("cost_basis") or self.credential.get("kind")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def parse_aggregate(path: Path | str) -> Aggregate:
    file = Path(path)
    aggregate = Aggregate(path=str(file))
    doc, error = _load_json(file)
    if error:
        aggregate.error = error
        return aggregate
    if doc.get("schema") != AGGREGATE_SCHEMA:
        aggregate.error = f"unknown schema {doc.get('schema')!r} (expected {AGGREGATE_SCHEMA})"
        return aggregate
    aggregate.tier = doc.get("tier")
    aggregate.started = doc.get("started")
    aggregate.finished = doc.get("finished")
    aggregate.cases = [c for c in doc.get("cases") or [] if isinstance(c, dict)]
    aggregate.totals = doc.get("totals") if isinstance(doc.get("totals"), dict) else {}
    aggregate.exit_code = doc.get("exit_code") if isinstance(doc.get("exit_code"), int) else None
    aggregate.runner_version = doc.get("runner_version")
    aggregate.sdk_version = doc.get("sdk_version")
    aggregate.cli_version = doc.get("cli_version")
    aggregate.credential = doc.get("credential") if isinstance(doc.get("credential"), dict) else {}
    aggregate.rate_limit = doc.get("rate_limit") if isinstance(doc.get("rate_limit"), dict) else None
    aggregate.stopped = doc.get("stopped") if isinstance(doc.get("stopped"), dict) else None
    return aggregate


@dataclass
class RunDir:
    """One `results/<timestamp>/` directory."""

    path: str
    aggregate: Aggregate | None = None
    cases: dict[str, CaseResult] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def ok(self) -> bool:
        return bool(self.cases) or (self.aggregate is not None and self.aggregate.ok)

    def status_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for case in self.cases.values():
            for run in case.runs:
                if run.status in counts:
                    counts[run.status] += 1
        return counts

    @property
    def is_clean(self) -> bool:
        counts = self.status_counts()
        return counts["FAILED"] == 0 and counts["NOT_EVALUATED"] == 0 and counts["PASSED"] > 0

    def suite_runs(self) -> list[dict[str, str]]:
        """Split the directory into per-index suite runs: the i-th run of every case."""
        width = max((len(case.runs) for case in self.cases.values()), default=0)
        return [
            {name: case.runs[i].status for name, case in self.cases.items() if i < len(case.runs)}
            for i in range(width)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "name": self.name,
            "aggregate": self.aggregate.to_dict() if self.aggregate else None,
            "cases": {name: case.to_dict() for name, case in self.cases.items()},
            "status_counts": self.status_counts(), "is_clean": self.is_clean,
        }


def results_root(target: Path | str) -> Path | None:
    """Accept a project, an `evals/` dir, a `results/` dir or one run directory."""
    path = Path(target).expanduser().resolve()
    if (path / AGGREGATE_NAME).is_file() or any(path.glob(f"*{RESULT_SUFFIX}")):
        return path
    for candidate in (path / "results", path / "evals" / "results"):
        if candidate.is_dir():
            return candidate
    if path.name == "results" and path.is_dir():
        return path
    return None


def find_run_dirs(target: Path | str) -> list[Path]:
    root = results_root(target)
    if root is None:
        return []
    if (root / AGGREGATE_NAME).is_file() or any(root.glob(f"*{RESULT_SUFFIX}")):
        return [root]
    return sorted(p for p in root.iterdir() if p.is_dir() and (
        (p / AGGREGATE_NAME).is_file() or any(p.glob(f"*{RESULT_SUFFIX}"))))


def load_run_dir(path: Path | str) -> RunDir:
    directory = Path(path)
    run = RunDir(path=str(directory))
    aggregate = directory / AGGREGATE_NAME
    if aggregate.is_file():
        run.aggregate = parse_aggregate(aggregate)
    for file in sorted(directory.glob(f"*{RESULT_SUFFIX}")):
        case = parse_result(file)
        run.cases[case.case] = case
    return run


def load_all(target: Path | str, *, last: int | None = None) -> list[RunDir]:
    dirs = find_run_dirs(target)
    if last:
        dirs = dirs[-last:]
    return [load_run_dir(d) for d in dirs]


def latest(target: Path | str) -> RunDir | None:
    dirs = find_run_dirs(target)
    return load_run_dir(dirs[-1]) if dirs else None


def samples_by_case(run_dirs: Iterable[RunDir], *, case: str | None = None) -> dict[str, list[str]]:
    """Every observed status per case, across directories and inner runs."""
    samples: dict[str, list[str]] = {}
    for run_dir in run_dirs:
        for name, result in run_dir.cases.items():
            if case and name != case:
                continue
            samples.setdefault(name, []).extend(result.statuses())
    return samples


def suite_runs(run_dirs: Iterable[RunDir]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for run_dir in run_dirs:
        out.extend(run_dir.suite_runs())
    return out


def efficiency_rows(run_dirs: Iterable[RunDir]) -> list[dict[str, Any]]:
    """Per case: mean turns, tokens and cost over every observed run (lower is better)."""
    rows: dict[str, dict[str, Any]] = {}
    for run_dir in run_dirs:
        for name, result in run_dir.cases.items():
            row = rows.setdefault(name, {"case": name, "runs": 0, "turns": 0.0, "input_tokens": 0.0,
                                         "output_tokens": 0.0, "cache_read": 0.0, "cost_usd": 0.0,
                                         "duration_ms": 0.0, "models_billed": [],
                                         "cost_basis": result.config.get("cost_basis")})
            for run in result.runs:
                row["runs"] += 1
                for model in run.models_billed:
                    if model not in row["models_billed"]:
                        row["models_billed"].append(model)
                row["turns"] += run.num_turns or 0
                row["input_tokens"] += float(run.usage.get("input_tokens") or 0)
                row["output_tokens"] += float(run.usage.get("output_tokens") or 0)
                row["cache_read"] += float(run.usage.get("cache_read_input_tokens") or 0)
                row["cost_usd"] += run.cost_usd
                row["duration_ms"] += float(run.result.get("duration_ms") or 0)
    out = []
    for row in rows.values():
        n = row["runs"] or 1
        out.append({
            "case": row["case"], "runs": row["runs"], "cost_basis": row["cost_basis"],
            "mean_turns": round(row["turns"] / n, 2),
            "mean_input_tokens": round(row["input_tokens"] / n),
            "mean_output_tokens": round(row["output_tokens"] / n),
            "mean_cache_read_tokens": round(row["cache_read"] / n),
            "mean_cost_usd": round(row["cost_usd"] / n, 4),
            "mean_duration_ms": round(row["duration_ms"] / n),
            "models_billed": sorted(row["models_billed"]),
        })
    return sorted(out, key=lambda r: -r["mean_cost_usd"])


def not_evaluated_cause(run: RunRecord) -> str:
    """The likely reason a run or grader never produced a verdict."""
    if run.rate_limit and run.rate_limit.get("status") == "rejected":
        return "usage limit rejected the request; wait for the reset shown in the aggregate"
    if run.result.get("api_error_status") == 429:
        return "the API returned 429; rate or usage limit"
    if run.error:
        return f"run error: {run.error}"
    types = {g.type for g in run.not_evaluated_graders()}
    if "llm" in types:
        return "the judge call did not return a verdict (credential, quota, or the judge model refused)"
    if "hook_event" in types:
        return "no hook was installed for the event the grader names"
    if types & {"budget", "terminal"}:
        return "no result event: an imported session carries no cost or terminal fields"
    return "a grader could not run; read its reason in the result file"
