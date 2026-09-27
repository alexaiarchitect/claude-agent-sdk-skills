"""Reliability across repeated runs: pass@k and fragility.

An LLM agent is not deterministic, so one green run is one sample, not a result.
The question a suite should answer is not "does it work" but "how often does it
work, and where is it fragile".

The runner keeps every run separate (``--runs N`` inside one results directory,
or N invocations), so this module aggregates statuses rather than averaged
scores. ``pass@k`` is the probability that at least one of *k* independent
attempts passes, estimated without bias from *n* observed runs of which *c*
passed::

    pass@k = 1 - C(n - c, k) / C(n, k)

Read two numbers together: **pass@1** is how the agent behaves in production,
one shot per user request. The gap between pass@1 and pass@k is **fragility**:
how much the agent depends on being lucky or on retrying. ``pass^k``, the
chance that all *k* attempts pass, is the number for anything that must not
fail even once.

How many runs: 5 separates "usually works" from "often fails", but not 95% from
90%. Use 5 while iterating, 10-20 before a release, and 50-100 when qualifying
something that spends money or touches a person. On a subscription every run
draws on the plan's usage limits, so the guidance is the same and the budget is
quota rather than dollars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

RELIABLE = 0.95
MARGINAL = 0.70
DEFAULT_KS = (1, 3, 5)
RUN_GUIDANCE = {"iterating": 5, "pre_release": 20, "qualification": 50}


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k for `c` passing runs out of `n`, in product form."""
    if n <= 0 or k <= 0 or c <= 0:
        return 0.0
    k = min(k, n)
    if n - c < k:
        return 1.0
    probability = 1.0
    for i in range(k):
        probability *= (n - c - i) / (n - i)
    return 1.0 - probability


def pass_power_k(rate: float, k: int) -> float:
    """The chance that all `k` independent attempts pass."""
    return rate ** k if k > 0 else 0.0


def classify(rate: float) -> str:
    if rate >= RELIABLE:
        return "RELIABLE"
    if rate >= MARGINAL:
        return "MARGINAL"
    return "UNRELIABLE"


def runs_needed(goal: str = "iterating") -> int:
    return RUN_GUIDANCE.get(goal, 5)


def resolution_warning(n: int) -> str | None:
    if n < 3:
        return f"{n} run(s) cannot measure reliability at all; it only tells you the agent can pass once"
    if n < 10:
        return f"{n} runs separate 'usually works' from 'often fails', but not 95% from 90%; use 10-20 before a release"
    if n < 50:
        return f"{n} runs give a usable pre-release estimate; 50+ for release qualification"
    return None


@dataclass
class CaseReliability:
    case: str
    runs: int
    passes: int
    statuses: list[str] = field(default_factory=list)
    pass_at: dict[int, float] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.runs if self.runs else 0.0

    @property
    def tag(self) -> str:
        return classify(self.pass_rate)

    @property
    def not_evaluated(self) -> int:
        return sum(1 for status in self.statuses if status == "NOT_EVALUATED")

    @property
    def fragility(self) -> float:
        if not self.pass_at:
            return 0.0
        best = max(self.pass_at)
        return round(self.pass_at[best] - self.pass_at.get(1, 0.0), 4)

    @property
    def flaky(self) -> bool:
        return 0 < self.passes < self.runs

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case, "runs": self.runs, "passes": self.passes,
            "pass_rate": round(self.pass_rate, 4), "tag": self.tag, "flaky": self.flaky,
            "not_evaluated": self.not_evaluated,
            "pass_at": {str(k): round(v, 4) for k, v in sorted(self.pass_at.items())},
            "pass_power": {str(k): round(pass_power_k(self.pass_rate, k), 4) for k in sorted(self.pass_at)},
            "fragility": self.fragility, "statuses": self.statuses,
        }


