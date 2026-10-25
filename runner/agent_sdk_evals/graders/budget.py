"""`budget`: the ceilings a run must stay under.

Three measured corrections live here.

* **`max_turns` is the grader's own ceiling, not the option's.** A run with
  `max_turns=1` reported `num_turns=2` and still succeeded, because the
  `StructuredOutput` round trip counts as a turn without tripping the limit. To
  assert that the limit *tripped*, use a `terminal` grader. To size the option,
  count each turn with tool calls plus one for the final text-only response
  (docs agent-loop, read 2026-10-29).
* **The token keys are the SDK's, not the plan's.** `max_input_tokens` reads
  `usage.input_tokens`, `max_output_tokens` reads `usage.output_tokens`. Cache
  tokens have their own two ceilings. `usage.cache_creation` is a nested dict of
  ephemeral TTL buckets and is never treated as a count.
* **`max_cost_usd` compares the case total**, which is the last
  `total_cost_usd` of the session — that field is a running total, not a
  per-turn figure. It is also the grader's own ceiling, not the option's:
  `ClaudeAgentOptions.max_budget_usd` is a **soft** cap, so a session can finish
  having passed it and only the *next* request is refused. Leave headroom on
  both, and assert that the option tripped with a `terminal` grader
  (`subtype: error_max_budget_usd`).
* **The cost is spread over more than one model.** Measured 2026-10-11 on CLI
  2.1.294 (and again on 2.1.301 and 2.1.310), `model_usage` carried a second
  entry for `claude-haiku-5-5`, which the CLI billed for its own background work. The trace `result` event records
  `models_billed` and `cost_basis_list` so a reader never takes the first entry
  for the total; `costBasis` and `thinkingTokens` are read with `.get()`
  because neither is declared on the `ModelUsage` TypedDict (0.2.165 through 0.2.174).

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
