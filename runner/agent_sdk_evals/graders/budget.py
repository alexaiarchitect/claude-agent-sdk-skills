"""`budget`: the ceilings a run must stay under.

Three measured corrections live here.

* **`max_turns` is the grader's own ceiling, not the option's.** A run with
  `max_turns=1` reported `num_turns=2` and still succeeded, because the
  `StructuredOutput` round trip counts as a turn without tripping the limit. To
  assert that the limit *tripped*, use a `terminal` grader.
* **The token keys are the SDK's, not the plan's.** `max_input_tokens` reads
  `usage.input_tokens`, `max_output_tokens` reads `usage.output_tokens`. Cache
  tokens have their own two ceilings. `usage.cache_creation` is a nested dict of
  ephemeral TTL buckets and is never treated as a count.
* **`max_cost_usd` compares the case total**, which is the last
  `total_cost_usd` of the session — that field is a running total, not a
  per-turn figure.

`informational: true` reports the numbers and never gates: the honest setting
while a suite is still learning what its own costs look like.
"""

from __future__ import annotations

from typing import Any

from . import Evidence, GraderResult, not_evaluated, verdict

#: grader field -> (where to read it, human label)
CEILINGS: dict[str, tuple[str, str]] = {
    "max_cost_usd": ("cost", "est. cost USD"),
    "max_turns": ("result.num_turns", "turns"),
    "max_duration_ms": ("result.duration_ms", "duration ms"),
    "max_input_tokens": ("usage.input_tokens", "input tokens"),
    "max_output_tokens": ("usage.output_tokens", "output tokens"),
    "max_cache_read_tokens": ("usage.cache_read_input_tokens", "cache read tokens"),
    "max_cache_creation_tokens": ("usage.cache_creation_input_tokens", "cache creation tokens"),
}


def observed_value(source: str, evidence: Evidence) -> Any:
    result = evidence.result or {}
    if source == "cost":
        return evidence.case_cost_usd
    section, _, key = source.partition(".")
    if section == "result":
        return result.get(key)
    if section == "usage":
        return (result.get("usage") or {}).get(key)
    return None


def grade_budget(grader: Any, evidence: Evidence) -> GraderResult:
    if evidence.result is None:
        return not_evaluated(
            grader,
            "no result message: an imported Claude Code session carries no cost, turn count or "
            "usage, so a budget grader cannot be decided on one",
        )
    checks: list[str] = []
    breaches: list[str] = []
    for field_name, (source, label) in CEILINGS.items():
        ceiling = grader.get(field_name)
        if ceiling is None:
            continue
        value = observed_value(source, evidence)
        if value is None:
            checks.append(f"{label}: not reported")
            continue
        over = float(value) > float(ceiling)
        rendered = f"{label} {value} vs ceiling {ceiling}"
        checks.append(rendered)
        if over:
            breaches.append(rendered)
    if not checks:
        return not_evaluated(grader, "no ceiling on this grader could be read from the result")
    return verdict(grader, not breaches,
                   ("over budget: " + "; ".join(breaches)) if breaches
                   else "within budget: " + "; ".join(checks))