@dataclass
class PassKReport:
    suite: str
    runs: int
    ks: list[int]
    cases: list[CaseReliability] = field(default_factory=list)
    perfect_runs: int = 0
    sources: list[str] = field(default_factory=list)
    warning: str | None = None

    @property
    def suite_pass_at(self) -> dict[int, float]:
        return {k: pass_at_k(self.runs, self.perfect_runs, k) for k in self.ks}

    @property
    def weakest(self) -> list[CaseReliability]:
        return sorted(self.cases, key=lambda c: (c.pass_rate, c.case))

    @property
    def unreliable(self) -> list[CaseReliability]:
        return [case for case in self.cases if case.tag != "RELIABLE"]

    @property
    def all_reliable(self) -> bool:
        return bool(self.cases) and not self.unreliable

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite, "runs": self.runs, "sources": self.sources, "ks": self.ks,
            "thresholds": {"reliable": RELIABLE, "marginal": MARGINAL},
            "perfect_runs": self.perfect_runs,
            "suite_pass_at": {str(k): round(v, 4) for k, v in self.suite_pass_at.items()},
            "cases": [case.to_dict() for case in self.weakest],
            "all_reliable": self.all_reliable, "warning": self.warning,
        }

    def to_md(self) -> str:
        lines = [f"## Reliability over {self.runs} run(s) — `{self.suite or 'suite'}`", ""]
        if self.warning:
            lines.extend([f"> {self.warning}", ""])
        header = "| case | passed | pass@1 | " + " | ".join(f"pass@{k}" for k in self.ks if k != 1)
        lines.append(header + " | pass^3 | fragility | verdict |")
        lines.append("|---" * (5 + max(0, len(self.ks) - 1)) + "|---|")
        for case in self.weakest:
            cells = [f"`{case.case}`", f"{case.passes}/{case.runs}", f"{case.pass_at.get(1, 0.0):.2f}"]
            cells.extend(f"{case.pass_at.get(k, 0.0):.2f}" for k in self.ks if k != 1)
            cells.append(f"{pass_power_k(case.pass_rate, 3):.2f}")
            cells.append(f"{case.fragility:+.2f}")
            cells.append(case.tag)
            lines.append("| " + " | ".join(cells) + " |")
        suite = self.suite_pass_at
        lines.extend(["", f"Whole-suite: {self.perfect_runs}/{self.runs} runs had every case pass "
                          f"(suite pass@1 {suite.get(1, 0.0):.2f})."])
        flaky = [case for case in self.cases if case.flaky]
        if flaky:
            lines.append("Flaky case(s) to investigate first: " + ", ".join(f"`{c.case}`" for c in flaky))
        never = [case for case in self.cases if case.not_evaluated]
        if never:
            lines.append("Case(s) with never-evaluated runs (excluded from passes, counted in runs): "
                         + ", ".join(f"`{c.case}` ({c.not_evaluated})" for c in never))
        return "\n".join(lines)


def aggregate(
    suite_runs: Sequence[Mapping[str, str]],
    *,
    ks: Iterable[int] = DEFAULT_KS,
    suite: str = "",
    sources: Sequence[str] = (),
) -> PassKReport:
    """Build a reliability report from suite runs: one `{case: status}` per run."""
    runs = [dict(r) for r in suite_runs]
    k_values = sorted({int(k) for k in ks if int(k) >= 1})
    report = PassKReport(suite=suite, runs=len(runs), ks=k_values, sources=list(sources))
    if not runs:
        report.warning = "no result files found"
        return report
    report.warning = resolution_warning(len(runs))

    by_case: dict[str, list[str]] = {}
    for run in runs:
        for case, status in run.items():
            by_case.setdefault(case, []).append(status)
        if run and all(status == "PASSED" for status in run.values()):
            report.perfect_runs += 1

    for case, statuses in sorted(by_case.items()):
        passes = sum(1 for status in statuses if status == "PASSED")
        reliability = CaseReliability(case=case, runs=len(statuses), passes=passes, statuses=statuses)
        reliability.pass_at = {k: pass_at_k(reliability.runs, passes, k) for k in k_values}
        report.cases.append(reliability)

    missing = [case.case for case in report.cases if case.runs != report.runs]
    if missing:
        note = ("case(s) missing from some runs (a case was added between runs, or a run stopped early): "
                + ", ".join(missing[:5]))
        report.warning = f"{report.warning}; {note}" if report.warning else note
    return report
