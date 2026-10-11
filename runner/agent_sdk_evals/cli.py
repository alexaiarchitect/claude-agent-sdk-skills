"""The command line: `run`, `list-tools`, `replay`, `version`, `whoami`.

Every subcommand prints exactly one JSON object as its **last** stdout line;
human-readable lines may come before it, which is how the plugin can show a
person something readable and still parse the outcome. The exit code is the real
gate: 0 all cases at or above threshold, 1 a case below, 2 usage/import/backend
error, 3 inconclusive.

The credential is never read by the runner. `whoami` reports what the CLI
subprocess *will* resolve, from `claude auth status`, and reports only
`kind`, `cost_basis`, `plan`, `auth_method` and `api_provider` — `email`,
`orgId` and `orgName` come back in that output and are never printed, logged or
written to a result file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import (
    CLIENT_APP,
    EXIT_INCONCLUSIVE,
    EXIT_OK,
    EXIT_USAGE,
    FAILED,
    ISOLATION_DEFAULTS,
    NOT_EVALUATED,
    PASSED,
    RUNNER_VERSION,
    SCHEMA_AGGREGATE,
    EvalError,
)
from .graders import Evidence, grade_free
from .judge import Judge, JudgeConfig
from .loader import (
    Case,
    Config,
    apply_overrides,
    discover_cases,
    import_entry,
    load_config,
    read_faults,
    read_persona,
    resolve_agent_entry,
    resolve_model,
    validate_overrides,
)
from .results import Aggregate, CaseResult, RunRecord, Writer, exit_code_for, result_projection, \
    rate_limit_projection, timestamp

MAX_CONCURRENCY = 8


def emit(payload: dict[str, Any]) -> None:
    """The one machine-readable line, always last."""
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def say(message: str) -> None:
    sys.stdout.write(message.rstrip() + "\n")


# -- the SDK ----------------------------------------------------------------

def import_sdk() -> Any:
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise EvalError(
            f"this interpreter ({sys.executable}) cannot import claude_agent_sdk: {exc}",
            code="ENV001",
            fix="python3 -m venv .venv && .venv/bin/pip install claude-agent-sdk",
        ) from exc
    return claude_agent_sdk


def sdk_version(sdk: Any) -> str:
    return str(getattr(sdk, "__version__", "unknown"))


def find_cli(sdk: Any | None = None) -> str | None:
    """The binary the SDK will use: its bundled copy first, then PATH."""
    if sdk is not None and getattr(sdk, "__file__", None):
        bundled = Path(sdk.__file__).resolve().parent / "_bundled" / "claude"
        for candidate in (bundled, bundled.with_suffix(".exe")):
            if candidate.is_file():
                return str(candidate)
    return shutil.which("claude")


def cli_version(sdk: Any | None = None) -> str:
    """The CLI version, without paying for a subprocess when the file says it.

    The bundled CLI wins over PATH, so this is not derivable from the SDK
    version: one machine measured SDK-bundled 2.1.285 next to a PATH 2.1.274.
    """
    if sdk is not None and getattr(sdk, "__file__", None):
        pinned = Path(sdk.__file__).resolve().parent / "_cli_version.py"
        if pinned.is_file():
            match = re.search(r"""['"](\d+\.\d+\.\d+)['"]""", pinned.read_text(encoding="utf-8"))
            if match:
                return match.group(1)
    binary = find_cli(sdk)
    if not binary:
        return "unknown"
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    match = re.search(r"(\d+\.\d+\.\d+)", out.stdout or "")
    return match.group(1) if match else "unknown"


# -- the credential ---------------------------------------------------------

#: The only keys of `claude auth status` that may leave this process. The rest of
#: that payload (`email`, `orgId`, `orgName`, `projectsDirectory`,
#: `configDirectory`) is personal or identifying and is dropped here, once, so no
#: later code has the chance to print it.
AUTH_SAFE_KEYS = ("loggedIn", "authMethod", "apiProvider", "subscriptionType")

PROVIDER_SWITCHES = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")


