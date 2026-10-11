#!/usr/bin/env python3
"""Check every mock, persona and faults file against what the runner loads.

All three are read by the runner with no schema and almost no complaint: an
unknown persona key is silently ignored, a mock with no `schema` advertises a
tool that accepts nothing, and a faults file that injects nothing still runs and
still passes. Each of those produces a green suite that measured nothing, which
is worse than a red one. So this compares the files on disk against the loaders
in `agent_sdk_evals/{mocks,faults,simulate}.py` and says which ones the runner
would quietly ignore.

    validate_sim.py <project> [--json] [--strict]

What it reports:

`SIM001`  a persona with no `violation_rubrics` (error); a rubric written about
          the agent instead of the simulated user (warn)
`SIM002`  a fault `probability` outside [0, 1], an unknown `action`, or a file
          the loader would refuse (error)
`SIM003`  `constraints` that is not a list of strings — a bare string is
          iterated character by character (error)
`SIM004`  a persona key the runner does not read (warn), with the key it
          probably meant
`SIM005`  `max_user_turns` below 1 (error)
`SIM006`  a persona `model` that is retired (error) or retiring (warn)
`SIM010`-`SIM013`  the mock checks: no `schema`, `error` with a body, a bad
          `latency_ms`, an unknown `type`
`MCP020`  a mock for a server the agent no longer mounts (warn)
`SIM020`  a fault naming a tool nothing in the project provides (warn)
`SIM021`  a fault that neither replaces a result nor delays one (error)
`SIM030`  a case whose `mocks:` names a server with no directory (error)
`SIM031`  a case whose `simulated_user:` path does not exist (error)
`SIM032`  a case whose `faults:` path does not exist (error)
`EVC040`  a simulated-user case carrying a `trajectory` or `no_tool` grader
          (info here; `/agent-sdk:eval-review` is where that is decided)

Exit codes: 0 clean, 1 findings (errors, or any finding under `--strict`),
2 usage — no such project, or no `evals/` directory to validate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import PYTHON_HOOK_EVENTS  # noqa: E402
from agent_sdk_skills.env import classify_model_id, model_retirement_date  # noqa: E402
from agent_sdk_skills.evalcase import iter_cases  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.mocks import mock_tool_names, mock_summary, validate_mocks  # noqa: E402
from agent_sdk_skills.options_ast import extract_project  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport, Option  # noqa: E402

_SRC_PERSONA = "runner/agent_sdk_evals/simulate.py Persona.from_dict"
_SRC_FAULTS = "runner/agent_sdk_evals/faults.py load_plan"
_SRC_CASE = "this plugin's case format (CONTRACTS §1)"

#: Exactly the keys `Persona.from_dict` reads. Everything else is dropped.
PERSONA_KEYS = (
    "name", "goal", "style", "model", "opening", "max_user_turns",
    "stop_marker", "constraints", "violation_rubrics",
)

#: Keys people write instead, and what the runner actually reads.
PERSONA_ALIASES = {
    "max_turns": "max_user_turns",
    "user_turns": "max_user_turns",
    "stop_when": "stop_marker",
    "stop": "stop_marker",
    "behaviours": "constraints",
    "behaviors": "constraints",
    "rules": "constraints",
    "instructions": "constraints",
    "violations": "violation_rubrics",
    "rubrics": "violation_rubrics",
    "first_turn": "opening",
}

#: Keys that carry no behaviour at all — documentation the runner ignores.
PERSONA_DOC_KEYS = ("schema", "description", "notes", "tags", "follow_ups")

#: `faults.ACTIONS`.
FAULT_ACTIONS = ("deny", "updated_input", "error_output", "latency", "allow")

BUILTIN_TOOLS = (
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch",
    "NotebookEdit", "TodoWrite", "Task", "Agent", "Skill", "StructuredOutput",
    "ToolSearch",
)

#: Graders whose meaning depends on a tool sequence nobody scripted.
UNFIXED_TRAJECTORY_GRADERS = ("trajectory", "no_tool")

#: Anything here means `tool` is a regex, not a name to look up.
REGEX_CHARS = ".*+?[]()|^$\\{}"

#: A rubric that starts like this is judging the agent, not the simulated user.
AGENT_SHAPED = ("the agent ", "agent ", "the assistant ", "assistant ", "it ")


# -- personas ---------------------------------------------------------------

def check_persona(path: Path, report: GapReport) -> dict[str, Any] | None:
    where = str(path)

    def add(fid: str, severity: str, message: str, *, fix: str = "",
            locator: str | None = None, source: str = _SRC_PERSONA) -> None:
        report.add(fid, severity, "persona", f"persona {path.stem}: {message}",
                   path=where, locator=locator, fix=fix or None, source=source)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        add("SIM001", "error", f"unreadable: {exc}",
            fix="a persona is a JSON object; the runner loads it before the case starts")
        return None
    if not isinstance(data, dict):
        add("SIM001", "error", f"must be a JSON object, got {type(data).__name__}")
        return None

    rubrics = data.get("violation_rubrics")
    if not rubrics:
        add("SIM001", "error", "no `violation_rubrics`",
            fix="the rubrics are the only check on the simulator itself. Without them "
                "nothing notices a user that drifted off character and handed the agent "
                "the answer, and the case passes for a reason unrelated to the agent. "
                "Add two or three statements the USER's turns must satisfy.",
            locator="violation_rubrics")
    elif not isinstance(rubrics, list):
        add("SIM001", "error", f"`violation_rubrics` must be a list, got {type(rubrics).__name__}",
            locator="violation_rubrics")
    else:
        for rubric in rubrics:
            text = str(rubric).strip().lower()
            if text.startswith(AGENT_SHAPED):
                add("SIM001", "warn",
                    f"violation rubric judges the agent, not the user: {str(rubric)[:70]!r}",
                    fix="violation rubrics are run against the simulated user's turns and a "
                        "violation makes the case NOT_EVALUATED, not FAILED. An assertion "
                        "about the agent belongs in the case's own graders.",
                    locator="violation_rubrics")

    constraints = data.get("constraints")
    if constraints is not None:
        if isinstance(constraints, str):
            add("SIM003", "error", "`constraints` is a string, not a list",
                fix="the runner does `[str(c) for c in constraints]`, so a bare string "
                    "becomes one constraint per character. Wrap it in a list.",
                locator="constraints")
        elif not isinstance(constraints, list):
            add("SIM003", "error",
                f"`constraints` must be a list of strings, got {type(constraints).__name__}",
                locator="constraints")
        else:
            bad = [c for c in constraints if not isinstance(c, str)]
            if bad:
                add("SIM003", "warn",
                    f"{len(bad)} constraint(s) are not strings and will be stringified",
                    fix="each constraint is rendered as a bullet under \"Rules you follow no "
                        "matter what\", so write an imperative sentence",
                    locator="constraints")

    turns = data.get("max_user_turns")
    if turns is not None:
        if isinstance(turns, bool) or not isinstance(turns, int):
            add("SIM005", "error", f"`max_user_turns` must be an integer, got {turns!r}",
                locator="max_user_turns")
        elif turns < 1:
            add("SIM005", "error", f"`max_user_turns` is {turns}",
                fix="0 is falsy and silently becomes the default of 4; a negative value "
                    "stops the conversation before the first turn. Use 1 or more.",
                locator="max_user_turns")

    model = data.get("model")
    if model:
        grade = classify_model_id(str(model))
        if grade == "retired":
            add("SIM006", "error", f"persona model {model!r} is retired and no longer served",
                fix="the simulated user runs on its own model; point it at a current one, "
                    "or drop `model` and inherit the judge tier's",
                locator="model", source="this plugin's model policy")
        elif grade in ("deprecated", "retiring", "unknown"):
            # A deprecated id has a committed date, which is the whole reason it
            # is graded apart from `retiring`: the message can say when the
            # persona stops working instead of "some time".
            retires = model_retirement_date(str(model))
            when = f", retires {retires}" if retires else ""
            add("SIM006", "warn", f"persona model {model!r} is {grade}{when}",
                fix="pin a current id, or drop `model` so the persona follows the judge "
                    "model in eval_config.json",
                locator="model", source="this plugin's model policy")

    for key in data:
        if key in PERSONA_KEYS:
            continue
        alias = PERSONA_ALIASES.get(key)
        if alias:
            fix = (f"the runner reads `{alias}`, not `{key}`; this key is dropped on load, "
                   "so whatever it said has no effect on the run")
        elif key in PERSONA_DOC_KEYS:
            fix = ("documentation only: the runner drops it. Harmless, but a reader will "
                   "assume it does something — say it in `style` or `constraints` instead")
            if key == "follow_ups":
                fix = ("a persona generates its turns; it does not replay a script. For a "
                       "fixed conversation use a case with `turns:` and no `simulated_user:`")
        else:
            fix = (f"`{key}` is not one of {', '.join(PERSONA_KEYS)}; the runner drops it "
                   "without a word")
        report.add("SIM004", "warn", "persona",
                   f"persona {path.stem}: `{key}` is not read by the runner",
                   path=where, locator=key, fix=fix, source=_SRC_PERSONA)

    return {
        "path": where, "name": data.get("name") or path.stem,
        "max_user_turns": data.get("max_user_turns", 4),
        "constraints": len(data.get("constraints") or []),
        "violation_rubrics": len(rubrics or []) if isinstance(rubrics, list) else 0,
        "model": data.get("model"),
        "opening": bool(data.get("opening")),
    }


# -- faults -----------------------------------------------------------------

def check_faults(path: Path, report: GapReport, known_tools: set[str]) -> dict[str, Any] | None:
    where = str(path)

    def add(fid: str, severity: str, message: str, *, fix: str = "",
            locator: str | None = None, source: str = _SRC_FAULTS) -> None:
        report.add(fid, severity, "faults", f"faults {path.stem}: {message}",
                   path=where, locator=locator, fix=fix or None, source=source)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        add("SIM002", "error", f"unreadable: {exc}")
        return None
    if not isinstance(data, dict):
        add("SIM002", "error", f"must be a JSON object, got {type(data).__name__}")
        return None

    entries = data.get("faults")
    if entries is None:
        add("SIM002", "error", "no `faults` list", locator="faults",
            fix='the file is `{"seed": N, "faults": [ ... ]}`; without the list nothing is injected')
        return None
    if not isinstance(entries, list):
        add("SIM002", "error", f"`faults` must be a list, got {type(entries).__name__}",
            locator="faults")
        return None

    summary: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        label = f"faults[{index}]"
        if not isinstance(raw, dict):
            add("SIM002", "error", f"{label} must be a mapping", locator=label)
            continue
        fid = str(raw.get("id") or f"fault-{index + 1}")
        event = str(raw.get("event") or "PreToolUse")
        action = str(raw.get("action") or "deny")
        tool = str(raw.get("tool") or ".*")

        if event not in PYTHON_HOOK_EVENTS:
            add("HOK020", "error", f"{fid}: event {event!r} is not a Python SDK hook event",
                fix=f"one of: {', '.join(PYTHON_HOOK_EVENTS)}", locator=f"{label}.event",
                source="claude_agent_sdk types.py HookEvent literal")
        if action not in FAULT_ACTIONS:
            add("SIM002", "error", f"{fid}: action {action!r} is not one of "
                                   f"{', '.join(FAULT_ACTIONS)}",
                fix="the runner refuses the file, so the whole case never runs",
                locator=f"{label}.action")

        probability = raw.get("probability", 1.0)
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            add("SIM002", "error", f"{fid}: probability {probability!r} is not a number",
                locator=f"{label}.probability")
        elif not 0.0 <= float(probability) <= 1.0:
            add("SIM002", "error", f"{fid}: probability {probability} is outside [0, 1]",
                fix="it is the share of matching calls the fault hits, drawn from the "
                    "seeded RNG inside the hook callback",
                locator=f"{label}.probability")

        latency = raw.get("latency_ms") or 0
        has_payload = {
            "deny": bool(raw.get("reason")),
            "updated_input": raw.get("updated_input") is not None,
            "error_output": raw.get("updated_tool_output") is not None,
            "latency": bool(latency),
            "allow": bool(latency),
        }.get(action, True)
        if not has_payload:
            add("SIM021", "error",
                f"{fid}: action {action!r} injects nothing — no error output and no latency",
                fix={
                    "deny": "add `reason`: it is the only thing the model reads, and a "
                            "denial without one is retried until the turn limit",
                    "updated_input": "add `updated_input` with the rewritten arguments",
                    "error_output": "add `updated_tool_output` with the result to substitute",
                    "latency": "add `latency_ms`",
                    "allow": "an `allow` with no `latency_ms` is a no-op; delete the entry",
                }.get(action, "give the fault something to inject"),
                locator=label)

        if tool and not any(ch in tool for ch in REGEX_CHARS):
            if known_tools and tool not in known_tools:
                add("SIM020", "warn", f"{fid}: no tool named {tool!r} in this project",
                    fix="tools found: " + (", ".join(sorted(known_tools)[:8]) or "(none)")
                        + ". The matcher is fullmatched against the tool name, so a typo "
                          "never fires and the run silently proves nothing.",
                    locator=f"{label}.tool",
                    source="the agent's @tool definitions and evals/mocks/")
        summary.append({"id": fid, "event": event, "action": action, "tool": tool,
                        "probability": probability, "latency_ms": latency})

    return {"path": where, "seed": data.get("seed", 0), "faults": summary}


# -- cases ------------------------------------------------------------------

def check_cases(evals_dir: Path, report: GapReport) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {"mocks": [], "personas": [], "faults": []}
    mock_root = evals_dir / "mocks"
    for case in iter_cases(evals_dir):
        case_dir = Path(case.dir)

        servers = case.meta.get("mocks")
        if isinstance(servers, list):
            for server in servers:
                used["mocks"].append(str(server))
                if not (mock_root / str(server)).is_dir():
                    report.add("SIM030", "error", "case",
                               f"case {case.name}: `mocks` names {str(server)!r}, which has no "
                               "mock directory",
                               path=case.prompt_path, locator="mocks",
                               fix=f"create {evals_dir.name}/mocks/{server}/<tool>.md, one file "
                                   "per tool — the runner raises MCP020 and the case never runs",
                               source="runner/agent_sdk_evals/mocks.py load_mock_tools")

        for key, fid in (("simulated_user", "SIM031"), ("faults", "SIM032")):
            value = case.meta.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            used["personas" if key == "simulated_user" else "faults"].append(value)
            if any((base / value).is_file() for base in (case_dir, evals_dir)):
                continue
            report.add(fid, "error", "case",
                       f"case {case.name}: `{key}` points at a missing file: {value}",
                       path=case.prompt_path, locator=key,
                       fix=f"the runner resolves it against the case directory first, then "
                           f"{evals_dir.name}/. Generate one with "
                           + ("gen_persona.py" if key == "simulated_user" else "gen_faults.py"),
                       source=_SRC_CASE)

        if case.is_simulated:
            for grader in case.graders:
                if grader.type in UNFIXED_TRAJECTORY_GRADERS:
                    report.add("EVC040", "info", "case",
                               f"case {case.name}: `{grader.type}` grader on a simulated-user case",
                               path=grader.path, locator="type",
                               fix="a persona chooses what to ask, so the tool sequence is not "
                                   "reproducible; the runner refuses `trajectory` here. Use "
                                   "`tool_used`, `llm`, or an `llm` grader with "
                                   "`target: simulated_user`. "
                                   "`/agent-sdk:eval-review` decides this one.",
                               source="runner/agent_sdk_evals/simulate.py module docstring")
    return used


# -- driver -----------------------------------------------------------------

def build_report(project: Path) -> tuple[GapReport, Path | None]:
    layout = detect_layout(project)
    evals_dir = Path(layout.evals.dir) if layout.evals else None
    report = GapReport(subject=str(project), skill="eval-simulation")
    if evals_dir is None or not evals_dir.is_dir():
        return report, None

    facts = extract_project(project)
    agent_servers = set(facts.server_names) if facts.modules else None
    known_tools = set(facts.tool_names()) | mock_tool_names(evals_dir) | set(BUILTIN_TOOLS)

    report.extend(validate_mocks(evals_dir, agent_servers=agent_servers))

    personas: list[dict[str, Any]] = []
    for path in sorted((evals_dir / "personas").glob("*.json")):
        found = check_persona(path, report)
        if found:
            personas.append(found)

    faults: list[dict[str, Any]] = []
    for path in sorted((evals_dir / "faults").glob("*.json")):
        found = check_faults(path, report, known_tools)
        if found:
            faults.append(found)

    used = check_cases(evals_dir, report)

    summary = mock_summary(evals_dir)
    report.discovered = {
        "evals_dir": str(evals_dir),
        "agent_servers": sorted(agent_servers) if agent_servers is not None else None,
        "mocks": summary,
        "personas": personas,
        "faults": faults,
        "referenced_by_cases": used,
    }

    if not summary["count"] and agent_servers:
        report.add_gap("GAP-MOCKS", "no mock servers",
                       "every case runs against whatever the real tools returned today, so a "
                       "failure cannot be told apart from a backend that changed",
                       "gen_mocks.py <project> --from-agent")
    if not personas:
        report.add_gap("GAP-PERSONAS", "no simulated users",
                       "nothing tests a conversation the case author did not script, so the "
                       "agent is only ever asked questions phrased the way it expects",
                       "gen_persona.py <project> --name <persona> --violation \"...\"")
    if not faults:
        report.add_gap("GAP-FAULTS", "no fault injection",
                       "nothing shows what the agent does when a tool is slow, denied or "
                       "wrong — the failure path is the one nobody measures",
                       "gen_faults.py <project> --tool <name> --error \"...\"")

    orphan_personas = [p["path"] for p in personas
                       if not any(Path(u).name == Path(p["path"]).name for u in used["personas"])]
    if orphan_personas:
        report.add_gap("GAP-UNUSED-PERSONAS", f"{len(orphan_personas)} persona(s) no case uses",
                       "a persona nobody references costs nothing and proves nothing",
                       "add `simulated_user: personas/<name>.json` to a case, or delete it")

    orphan_faults = [f["path"] for f in faults
                     if not any(Path(u).name == Path(f["path"]).name for u in used["faults"])]
    if orphan_faults:
        report.add_gap("GAP-UNUSED-FAULTS", f"{len(orphan_faults)} faults file(s) no case uses",
                       "an unreferenced faults file is never injected",
                       "add `faults: faults/<name>.json` to a dedicated case, never the happy path")

    report.add_option(Option(
        key="1", label="Fix the errors above and re-validate", cost="free",
        detail="every finding here is static; nothing has run yet", recommended=True))
    report.add_option(Option(
        key="2", label="Run the suite's free tier", cost="run",
        detail="mocks and faults add no model calls; a simulated-user case adds one "
               "judge-tier call per user turn plus one per violation rubric",
        runs=["../eval-run/scripts/run_evals.py <project> --tier pr"]))
    return report, evals_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", help="the agent project to validate")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as errors (exit 1 on any finding)")
    parser.add_argument("--json", action="store_true", help="machine-readable gap report")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.exists():
        print(f"no such project: {project}", file=sys.stderr)
        return EXIT_USAGE

    report, evals_dir = build_report(project)
    if evals_dir is None:
        print(f"no evals/ directory under {project}: nothing to validate. "
              "Scaffold one with /agent-sdk:eval-create.", file=sys.stderr)
        return EXIT_USAGE

    print(report.render("json" if args.json else "md"))

    if report.has_errors():
        return EXIT_FINDINGS
    if args.strict and report.findings:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
