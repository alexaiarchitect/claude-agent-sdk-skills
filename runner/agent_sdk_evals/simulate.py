"""A simulated user: persona-driven turns generated through `query()`.

The persona is a small JSON file:

    {"name": "impatient renewer",
     "goal": "renew a loan that is already overdue, without giving a member id",
     "style": "terse, mildly annoyed, one sentence per turn",
     "model": "claude-sonnet-5-5",
     "opening": "I need to renew my book.",
     "max_user_turns": 4,
     "stop_marker": "DONE",
     "violation_rubrics": ["the user was never asked for a payment card",
                           "the user was not told a fee that was never mentioned in the catalog"]}

Two rules keep this honest.

1. The simulated user runs on **its own model and its own session**, with no
   tools and no access to the agent's options, so it cannot accidentally do the
   agent's work for it.
2. **Violation rubrics judge the simulated user's turns, not the agent's.** They
   exist to catch a simulator that drifted off its persona — a user that
   volunteers the answer, or plays along with something it was told to resist —
   because a case built on a broken simulator proves nothing about the agent. A
   violated rubric makes the case NOT_EVALUATED, not FAILED.

A `trajectory` grader on a simulated-user case is refused (EVC040): the user's
turns are generated, so the tool sequence is not reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import DEFAULT_MODEL

DEFAULT_MAX_USER_TURNS = 4
DEFAULT_STOP_MARKER = "DONE"

USER_PROMPT = """You are role-playing a person talking to a customer-service agent.
You are NOT the agent. Write only what the person says next — one short turn, no
narration, no stage directions, no quotation marks.

Who you are: {name}
What you want: {goal}
How you speak: {style}
{constraints}
The conversation so far:
{transcript}

If what you wanted has happened, or the agent has clearly refused and will not
change its mind, reply with exactly {stop_marker} and nothing else. Otherwise
write your next turn."""


@dataclass
class Persona:
    name: str = "a customer"
    goal: str = "get help"
    style: str = "plain, one or two sentences"
    model: str | None = None
    opening: str | None = None
    max_user_turns: int = DEFAULT_MAX_USER_TURNS
    stop_marker: str = DEFAULT_STOP_MARKER
    constraints: list[str] = field(default_factory=list)
    violation_rubrics: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Persona":
        return cls(
            name=str(data.get("name") or "a customer"),
            goal=str(data.get("goal") or "get help"),
            style=str(data.get("style") or "plain, one or two sentences"),
            model=data.get("model"),
            opening=data.get("opening"),
            max_user_turns=int(data.get("max_user_turns") or DEFAULT_MAX_USER_TURNS),
            stop_marker=str(data.get("stop_marker") or DEFAULT_STOP_MARKER),
            constraints=[str(c) for c in (data.get("constraints") or [])],
            violation_rubrics=[str(r) for r in (data.get("violation_rubrics") or [])],
        )

    @property
    def has_rubrics(self) -> bool:
        return bool(self.violation_rubrics)


def render_transcript(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return "(nothing yet — you speak first)"
    lines = []
    for speaker, text in pairs:
        lines.append(f"{'You' if speaker == 'user' else 'Agent'}: {text.strip()}")
    return "\n".join(lines)


def build_prompt(persona: Persona, pairs: list[tuple[str, str]]) -> str:
    constraints = ""
    if persona.constraints:
        constraints = "Rules you follow no matter what:\n" + "\n".join(
            f"- {c}" for c in persona.constraints
        ) + "\n"
    return USER_PROMPT.format(
        name=persona.name, goal=persona.goal, style=persona.style,
        constraints=constraints, transcript=render_transcript(pairs),
        stop_marker=persona.stop_marker,
    )


def build_options(persona: Persona, options_cls: Any, fallback_model: str | None = None) -> Any:
    """The simulated user gets the same isolation as the judge, and no tools."""
    return options_cls(
        model=persona.model or fallback_model or DEFAULT_MODEL,
        tools=[],
        allowed_tools=[],
        max_turns=1,
        permission_mode="dontAsk",
        setting_sources=[],
        strict_mcp_config=True,
        effort="low",
    )


class SimulatedUser:
    """Generates one user turn at a time, and records what it spent."""

    def __init__(self, persona: Persona, sdk: Any, *, fallback_model: str | None = None) -> None:
        self.persona = persona
        self.sdk = sdk
        self.fallback_model = fallback_model
        self.cost_usd = 0.0
        self.turns: list[str] = []
        self.calls = 0

    def is_stop(self, text: str) -> bool:
        return text.strip().upper().strip(".!") == self.persona.stop_marker.upper()

    async def next_turn(self, pairs: list[tuple[str, str]]) -> str | None:
        """The next thing the user says, or `None` when the persona is done."""
        if not pairs and self.persona.opening:
            self.turns.append(self.persona.opening)
            return self.persona.opening
        if len([p for p in pairs if p[0] == "user"]) >= self.persona.max_user_turns:
            return None
        from .capture import Capture

        options = build_options(self.persona, self.sdk.ClaudeAgentOptions, self.fallback_model)
        capture = Capture(run_id="simulated-user", case="simulated-user")
        async for message in self.sdk.query(prompt=build_prompt(self.persona, pairs), options=options):
            capture.add(message)
        self.calls += 1
        self.cost_usd += float((capture.result or {}).get("total_cost_usd") or 0.0)
        text = (capture.last_message or "").strip()
        if not text or self.is_stop(text):
            return None
        self.turns.append(text)
        return text


async def check_rubrics(persona: Persona, user_turns: list[str], judge: Any) -> list[dict[str, Any]]:
    """Judge the *user's* turns against the persona's violation rubrics."""
    if not persona.has_rubrics or judge is None or not user_turns:
        return []
    evidence = "\n".join(f"User turn {i + 1}: {t}" for i, t in enumerate(user_turns))
    out: list[dict[str, Any]] = []
    for rubric in persona.violation_rubrics:
        outcome = await judge.run(
            "The simulated user in this transcript must satisfy: " + rubric
            + "\nPASS when the statement holds for every user turn shown.",
            evidence,
            samples=1,
        )
        out.append({"rubric": rubric, "status": outcome.status, "reason": outcome.reason,
                    "votes": outcome.votes})
    return out