def auth_status(sdk: Any | None = None, *, timeout: float = 60.0) -> dict[str, Any]:
    """`claude auth status`, redacted to the four safe keys. Failure is "unknown"."""
    binary = find_cli(sdk)
    if not binary:
        return {}
    try:
        proc = subprocess.run([binary, "auth", "status"], capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}
    # Measured: the output is a pretty-printed JSON object spanning many lines,
    # with or without `--json`, and it carries `email`, `orgId` and `orgName`.
    # Everything but the four safe keys is dropped here and nowhere else.
    text = (proc.stdout or "").strip()
    candidates = [text] + [line.strip() for line in reversed(text.splitlines())]
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return {k: payload[k] for k in AUTH_SAFE_KEYS if k in payload}
    return {}


def credential(sdk: Any | None = None, *, probe: bool = True) -> dict[str, Any]:
    """What the CLI subprocess will use, and what that means for the cost figures."""
    provider = next((name for name in PROVIDER_SWITCHES if os.environ.get(name)), None)
    # With an API key set there is nothing the stored login can tell us — the key
    # wins in non-interactive mode — so the CLI is not asked, which also keeps
    # the check free and fast in CI.
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    status = auth_status(sdk) if (probe and not has_key) else {}
    if has_key:
        kind, basis = "api_key", "api_key"
    elif os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        kind, basis = "oauth_token", "subscription"
    elif provider:
        kind, basis = "provider", "provider"
    elif status.get("loggedIn"):
        kind, basis = "login", "subscription"
    elif status:
        kind, basis = "none", "unknown"
    else:
        kind, basis = "unknown", "unknown"
    if provider and kind in ("api_key", "oauth_token", "login"):
        basis = "provider"
    return {
        "kind": kind,
        "cost_basis": basis,
        "plan": status.get("subscriptionType"),
        "auth_method": status.get("authMethod"),
        "api_provider": status.get("apiProvider") or (provider.lower() if provider else None),
        "provider_switch": provider,
    }


# -- planning ---------------------------------------------------------------

@dataclass
class Plan:
    """A validated, costed-out intention. Built before anything is spent."""

    config: Config
    tier: Any
    cases: list[Case]
    options: dict[str, Any]
    models: dict[str, str]
    isolation: dict[str, dict[str, Any]]
    runs: dict[str, int]
    warnings: list[str]
    entries: dict[str, str]
    #: case -> ("agent" | "runner-default"), who decided `permission_mode`.
    permission_modes: dict[str, str] = field(default_factory=dict)


def build_plan(args: argparse.Namespace, sdk: Any) -> Plan:
    evals_dir = Path(args.evals_dir)
    config = load_config(evals_dir)
    if config.runner_version and config.runner_version != RUNNER_VERSION:
        if _newer(config.runner_version, RUNNER_VERSION):
            raise EvalError(
                f"eval_config.json asks for runner {config.runner_version}, this copy is "
                f"{RUNNER_VERSION}",
                code="CFG050",
                fix="upgrade the runner copy in evals/runner/ from the plugin",
            )
    tier = config.tier(args.tier)
    cases = discover_cases(evals_dir, case_glob=args.case, tag=args.tag)
    if not cases:
        raise EvalError(
            f"no cases matched in {evals_dir}"
            + (f" (--case {args.case})" if args.case else "")
            + (f" (--tag {args.tag})" if args.tag else ""),
            code="EVC001",
        )
    live_fields = getattr(sdk.ClaudeAgentOptions, "__dataclass_fields__", None)
    warnings: list[str] = []
    options: dict[str, Any] = {}
    models: dict[str, str] = {}
    isolation: dict[str, dict[str, Any]] = {}
    runs: dict[str, int] = {}
    entries: dict[str, str] = {}
    permission_modes: dict[str, str] = {}
    errors: list[str] = []
    for case in cases:
        check = validate_overrides(case.overrides, live_fields)
        errors.extend(f"{case.name}: {message}" for message in check.errors)
        warnings.extend(f"{case.name}: {message}" for message in check.warnings)
        warnings.extend(f"{case.name}: {note}" for note in case.notes)
    if errors:
        # Refused before a single session starts: an `overrides` typo costs nothing.
        raise EvalError("; ".join(errors), code="EVC003",
                        fix="fix the case's `overrides` block, then re-run")
    for case in cases:
        entry = resolve_agent_entry(case, config)
        entries[case.name] = entry
        builder = import_entry(entry, Path.cwd())
        try:
            base = builder()
        except BaseException as exc:  # the agent's own code
            raise EvalError(
                f"{case.name}: {entry} raised {type(exc).__name__}: {exc}",
                code="AGT001",
            ) from exc
        model = resolve_model(case, config, getattr(base, "model", None))
        overrides = dict(case.overrides)
        overrides["model"] = model
        if case.max_turns is not None:
            overrides.setdefault("max_turns", case.max_turns)
        built, applied, mode_source = apply_overrides(base, overrides, config.isolation)
        permission_modes[case.name] = mode_source
        for name, value in ISOLATION_DEFAULTS.items():
            if name in case.overrides and case.overrides[name] != value:
                warnings.append(
                    f"{case.name}: `overrides.{name}` opts out of the runner's isolation default "
                    f"({value!r}); results stop being portable between machines"
                )
        options[case.name] = built
        models[case.name] = model
        isolation[case.name] = applied
        runs[case.name] = int(args.runs or case.runs or tier.runs or 1)
    return Plan(config=config, tier=tier, cases=cases, options=options, models=models,
                isolation=isolation, runs=runs, warnings=warnings, entries=entries,
                permission_modes=permission_modes)


