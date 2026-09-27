"""LLM-as-judge through the SDK (CONTRACTS section 9).

The judge options are not a style choice; each one was measured.

* `tools=[]` **and** `allowed_tools=[]` — `allowed_tools` only governs
  prompting; `tools=[]` is what actually disables the built-ins.
* `strict_mcp_config=True` — otherwise ambient MCP servers reach a judge that
  was supposed to have no tools at all.
* `setting_sources=[]` — without it a judge call loaded 21 KB of the host's
  settings and CLAUDE.md and cost 17x more for the same verdict.
* `effort="low"`, `max_turns=1`, `permission_mode="dontAsk"` — one cheap pass.
* `output_format` with the VERDICT schema, so the verdict arrives as parsed
  `structured_output` rather than prose to regex.

`samples` calls vote; the majority wins and every vote is recorded, so a 2-1
split is visible in the result file rather than hidden behind a PASS. A judge
call that errors makes the grader NOT_EVALUATED, never FAILED: a broken judge is
not evidence about the agent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from . import DEFAULT_JUDGE_MODEL, FAILED, NOT_EVALUATED, PASSED

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["PASS", "FAIL"]},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "reason"],
}

PROMPT = """You are grading one run of an AI agent against a single rubric.

Rubric (the only thing you are judging):
{criteria}
{focus}
Evidence from the run:
<evidence>
{evidence}
</evidence>

Decide PASS or FAIL against the rubric alone. Do not reward or punish anything
the rubric does not mention. Quote the evidence you relied on. If the evidence
does not contain what the rubric asks about, FAIL and say what was missing.
Answer through the structured output schema only."""

EVIDENCE_LIMIT = 24000


@dataclass
class JudgeConfig:
    model: str = DEFAULT_JUDGE_MODEL
    samples: int = 3
    vote: str = "majority"
    effort: str = "low"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "JudgeConfig":
        data = data or {}
        return cls(
            model=str(data.get("model") or DEFAULT_JUDGE_MODEL),
            samples=max(1, int(data.get("samples") or 1)),
            vote=str(data.get("vote") or "majority"),
            effort=str(data.get("effort") or "low"),
        )


@dataclass
class JudgeOutcome:
    status: str
    votes: list[str] = field(default_factory=list)
    reason: str = ""
    cost_usd: float = 0.0


def build_options(config: JudgeConfig, options_cls: Any, model: str | None = None) -> Any:
    """The exact judge options. Kept in one place so a test can assert on them."""
    return options_cls(
        model=model or config.model,
        tools=[],
        allowed_tools=[],
        max_turns=1,
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        effort=config.effort,
        output_format={"type": "json_schema", "schema": VERDICT_SCHEMA},
    )


def build_prompt(criteria: str, evidence: str, focus: str | None = None) -> str:
    return PROMPT.format(
        criteria=criteria.strip(),
        focus=f"\nPay particular attention to: {focus}\n" if focus else "",
        evidence=evidence[:EVIDENCE_LIMIT],
    )


def parse_verdict(result: dict[str, Any] | None, text: str = "") -> tuple[str | None, str]:
    """Read PASS/FAIL out of a result, preferring the parsed structured output."""
    payload = (result or {}).get("structured_output")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict) and str(payload.get("verdict", "")).upper() in ("PASS", "FAIL"):
        return str(payload["verdict"]).upper(), str(payload.get("reason") or "")
    # A judge whose model ignored the schema still said something usable.
    haystack = (text or (result or {}).get("result_text") or "").upper()
    if "FAIL" in haystack and "PASS" not in haystack:
        return "FAIL", (text or "").strip()[:400]
    if "PASS" in haystack and "FAIL" not in haystack:
        return "PASS", (text or "").strip()[:400]
    return None, (text or "").strip()[:400]


def tally(votes: list[str], vote_rule: str = "majority") -> str:
    """Majority of PASS/FAIL; a tie is a FAIL (the conservative reading)."""
    usable = [v for v in votes if v in ("PASS", "FAIL")]
    if not usable:
        return NOT_EVALUATED
    if vote_rule == "unanimous":
        return PASSED if all(v == "PASS" for v in usable) else FAILED
    if vote_rule == "any":
        return PASSED if any(v == "PASS" for v in usable) else FAILED
    passes = usable.count("PASS")
    return PASSED if passes * 2 > len(usable) else FAILED


class Judge:
    """Runs judge calls through the SDK and adds their cost to the run."""

    def __init__(self, config: JudgeConfig, sdk: Any) -> None:
        self.config = config
        self.sdk = sdk
        self.cost_usd = 0.0
        self.calls = 0

    async def _one_call(self, prompt: str, model: str | None) -> tuple[str | None, str, float]:
        from .capture import Capture

        options = build_options(self.config, self.sdk.ClaudeAgentOptions, model)
        capture = Capture(run_id="judge", case="judge")
        async for message in self.sdk.query(prompt=prompt, options=options):
            capture.add(message)
        self.calls += 1
        cost = float((capture.result or {}).get("total_cost_usd") or 0.0)
        self.cost_usd += cost
        verdict_value, reason = parse_verdict(capture.result, capture.last_message)
        return verdict_value, reason, cost

    async def run(self, criteria: str, evidence: str, *, focus: str | None = None,
                  samples: int | None = None, model: str | None = None) -> JudgeOutcome:
        prompt = build_prompt(criteria, evidence, focus)
        wanted = max(1, int(samples if samples is not None else self.config.samples))
        votes: list[str] = []
        reasons: list[str] = []
        cost = 0.0
        errors: list[str] = []
        for _ in range(wanted):
            try:
                verdict_value, reason, call_cost = await self._one_call(prompt, model)
            except Exception as exc:  # a broken judge is not evidence about the agent
                errors.append(f"{type(exc).__name__}: {exc}")
                continue
            cost += call_cost
            if verdict_value:
                votes.append(verdict_value)
                if reason:
                    reasons.append(reason)
            else:
                errors.append("the judge returned no PASS/FAIL verdict")
        if not votes:
            return JudgeOutcome(
                status=NOT_EVALUATED,
                votes=[],
                reason="the judge could not be reached or returned nothing usable: "
                       + "; ".join(errors[:3]),
                cost_usd=cost,
            )
        status = tally(votes, self.config.vote)
        summary = reasons[0] if reasons else ""
        if len(set(votes)) > 1:
            summary = f"split vote {votes}: {summary}"
        return JudgeOutcome(status=status, votes=votes, reason=summary, cost_usd=cost)
