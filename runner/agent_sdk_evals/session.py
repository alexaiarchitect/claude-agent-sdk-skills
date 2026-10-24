"""Drive one run: build the options, talk to the agent, capture everything.

The capture loop is the one the SDK's own docs use and the one P-1 measured:

    async with ClaudeSDKClient(options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            capture.add(message)

`receive_response()` stops after the `ResultMessage`; `receive_messages()` never
terminates, so it is not used here. A scripted multi-turn case loops `query()` on
the *same* client, which is why `total_cost_usd` has to be diffed rather than
summed — it is a session running total.

Exception mapping is CONTRACTS section 8. `ResultError` is caught **before**
`ProcessError` because it subclasses it, and it is the useful one: it carries
`terminal_reason`, `subtype` and `api_error_status`, so the runner branches on
fields instead of matching strings. Its `data` is the raw result, and
`data["stop_reason"]` is read first: a refusal or a deferred tool missing on
resume ends with `is_error=True` on `subtype="success"` and is not an API error
(Python SDK docs, Claude Code 2.1.310). `MessageParseError` is deliberately not
imported — it is not exported from the package root — so `ClaudeSDKError` is the
catch-all.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import FAILED, NOT_EVALUATED, PASSED
from .capture import Capture, looks_like_usage_limit, rate_limit_payload, result_outcome
from .loader import Case, Config, resolve_permission_mode


@dataclass
class RunOutcome:
    """Everything one run produced, graded or not."""

    run: int
    case: str
    capture: Capture
    cwd: Path | None = None
    cwd_kept: bool = False
    mock_calls: list[dict[str, Any]] = field(default_factory=list)
    simulated_user_turns: list[str] = field(default_factory=list)
    rubric_checks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None
    not_evaluated: bool = False
    exit_hint: int = 0
    extra_cost_usd: float = 0.0

    @property
    def rate_limit(self) -> dict[str, Any] | None:
        return self.capture.rate_limit

    @property
    def rejected(self) -> bool:
        return self.capture.rejected_rate_limit is not None


#: exception class name -> (exit code, what to tell the user)
EXCEPTION_MAP: dict[str, tuple[int, str]] = {
    "CLINotFoundError": (2, "the Claude Code CLI could not be found; install the SDK in this "
                            "project's interpreter: python3 -m venv .venv && "
                            ".venv/bin/pip install claude-agent-sdk"),
    "CLIConnectionError": (2, "could not connect to the Claude Code CLI"),
    "CLIJSONDecodeError": (2, "the CLI emitted a line the SDK could not parse"),
    "ProcessError": (2, "the CLI subprocess failed"),
    "ClaudeSDKError": (2, "the SDK raised an error"),
}


def classify_exception(exc: BaseException) -> tuple[int, str, str]:
    """Return (exit code, kind, message). `ResultError` is checked first."""
    name = type(exc).__name__
    if name == "ResultError":
        subtype = getattr(exc, "subtype", None)
        reason = getattr(exc, "terminal_reason", None)
        status = getattr(exc, "api_error_status", None)
        text = getattr(exc, "result", None) or str(exc)
        data = getattr(exc, "data", None)
        stop_reason = data.get("stop_reason") if isinstance(data, dict) else None
        outcome = result_outcome(subtype, True, stop_reason)
        if outcome == "refusal":
            return 1, "refusal", (
                f"the model declined the request (stop_reason='refusal', subtype={subtype!r}, "
                f"terminal_reason={reason!r}): {text}"
            )
        if outcome == "tool_deferred":
            return 1, "tool_deferred", (
                "a deferred tool was not available when the session resumed "
                f"(stop_reason='tool_deferred_unavailable', subtype={subtype!r}): {text}"
            )
        if looks_like_usage_limit(str(text), status):
            return 3, "usage_limit", (
                f"the run hit a usage limit (subtype={subtype!r}, terminal_reason={reason!r}, "
                f"api_error_status={status!r}): {text}"
            )
        return 1, "result_error", (
            f"the run ended in an error result (subtype={subtype!r}, "
            f"terminal_reason={reason!r}, api_error_status={status!r}): {text}"
        )
    for candidate in type(exc).__mro__:
        if candidate.__name__ in EXCEPTION_MAP:
            code, note = EXCEPTION_MAP[candidate.__name__]
            detail = f"{note}: {exc}"
            extra = []
            for attribute in ("exit_code", "stderr", "line", "original_error", "cli_path"):
                value = getattr(exc, attribute, None)
                if value:
                    extra.append(f"{attribute}={value!r}")
            if extra:
                detail += " [" + ", ".join(extra) + "]"
            return code, candidate.__name__, detail
    return 2, name, f"{name}: {exc}"


async def run_scaffold(script: str, cwd: Path, env: dict[str, str]) -> str:
    """Run a case's `scaffold_script` in the fresh working directory."""
    process = await asyncio.create_subprocess_shell(
        script, cwd=str(cwd), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await process.communicate()
    text = (out or b"").decode("utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(f"scaffold_script exited {process.returncode}: {text.strip()[-500:]}")
    return text


def make_cwd(case: str, run: int) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"agent-sdk-evals-{case}-{run}-"))


def child_env(case: Case, config: Config) -> dict[str, str]:
    """The environment the run's subprocess inherits.

    `ClaudeAgentOptions.env` can only *override* an inherited variable, never
    remove one, so `trace.redact_env` names are scrubbed from this copy here — the
    only level at which removal is possible. It still cannot promise the child
    never sees a variable the parent shell exported into some other name; the
    `init` event's `api_key_source` is the honest read-back of what the child
    actually resolved.
    """
    env = dict(os.environ)
    for name in (config.trace.get("redact_env") or []):
        env.pop(str(name), None)
    env.update(case.env)
    env.setdefault("CLAUDE_AGENT_SDK_CLIENT_APP", "agent-sdk-evals")
    return env