def _newer(left: str, right: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        return tuple(int(p) for p in re.findall(r"\d+", value)[:3])
    try:
        return parts(left) > parts(right)
    except ValueError:
        return False


# -- grading ----------------------------------------------------------------

async def grade_run(case: Case, outcome: Any, tier: Any, judge: Judge | None) -> list[Any]:
    from .graders.llm import grade_llm

    capture = outcome.capture
    evidence = Evidence(
        last_message=capture.last_message,
        assistant_texts=capture.assistant_texts,
        events=capture.events,
        result=capture.result,
        run_cwd=outcome.cwd,
        case_dir=case.dir,
        mock_calls=outcome.mock_calls,
        hook_events_installed=set(capture.hook_events_installed),
        case_cost_usd=capture.total_cost_usd,
        simulated_user_turns=outcome.simulated_user_turns,
    )
    results: list[Any] = []
    for grader in case.graders_for(list(tier.graders)):
        if grader.tier == "judge":
            results.append(await grade_llm(grader, evidence, judge))
        else:
            results.append(grade_free(grader, evidence))
    return results


# -- run --------------------------------------------------------------------

async def execute_run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from .session import cleanup, run_once, run_status

    sdk = import_sdk()
    os.environ.setdefault("CLAUDE_AGENT_SDK_CLIENT_APP", CLIENT_APP)
    plan = build_plan(args, sdk)
    config, tier = plan.config, plan.tier
    creds = credential(sdk)
    versions = {"sdk_version": sdk_version(sdk), "cli_version": cli_version(sdk)}

    if args.dry_run:
        return dry_run_payload(args, plan, creds, versions), EXIT_OK

    judge = Judge(JudgeConfig.from_dict(config.judge), sdk) if "judge" in tier.graders else None
    out_dir = Path(args.out) if args.out else Path(config.results_dir) / timestamp()
    writer = Writer(out_dir)
    aggregate = Aggregate(tier=tier.name, credential=creds, **versions)
    aggregate.warnings = list(plan.warnings)
    for warning in plan.warnings:
        say(f"warn: {warning}")

    ceiling_total = args.max_cost_usd if args.max_cost_usd is not None \
        else config.budget.get("max_cost_usd_total")
    concurrency = max(1, min(int(args.concurrency or config.concurrency or 1), MAX_CONCURRENCY))
    semaphore = asyncio.Semaphore(concurrency)
    started = time.monotonic()
    state = {"rejected": None, "stop": False, "ceiling": False, "spent": 0.0,
             "backend_error": None}

    async def one_run(case: Case, run_index: int) -> Any:
        async with semaphore:
            if state["stop"]:
                return None
            persona = None
            if case.simulated_user:
                from .simulate import Persona

                persona = Persona.from_dict(read_persona(case, config.evals_dir))
            mock_calls: list[dict[str, Any]] = []
            options = plan.options[case.name]
            if case.mocks:
                from .mocks import MockRecorder, build_servers

                recorder = MockRecorder()
                servers = dict(getattr(options, "mcp_servers", None) or {})
                servers.update(build_servers(config.evals_dir, case.mocks, recorder, sdk))
                import dataclasses as _dc

                options = _dc.replace(options, mcp_servers=servers)
                mock_calls = recorder.calls
            fault_plan = None
            if case.faults:
                from .faults import load_plan

                fault_plan = load_plan(read_faults(case, config.evals_dir), run=run_index)
            from .faults import build_hooks

            probe = _HookTarget()
            hooks = build_hooks(probe, fault_plan, sdk)
            import dataclasses as _dc2

            options = _dc2.replace(options, hooks=hooks, include_hook_events=True)
            outcome = await run_once(
                case, config, options,
                run=run_index, run_id=f"{case.name}.{run_index}", sdk=sdk,
                mock_calls=mock_calls, persona=persona, keep_cwd=bool(args.keep_cwd),
                permission_mode_source=plan.permission_modes.get(case.name),
            )
            outcome.capture.hook_events_installed |= probe.installed
            probe.drain_into(outcome.capture)
            outcome.capture.set_cost_basis(creds["cost_basis"])
            return outcome

    for case in plan.cases:
        if state["stop"]:
            break
        case_result = CaseResult(
            case=case.name, category=case.category,
            config={
                "tier": tier.name,
                "model": plan.models[case.name],
                "agent": plan.entries[case.name],
                "judge": {"model": config.judge.get("model"), "samples": config.judge.get("samples")},
                "isolation": plan.isolation[case.name],
                "cost_basis": creds["cost_basis"],
                "sdk_version": versions["sdk_version"],
                "cli_version": versions["cli_version"],
                "runner_version": RUNNER_VERSION,
            },
            notes=list(case.notes),
        )
        total_runs = plan.runs[case.name]
        outcomes = await asyncio.gather(*[one_run(case, i + 1) for i in range(total_runs)])
        for outcome in outcomes:
            if outcome is None:
                case_result.runs.append(RunRecord(
                    run=len(case_result.runs) + 1, trace="", status=NOT_EVALUATED,
                    error="not launched: a rejected rate limit stopped the suite",
                ))
                continue
            grader_results = await grade_run(case, outcome, tier, judge)
            status = run_status(outcome, grader_results)
            trace_name = writer.write_trace(case.name, outcome.run, outcome.capture.to_jsonl())
            record = RunRecord(
                run=outcome.run, trace=trace_name, status=status,
                graders=[g.to_dict() for g in grader_results],
                result=result_projection(outcome.capture.result),
                rate_limit=rate_limit_projection(outcome.rate_limit),
                error=outcome.error,
                mock_calls=len(outcome.mock_calls),
                cwd=str(outcome.cwd) if outcome.cwd_kept and outcome.cwd else None,
                simulated_user_turns=outcome.simulated_user_turns,
            )
            case_result.runs.append(record)
            if outcome.rate_limit:
                aggregate.rate_limit = outcome.rate_limit
                if outcome.rate_limit.get("status") == "allowed_warning":
                    say(f"warn: rate limit {outcome.rate_limit.get('rate_limit_type')} at "
                        f"{outcome.rate_limit.get('utilization')} utilization — still running")
            if outcome.rejected:
                state["rejected"] = outcome.rate_limit
                state["stop"] = True
            if outcome.exit_hint == EXIT_USAGE:
                # A backend failure (no CLI, a connection refused, an unparseable
                # line) is an environment problem, not a verdict about the agent.
                state["backend_error"] = outcome.error
                state["stop"] = True
            cleanup(outcome)
        aggregate.cases.append(case_result)
        state["spent"] = round(state["spent"] + case_result.cost_usd, 6)
        if ceiling_total is not None and state["spent"] > float(ceiling_total):
            state["ceiling"] = True
            state["stop"] = True
            say(f"stopping: est. spend {state['spent']} exceeds the ceiling {ceiling_total}")

    if state["rejected"] and args.wait_for_reset:
        aggregate.warnings.append(
            "a rejected rate limit stopped the suite; --wait-for-reset slept once and retried"
        )
        retried = await _retry_after_reset(state, plan, aggregate, writer, tier, judge, one_run,
                                           creds, args)
        if retried:
            state["rejected"] = None
            state["stop"] = False

    aggregate.duration_ms = int((time.monotonic() - started) * 1000)
    if state["rejected"]:
        aggregate.stopped = {
            "reason": "rate_limit_rejected",
            "resets_at": state["rejected"].get("resets_at"),
            "status": state["rejected"].get("status"),
        }
    elif state["ceiling"]:
        aggregate.stopped = {"reason": "cost_ceiling", "spent_usd": state["spent"],
                             "ceiling_usd": ceiling_total}
    elif state["backend_error"]:
        aggregate.stopped = {"reason": "backend_error", "error": state["backend_error"]}
    if state["backend_error"]:
        aggregate.exit_code = EXIT_USAGE
        aggregate.warnings.append(f"backend error: {state['backend_error']}")
    else:
        aggregate.exit_code = exit_code_for(
            aggregate, tier.threshold,
            rejected=bool(state["rejected"]), cost_ceiling_hit=bool(state["ceiling"]),
        )
    for case_result in aggregate.cases:
        writer.write_case(case_result)
    writer.write_aggregate(aggregate, pass_k=tier.pass_k)
    payload = aggregate.to_dict(pass_k=tier.pass_k)
    payload["results_dir"] = str(out_dir)
    if not args.json:
        say(render_run(payload))
    return payload, aggregate.exit_code


async def _retry_after_reset(state: dict[str, Any], plan: Plan, aggregate: Aggregate,
                             writer: Writer, tier: Any, judge: Any, one_run: Any,
                             creds: dict[str, Any], args: argparse.Namespace) -> bool:
    """Sleep until the reported reset once, then retry the cases never launched."""
    from .session import cleanup, run_status

    resets_at = (state["rejected"] or {}).get("resets_at")
    if not resets_at:
        return False
    wait = max(0.0, float(resets_at) - time.time()) + 5.0
    say(f"waiting {wait:.0f}s for the rate-limit window to reset, then retrying pending runs")
    await asyncio.sleep(wait)
    state["stop"] = False
    state["rejected"] = None
    done = {case_result.case for case_result in aggregate.cases
            if all(r.status != NOT_EVALUATED or r.trace for r in case_result.runs)}
    pending = [case for case in plan.cases if case.name not in done]
    if not pending:
        return True
    for case in pending:
        outcomes = await asyncio.gather(*[one_run(case, i + 1) for i in range(plan.runs[case.name])])
        existing = next((c for c in aggregate.cases if c.case == case.name), None)
        if existing is None:
            continue
        existing.runs = []
        for outcome in outcomes:
            if outcome is None:
                continue
            grader_results = await grade_run(case, outcome, tier, judge)
            trace_name = writer.write_trace(case.name, outcome.run, outcome.capture.to_jsonl())
            existing.runs.append(RunRecord(
                run=outcome.run, trace=trace_name, status=run_status(outcome, grader_results),
                graders=[g.to_dict() for g in grader_results],
                result=result_projection(outcome.capture.result),
                rate_limit=rate_limit_projection(outcome.rate_limit),
                error=outcome.error,
            ))
            if outcome.rejected:
                state["rejected"] = outcome.rate_limit
                state["stop"] = True
            cleanup(outcome)
    return not state["rejected"]


class _HookTarget:
    """Collects hook events before the run's `Capture` exists, then hands them over."""

    def __init__(self) -> None:
        self.installed: set[str] = set()
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def hook_events_installed(self) -> set[str]:
        return self.installed

    def hook(self, event: str, phase: str, **fields: Any) -> None:
        self.records.append((event, phase, fields))

    def drain_into(self, capture: Any) -> None:
        for event, phase, fields in self.records:
            capture.hook(event, phase, **fields)
        self.records.clear()


def dry_run_payload(args: argparse.Namespace, plan: Plan, creds: dict[str, Any],
                    versions: dict[str, str]) -> dict[str, Any]:
    command = ["python", "-m", "agent_sdk_evals", "run", str(args.evals_dir), "--tier", args.tier]
    for flag, value in (("--case", args.case), ("--tag", args.tag), ("--runs", args.runs),
                        ("--concurrency", args.concurrency), ("--out", args.out),
                        ("--max-cost-usd", args.max_cost_usd)):
        if value:
            command += [flag, str(value)]
    payload = {
        "schema": SCHEMA_AGGREGATE,
        "dry_run": True,
        "command": " ".join(command),
        "tier": plan.tier.name,
        "threshold": plan.tier.threshold,
        "graders": list(plan.tier.graders),
        "credential": creds,
        "runner_version": RUNNER_VERSION,
        **versions,
        "cases": [
            {
                "case": case.name,
                "category": case.category,
                "tags": case.tags,
                "runs": plan.runs[case.name],
                "model": plan.models[case.name],
                "agent": plan.entries[case.name],
                "isolation": plan.isolation[case.name],
                "permission_mode": getattr(plan.options[case.name], "permission_mode", None),
                "permission_mode_source": plan.permission_modes.get(case.name),
                "graders": [
                    {"name": g.name, "type": g.type, "tier": g.tier}
                    for g in case.graders_for(list(plan.tier.graders))
                ],
                "mocks": case.mocks,
                "simulated_user": case.simulated_user,
                "timeout_seconds": case.timeout_seconds,
            }
            for case in plan.cases
        ],
        "warnings": plan.warnings,
        "exit_code": EXIT_OK,
        "started_nothing": True,
    }
    say(f"dry run — nothing was started.\n  command:    {payload['command']}")
    say(f"  credential: {creds['kind']} (cost basis {creds['cost_basis']}"
        + (f", plan {creds['plan']}" if creds.get("plan") else "") + ")")
    say(f"  versions:   runner {RUNNER_VERSION}, sdk {versions['sdk_version']}, "
        f"cli {versions['cli_version']}")
    for case in payload["cases"]:
        say(f"  case {case['case']}: model {case['model']}, {case['runs']} run(s), "
            f"permission_mode {case['permission_mode']} ({case['permission_mode_source']}), "
            f"isolation {json.dumps(case['isolation'])}, graders "
            + (", ".join(f"{g['name']}({g['type']})" for g in case["graders"]) or "none"))
    return payload


def render_run(payload: dict[str, Any]) -> str:
    totals = payload["totals"]
    lines = [
        f"{payload['tier']}: {totals['passed']} passed, {totals['failed']} failed, "
        f"{totals['not_evaluated']} not evaluated across {totals['runs']} run(s) of "
        f"{totals['cases']} case(s)",
        f"est. {totals['cost_usd']} USD on a {totals['cost_basis']} cost basis; results in "
        f"{payload.get('results_dir')}",
    ]
    for case in payload["cases"]:
        lines.append(f"  {case['case']}: pass_rate {case['pass_rate']}, cost {case['cost']}")
    return "\n".join(lines)


# -- replay -----------------------------------------------------------------

def load_trace(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(f"{path}: line {len(events) + 1} is not JSON: {exc}", code="RES010") from exc
        if isinstance(event, dict):
            events.append(event)
    if not events:
        raise EvalError(f"{path}: no events", code="RES010")
    return events


def evidence_from_trace(events: list[dict[str, Any]], case_dir: Path | None) -> Evidence:
    texts = [e.get("text", "") for e in events if e.get("type") == "assistant_text"]
    results = [e for e in events if e.get("type") == "result"]
    installed = {str(e.get("event")) for e in events if e.get("type") == "hook" and e.get("event")}
    return Evidence(
        last_message=texts[-1] if texts else "",
        assistant_texts=texts,
        events=events,
        result=results[-1] if results else None,
        run_cwd=None,
        case_dir=case_dir,
        hook_events_installed=installed,
        case_cost_usd=float((results[-1].get("total_cost_usd") or 0.0) if results else 0.0),
    )


def execute_replay(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from .loader import load_graders

    events = load_trace(Path(args.trace))
    case_name = next((e.get("case") for e in events if e.get("case")), Path(args.trace).stem)
    case_dir = Path(args.case_dir) if args.case_dir else None
    graders = load_graders(case_dir) if case_dir else []
    if not graders:
        raise EvalError(
            "replay needs the case's graders: pass --case-dir <evals/case>",
            code="EVC010",
        )
    evidence = evidence_from_trace(events, case_dir)
    results = [grade_free(g, evidence) for g in graders if g.tier == "free"]
    skipped = [g.name for g in graders if g.tier != "free"]
    status = PASSED if all(r.status == PASSED for r in results if r.gating) else FAILED
    if not [r for r in results if r.gating]:
        status = NOT_EVALUATED
    payload = {
        "schema": "agent-sdk-skills.result/1",
        "case": case_name,
        "replay": str(args.trace),
        "graders_only": True,
        "runs": [{
            "run": 1, "trace": str(args.trace), "status": status,
            "graders": [r.to_dict() for r in results],
            "result": result_projection(evidence.result),
        }],
        "summary": {
            "passed": sum(1 for r in results if r.status == PASSED),
            "failed": sum(1 for r in results if r.status == FAILED),
            "not_evaluated": sum(1 for r in results if r.status == NOT_EVALUATED),
            "informational": sum(1 for r in results if r.status == "INFORMATIONAL"),
            "pass_rate": 1.0 if status == PASSED else 0.0,
            "cost_usd": 0.0,
        },
        "skipped_judge_graders": skipped,
        "exit_code": 0 if status == PASSED else (1 if status == FAILED else 3),
    }
    if not args.json:
        say(f"replayed {args.trace}: {status}")
        for record in results:
            say(f"  {record.name} ({record.type}): {record.status} — {record.reason}")
    return payload, int(payload["exit_code"])


# -- list-tools -------------------------------------------------------------

def execute_list_tools(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    sdk = import_sdk()
    entry = args.agent or os.environ.get("AGENT_ENTRY") or "agent:build_options"
    evals_dir = Path(args.evals_dir) if args.evals_dir else None
    if evals_dir and (evals_dir / "eval_config.json").is_file():
        entry = args.agent or load_config(evals_dir).agent
    options = import_entry(entry, Path.cwd())()
    servers = dict(getattr(options, "mcp_servers", None) or {})
    tools = list(getattr(options, "allowed_tools", None) or [])
    payload = {
        "source": "options",
        "agent": entry,
        "tools": sorted(tools),
        "disallowed_tools": sorted(getattr(options, "disallowed_tools", None) or []),
        "builtin_tools": getattr(options, "tools", None),
        "mcp_servers": sorted(servers),
        "sdk_version": sdk_version(sdk),
    }
    if args.probe:
        payload.update(_probe_tools(sdk, options))
        payload["source"] = "probe"
    if not args.json:
        say(f"{entry}: {len(payload['tools'])} allowed tool(s), "
            f"{len(payload['mcp_servers'])} MCP server(s)")
    return payload, EXIT_OK


def _probe_tools(sdk: Any, options: Any) -> dict[str, Any]:
    """Connect once and read what the CLI says it has. Starts a session."""
    async def _go() -> dict[str, Any]:
        from .capture import Capture

        capture = Capture(run_id="list-tools", case="list-tools")
        async with sdk.ClaudeSDKClient(options=options) as client:
            status = await client.get_mcp_status()
            await client.query("Reply with the single word: ready")
            async for message in client.receive_response():
                capture.add(message)
        init = next((e for e in capture.events if e["type"] == "init"), {})
        return {
            "tools": sorted(init.get("tools") or []),
            "mcp_servers": init.get("mcp_servers") or [],
            "mcp_status": str(status),
            "cost_usd": (capture.result or {}).get("total_cost_usd"),
        }

    return asyncio.run(_go())


# -- whoami / version ------------------------------------------------------

def execute_whoami(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    sdk: Any | None
    try:
        sdk = import_sdk()
    except EvalError:
        sdk = None
    creds = credential(sdk)
    payload = {
        "credential": creds,
        "sdk_version": sdk_version(sdk) if sdk else "unknown",
        "cli_version": cli_version(sdk),
        "cli_path": find_cli(sdk),
        "runner_version": RUNNER_VERSION,
        "python": sys.executable,
    }
    if not args.json:
        say(f"credential: {creds['kind']} (cost basis {creds['cost_basis']}"
            + (f", plan {creds['plan']}" if creds.get("plan") else "")
            + (f", auth {creds['auth_method']}" if creds.get("auth_method") else "") + ")")
        say("no account identity is read or reported: email, organisation id and organisation "
            "name are dropped before anything is printed")
    return payload, EXIT_OK


def execute_version(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        sdk: Any | None = import_sdk()
    except EvalError:
        sdk = None
    payload = {
        "runner_version": RUNNER_VERSION,
        "sdk_version": sdk_version(sdk) if sdk else "unknown",
        "cli_version": cli_version(sdk),
        "python": sys.version.split()[0],
    }
    if not args.json:
        say(f"runner {payload['runner_version']}, claude-agent-sdk {payload['sdk_version']}, "
            f"CLI {payload['cli_version']}")
    return payload, EXIT_OK


# -- argument parsing -------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent_sdk_evals",
        description="Run and grade Claude Agent SDK evaluations. The last stdout line of every "
                    "subcommand is one JSON object.",
    )
    parser.add_argument("--json", action="store_true",
                        help="print only the JSON line, no human-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the cases in an evals directory")
    run.add_argument("evals_dir")
    run.add_argument("--case", help="glob over case directory names")
    run.add_argument("--tag", help="only cases carrying this tag")
    run.add_argument("--runs", type=int, help="override the tier's run count")
    run.add_argument("--tier", default="pr",
                     choices=("pr", "nightly", "free", "run", "judge"))
    run.add_argument("--dry-run", action="store_true",
                     help="print the resolved command, credential, model, isolation and case "
                          "list, then exit 0 without starting anything")
    run.add_argument("--max-cost-usd", type=float, help="stop once the estimate passes this")
    run.add_argument("--concurrency", type=int, default=None,
                     help=f"parallel runs, 1..{MAX_CONCURRENCY} (default from the config, else 1)")
    run.add_argument("--wait-for-reset", action="store_true",
                     help="on a rejected rate limit, sleep until the reset once and retry")
    run.add_argument("--keep-cwd", action="store_true", help="keep each run's temporary directory")
    run.add_argument("--out", help="write results here instead of results_dir/<timestamp>")
    run.add_argument("--json", action="store_true", help="print only the JSON line")

    tools = sub.add_parser("list-tools", help="what tools the agent's options expose")
    tools.add_argument("evals_dir", nargs="?")
    tools.add_argument("--agent", help="module:function overriding the config's agent")
    tools.add_argument("--probe", action="store_true",
                       help="connect once and ask the CLI (starts a session; costs a little)")
    tools.add_argument("--json", action="store_true", help="print only the JSON line")

    replay = sub.add_parser("replay", help="re-grade a stored trace without calling the model")
    replay.add_argument("trace")
    replay.add_argument("--case-dir", help="the case directory whose graders to apply")
    replay.add_argument("--graders-only", action="store_true",
                        help="the only supported mode: free graders over the stored trace")
    replay.add_argument("--json", action="store_true", help="print only the JSON line")

    version = sub.add_parser("version", help="runner, SDK and CLI versions")
    version.add_argument("--json", action="store_true", help="print only the JSON line")

    whoami = sub.add_parser("whoami", help="the credential the runs will use")
    whoami.add_argument("--json", action="store_true", help="print only the JSON line")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            payload, code = asyncio.run(execute_run(args))
        elif args.command == "replay":
            payload, code = execute_replay(args)
        elif args.command == "list-tools":
            payload, code = execute_list_tools(args)
        elif args.command == "whoami":
            payload, code = execute_whoami(args)
        elif args.command == "version":
            payload, code = execute_version(args)
        else:  # pragma: no cover - argparse rejects anything else
            parser.error(f"unknown command {args.command}")
            return EXIT_USAGE
    except EvalError as exc:
        payload = {"schema": SCHEMA_AGGREGATE, "exit_code": EXIT_USAGE, **exc.to_dict()}
        sys.stderr.write(f"error: {exc}\n")
        if exc.fix:
            sys.stderr.write(f"fix: {exc.fix}\n")
        emit(payload)
        return EXIT_USAGE
    except KeyboardInterrupt:
        emit({"schema": SCHEMA_AGGREGATE, "exit_code": EXIT_INCONCLUSIVE,
              "error": "interrupted", "stopped": {"reason": "interrupted"}})
        return EXIT_INCONCLUSIVE
    payload.setdefault("exit_code", code)
    emit(payload)
    return code