async def drive(client: Any, capture: Capture, prompts: list[str]) -> None:
    """Scripted turns on one client: query, drain to the result, repeat."""
    for prompt in prompts:
        capture.user_turn(prompt)
        await client.query(prompt)
        async for message in client.receive_response():
            capture.add(message)


async def drive_simulated(client: Any, capture: Capture, user: Any) -> list[str]:
    """Persona-driven turns: ask the simulator, send it, drain, repeat."""
    pairs: list[tuple[str, str]] = []
    while True:
        text = await user.next_turn(pairs)
        if text is None:
            break
        capture.user_turn(text)
        pairs.append(("user", text))
        before = len(capture.assistant_texts)
        await client.query(text)
        async for message in client.receive_response():
            capture.add(message)
        replies = capture.assistant_texts[before:]
        pairs.append(("agent", "\n".join(replies) if replies else "(no reply)"))
    return user.turns


async def run_once(
    case: Case,
    config: Config,
    options: Any,
    *,
    run: int,
    run_id: str,
    sdk: Any,
    mock_calls: list[dict[str, Any]],
    persona: Any = None,
    keep_cwd: bool = False,
    permission_mode_source: str | None = None,
) -> RunOutcome:
    """One attempt at one case. Never raises for an agent-side failure.

    `permission_mode_source` is what `apply_overrides` already decided; it is
    passed in because the answer is no longer readable from the options once the
    mode has been filled in. Omitted (a direct caller), it is resolved here, so
    a session never starts with the mode unset whichever way it was reached.
    """
    if permission_mode_source is None:
        options, permission_mode_source = resolve_permission_mode(options)
    capture = Capture(run_id=run_id, case=case.name,
                      include_thinking=bool(config.trace.get("include_thinking")),
                      permission_mode_source=permission_mode_source)
    cwd = make_cwd(case.name, run)
    outcome = RunOutcome(run=run, case=case.name, capture=capture, cwd=cwd, cwd_kept=keep_cwd)
    env = child_env(case, config)
    # Every run gets its own working directory, and the session is pointed at it:
    # the scaffold seeds it, the agent writes into it, and `file_exists` graders
    # read it. Without this the agent would write into the project itself and one
    # run could see another's leftovers.
    options = dataclasses.replace(options, cwd=str(cwd))
    user = None
    prompts = case.turns or ([case.prompt] if case.prompt else [])
    if persona is not None:
        from .simulate import SimulatedUser

        user = SimulatedUser(persona, sdk, fallback_model=getattr(options, "model", None))

    async def _attempt() -> None:
        # `timeout_seconds` is wall clock for the whole run, scaffolding included:
        # a scaffold that hangs is just as dead as a session that hangs.
        if case.scaffold_script:
            output = await run_scaffold(case.scaffold_script, cwd, env)
            if output.strip():
                capture.note("scaffold_script output", output=output[-2000:])
        async with sdk.ClaudeSDKClient(options=options) as client:
            if user is not None:
                outcome.simulated_user_turns = await drive_simulated(client, capture, user)
            else:
                await drive(client, capture, prompts)

    try:
        await asyncio.wait_for(_attempt(), timeout=case.timeout_seconds)
    except asyncio.TimeoutError:
        outcome.error = f"the run exceeded timeout_seconds={case.timeout_seconds}"
        outcome.error_kind = "timeout"
        outcome.not_evaluated = False
        capture.note(outcome.error, kind="timeout")
    except BaseException as exc:  # noqa: BLE001 - every failure must be classified, never escape
        code, kind, message = classify_exception(exc)
        outcome.error, outcome.error_kind, outcome.exit_hint = message, kind, code
        capture.note(message, kind=kind)
        if kind == "usage_limit":
            limit = rate_limit_payload({"status": "rejected", "raw": {}}, kind="usage_limit",
                                       message=message[:400])
            capture.rate_limit = limit
            capture.rejected_rate_limit = limit
            capture.emit("rate_limit", **limit)
            outcome.not_evaluated = True
        elif code == 2:
            outcome.not_evaluated = True
    finally:
        if user is not None:
            outcome.extra_cost_usd += user.cost_usd
        outcome.mock_calls = list(mock_calls)
    # The working directory survives until the graders that read files have run;
    # `cleanup(outcome)` removes it afterwards unless `--keep-cwd` was given.
    return outcome


def cleanup(outcome: RunOutcome) -> None:
    """Remove the run's temporary directory unless `--keep-cwd` was given."""
    if outcome.cwd_kept or outcome.cwd is None:
        return
    shutil.rmtree(outcome.cwd, ignore_errors=True)
    outcome.cwd = None


def run_status(outcome: RunOutcome, grader_results: list[Any]) -> str:
    """A run passes when every gating grader passed and nothing was inconclusive.

    A `rejected` rate limit makes the run inconclusive whatever the graders said:
    the backend refused part of the work, so the evidence is not about the agent.
    An `allowed_warning` — which fired on every measured run — changes nothing.
    """
    if outcome.not_evaluated or getattr(outcome, "rejected", False):
        return NOT_EVALUATED
    gating = [g for g in grader_results if g.gating]
    if outcome.error and outcome.error_kind == "timeout":
        return FAILED
    if outcome.error and outcome.error_kind in ("result_error", "refusal", "tool_deferred") \
            and not gating:
        return FAILED
    if not gating:
        inconclusive = [g for g in grader_results if g.status == NOT_EVALUATED]
        return NOT_EVALUATED if inconclusive else PASSED
    return PASSED if all(g.status == PASSED for g in gating) else FAILED
