"""`eval-simulation`: three generators and the validator that holds them honest.

The generators are held to two rules. `--dry-run` writes nothing. And what a real
run writes is loaded back **by the runner's own loaders** — `mocks.load_mock_tools`,
`simulate.Persona.from_dict`, `faults.load_plan` — because "the shape the runner
reads" is not a shape this plugin gets to define. A generator that agreed with
its own idea of the format and disagreed with the runner would pass every test
written against itself.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE

PLUGIN_ROOT = Path(__file__).resolve().parents[2]

# The runner imports `claude_agent_sdk` lazily, but the stub is cheap insurance:
# these three modules must be importable on a plain interpreter.
for _path in (PLUGIN_ROOT / "tests" / "fixtures" / "stubs", PLUGIN_ROOT / "runner"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

GEN_MOCKS = "skills/eval-simulation/scripts/gen_mocks.py"
GEN_PERSONA = "skills/eval-simulation/scripts/gen_persona.py"
GEN_FAULTS = "skills/eval-simulation/scripts/gen_faults.py"
VALIDATE = "skills/eval-simulation/scripts/validate_sim.py"


def ids_of(result) -> set[str]:
    return {finding["id"] for finding in json.loads(result.stdout)["findings"]}


def severities(result) -> dict[str, str]:
    return {f["id"]: f["severity"] for f in json.loads(result.stdout)["findings"]}


@pytest.fixture
def runner_loaders():
    """The runner's own loaders, or a skip if they need something we lack."""
    try:
        from agent_sdk_evals import faults as runner_faults
        from agent_sdk_evals import mocks as runner_mocks
        from agent_sdk_evals import simulate as runner_simulate
    except ImportError as exc:  # pragma: no cover - only on a broken checkout
        pytest.skip(f"the runner copy is not importable here: {exc}")
    return runner_mocks, runner_simulate, runner_faults


# -- gen_mocks --------------------------------------------------------------

def test_dry_run_writes_no_mock_file(run_script, tmp_agent):
    project = tmp_agent("good")
    out = project / "evals" / "generated"
    result = run_script(GEN_MOCKS, str(project), "--from-agent", "--out", str(out / "mocks"),
                        "--dry-run", "--json")
    assert result.returncode == EXIT_OK, result.combined
    assert json.loads(result.stdout)["plan"]["will_write"], "the plan should be non-empty"
    assert not out.exists(), "--dry-run must not touch the disk"


def test_a_mock_is_generated_per_tool_with_the_agents_own_schema(run_script, tmp_agent,
                                                                 runner_loaders):
    runner_mocks, _, _ = runner_loaders
    project = tmp_agent("good")
    out = project / "evals" / "generated"
    result = run_script(GEN_MOCKS, str(project), "--from-agent", "--out", str(out / "mocks"),
                        "--json")
    assert result.returncode == EXIT_OK, result.combined

    generated = runner_mocks.load_mock_tools(out, "library")
    by_name = {t.name: t for t in generated}
    assert set(by_name) == {"lookup_book", "reserve_book", "cancel_reservation"}
    assert by_name["lookup_book"].schema == {"title": "str"}
    assert by_name["reserve_book"].schema == {"title": "str", "member_id": "str"}
    assert by_name["lookup_book"].description == "Find a book by title and report copies and holders"
    assert by_name["lookup_book"].kind == "canned"


def test_the_generated_body_substitutes_every_declared_input(run_script, tmp_agent,
                                                             runner_loaders):
    runner_mocks, _, _ = runner_loaders
    project = tmp_agent("good")
    out = project / "evals" / "generated"
    run_script(GEN_MOCKS, str(project), "--from-agent", "--out", str(out / "mocks"), "--json")
    mock = {t.name: t for t in runner_mocks.load_mock_tools(out, "library")}["reserve_book"]
    rendered = runner_mocks.substitute(mock.body, {"title": "Dune", "member_id": "member-42"},
                                       out / "mocks" / "library")
    assert "Dune" in rendered and "member-42" in rendered
    assert "{{input." not in rendered.split("\n")[0]


def test_an_external_server_gets_a_stub_with_a_todo_schema(run_script, tmp_agent):
    project = tmp_agent("external_mcp")
    out = project / "evals" / "generated"
    result = run_script(GEN_MOCKS, str(project), "--from-agent", "--out", str(out / "mocks"),
                        "--json")
    assert result.returncode == EXIT_OK, result.combined
    servers = {row["server"] for row in json.loads(result.stdout)["discovered"]["tools"]}
    assert servers, "an external mcp_servers entry should still get a stub"
    for server in servers:
        stub = out / "mocks" / server / "replace_me.md"
        assert stub.is_file()
        assert "TODO" in stub.read_text(encoding="utf-8")


def test_existing_mocks_are_skipped_unless_forced(run_script, tmp_agent):
    project = tmp_agent("good")
    first = run_script(GEN_MOCKS, str(project), "--from-agent", "--json")
    actions = {i["action"] for i in json.loads(first.stdout)["plan"]["items"]}
    assert actions == {"skip"}, "the good fixture already has its mocks"
    forced = run_script(GEN_MOCKS, str(project), "--from-agent", "--force", "--json")
    assert {i["action"] for i in json.loads(forced.stdout)["plan"]["items"]} == {"overwrite"}


def test_nothing_to_mock_is_exit_one(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN_MOCKS, str(project), "--server", "nosuch", "--json")
    assert result.returncode == EXIT_FINDINGS
    assert "reason" in json.loads(result.stdout)


# -- gen_persona ------------------------------------------------------------

def test_a_persona_dry_run_writes_nothing(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(GEN_PERSONA, str(project), "--name", "novice",
                        "--violation", "the user never names a tool", "--dry-run", "--json")
    assert result.returncode == EXIT_OK, result.combined
    assert not (project / "evals" / "personas" / "novice.json").exists()


def test_a_generated_persona_loads_as_the_runners_persona(run_script, tmp_agent, runner_loaders):
    _, runner_simulate, _ = runner_loaders
    project = tmp_agent("good")
    result = run_script(
        GEN_PERSONA, str(project), "--name", "impatient-renewer",
        "--goal", "renew an overdue loan without giving a member id",
        "--style", "Terse. One sentence per turn.",
        "--opening", "I need to renew my book.",
        "--behaviour", "Never volunteer your member id.",
        "--behaviour", "Never name a tool.",
        "--violation", "the user never states a member id unless asked twice",
        "--violation", "the user never names a tool",
        "--max-turns", "3", "--stop-marker", "FINISHED", "--json")
    assert result.returncode == EXIT_OK, result.combined

    path = project / "evals" / "personas" / "impatient-renewer.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) <= {"name", "goal", "style", "model", "opening", "max_user_turns",
                        "stop_marker", "constraints", "violation_rubrics"}, \
        "the runner drops anything else silently, so nothing else may be written"

    persona = runner_simulate.Persona.from_dict(raw)
    assert persona.name == "impatient-renewer"
    assert persona.max_user_turns == 3
    assert persona.stop_marker == "FINISHED"
    assert persona.constraints == ["Never volunteer your member id.", "Never name a tool."]
    assert persona.has_rubrics and len(persona.violation_rubrics) == 2
    assert persona.opening == "I need to renew my book."


def test_the_generated_persona_renders_a_usable_prompt(run_script, tmp_agent, runner_loaders):
    _, runner_simulate, _ = runner_loaders
    project = tmp_agent("good")
    run_script(GEN_PERSONA, str(project), "--name", "novice",
               "--behaviour", "Never use a library term you were not given.",
               "--violation", "the user never names a tool", "--json")
    raw = json.loads((project / "evals" / "personas" / "novice.json").read_text(encoding="utf-8"))
    persona = runner_simulate.Persona.from_dict(raw)
    prompt = runner_simulate.build_prompt(persona, [("user", "hi"), ("agent", "hello")])
    assert "Rules you follow no matter what" in prompt
    assert "Never use a library term you were not given." in prompt
    assert persona.stop_marker in prompt


def test_a_persona_without_violation_rubrics_is_refused(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(GEN_PERSONA, str(project), "--name", "unsupervised", "--json")
    assert result.returncode == EXIT_USAGE
    assert json.loads(result.stdout)["error"] == "SIM001"
    assert not (project / "evals" / "personas" / "unsupervised.json").exists()


def test_a_persona_with_no_turns_is_refused(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(GEN_PERSONA, str(project), "--name", "zero", "--max-turns", "0",
                        "--violation", "the user stays in character", "--json")
    assert result.returncode == EXIT_USAGE
    assert json.loads(result.stdout)["error"] == "SIM005"


# -- gen_faults -------------------------------------------------------------

def test_a_faults_dry_run_writes_nothing(run_script, tmp_agent):
    project = tmp_agent("good")
    faults_dir = project / "evals" / "faults"
    before = sorted(p.name for p in faults_dir.glob("*.json")) if faults_dir.is_dir() else []
    result = run_script(GEN_FAULTS, str(project), "--tool", "mcp__library__lookup_book",
                        "--latency-ms", "1500", "--dry-run", "--json")
    assert result.returncode == EXIT_OK, result.combined
    planned = json.loads(result.stdout)["plan"]["will_write"]
    assert planned, "the plan should name the file it would write"
    assert not Path(planned[0]).exists(), "--dry-run must not touch the disk"
    after = sorted(p.name for p in faults_dir.glob("*.json")) if faults_dir.is_dir() else []
    assert after == before


def test_a_generated_faults_file_loads_as_the_runners_plan(run_script, tmp_agent, runner_loaders):
    _, _, runner_faults = runner_loaders
    project = tmp_agent("good")
    result = run_script(GEN_FAULTS, str(project), "--tool", "mcp__library__lookup_book",
                        "--error", "catalog service timed out", "--latency-ms", "1500",
                        "--probability", "1.0", "--seed", "7", "--json")
    assert result.returncode == EXIT_OK, result.combined

    path = project / "evals" / "faults" / "library-lookup-book.json"
    plan = runner_faults.read_plan_file(path, run=1)
    assert plan.seed == 8, "the runner folds the run index into the seed"
    assert len(plan.faults) == 1
    fault = plan.faults[0]
    assert fault.event == "PostToolUse"
    assert fault.action == "error_output"
    assert fault.tool == "mcp__library__lookup_book"
    assert fault.matches_tool("mcp__library__lookup_book")
    assert fault.updated_tool_output == "catalog service timed out"
    assert fault.latency_ms == 1500
    assert fault.probability == 1.0


def test_latency_alone_is_a_pretooluse_latency_fault(run_script, tmp_agent, runner_loaders):
    _, _, runner_faults = runner_loaders
    project = tmp_agent("good")
    run_script(GEN_FAULTS, str(project), "--tool", "mcp__library__.*",
               "--latency-ms", "2500", "--out", str(project / "evals" / "faults" / "slow.json"),
               "--json")
    plan = runner_faults.read_plan_file(project / "evals" / "faults" / "slow.json")
    fault = plan.faults[0]
    assert (fault.event, fault.action, fault.latency_ms) == ("PreToolUse", "latency", 2500)
    assert fault.matches_tool("mcp__library__reserve_book")
    assert not fault.matches_tool("Bash")


def test_a_probability_outside_zero_to_one_is_refused(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(GEN_FAULTS, str(project), "--tool", "Write", "--error", "nope",
                        "--probability", "2", "--json")
    assert result.returncode == EXIT_USAGE
    assert json.loads(result.stdout)["error"] == "SIM002"


def test_a_fault_that_injects_nothing_is_refused(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(GEN_FAULTS, str(project), "--tool", "Write", "--json")
    assert result.returncode == EXIT_USAGE
    assert json.loads(result.stdout)["error"] == "SIM021"


# -- validate_sim -----------------------------------------------------------

def test_a_clean_suite_reports_no_errors(run_script, agent_dir):
    result = run_script(VALIDATE, str(agent_dir("good")), "--json")
    assert result.returncode == EXIT_OK, result.combined
    payload = json.loads(result.stdout)
    assert payload["summary"]["errors"] == 0
    assert payload["discovered"]["mocks"]["servers"] == ["library"]


def test_warnings_alone_pass_but_strict_fails(run_script, tmp_agent):
    """A mock for a server the agent does not mount is MCP020 — warn, not error."""
    project = tmp_agent("good")
    ghost = project / "evals" / "mocks" / "ghostly"
    ghost.mkdir(parents=True)
    shutil.copy(project / "evals" / "mocks" / "library" / "reserve_book.md",
                ghost / "reserve_book.md")

    lenient = run_script(VALIDATE, str(project), "--json")
    assert lenient.returncode == EXIT_OK, lenient.combined
    payload = json.loads(lenient.stdout)
    assert payload["summary"]["errors"] == 0
    assert payload["summary"]["warnings"] > 0

    strict = run_script(VALIDATE, str(project), "--strict", "--json")
    assert strict.returncode == EXIT_FINDINGS


def test_a_missing_project_is_a_usage_error(run_script, tmp_path):
    assert run_script(VALIDATE, str(tmp_path / "nope"), "--json").returncode == EXIT_USAGE


def test_a_project_without_evals_is_a_usage_error(run_script, agent_dir):
    assert run_script(VALIDATE, str(agent_dir("no_evals")), "--json").returncode == EXIT_USAGE


@pytest.fixture
def defective(tmp_agent):
    """A copy of `good` with one planted defect per rule."""
    project = tmp_agent("good")
    evals = project / "evals"

    # SIM010: a mock that advertises no schema.
    (evals / "mocks" / "library" / "lookup_book.md").write_text(
        "---\ntype: canned\ndescription: no schema here\n---\nDune: 2 copies.\n",
        encoding="utf-8")

    # MCP020: a mock for a server the agent does not mount.
    ghost = evals / "mocks" / "ghostly"
    ghost.mkdir(parents=True)
    shutil.copy(evals / "mocks" / "library" / "reserve_book.md", ghost / "reserve_book.md")

    # SIM001/003/005/006: a persona with none of the things that keep it honest.
    (evals / "personas" / "broken.json").write_text(json.dumps({
        "name": "broken", "goal": "x", "style": "y",
        "constraints": "be terse",
        "max_user_turns": 0,
        "model": "claude-3-opus-20240229",
    }), encoding="utf-8")

    # SIM002/020/021: a probability of 2, an unknown tool, and a no-op entry.
    faults = evals / "faults"
    faults.mkdir(parents=True, exist_ok=True)
    (faults / "bad.json").write_text(json.dumps({"seed": 1, "faults": [
        {"id": "boom", "event": "PreToolUse", "tool": "mcp__library__nope",
         "action": "deny", "probability": 2.0, "reason": "x"},
        {"id": "nop", "event": "PreToolUse", "tool": "Read", "action": "latency"},
    ]}), encoding="utf-8")

    # SIM030/031/032: a case pointing at three things that do not exist.
    prompt = evals / "reserve-available" / "prompt.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(
            "mocks: [library]",
            "mocks: [library, ghost]\nsimulated_user: personas/missing.json\n"
            "faults: faults/missing.json"),
        encoding="utf-8")
    return project


def test_every_planted_defect_is_found(run_script, defective):
    result = run_script(VALIDATE, str(defective), "--json")
    assert result.returncode == EXIT_FINDINGS
    found = ids_of(result)
    expected = {"SIM001", "SIM002", "SIM003", "SIM005", "SIM006", "SIM010",
                "SIM020", "SIM021", "SIM030", "SIM031", "SIM032", "MCP020"}
    assert expected <= found, f"missing {sorted(expected - found)}"


def test_the_severities_match_the_published_bands(run_script, defective):
    grades = severities(run_script(VALIDATE, str(defective), "--json"))
    for error_id in ("SIM002", "SIM003", "SIM005", "SIM006", "SIM010",
                     "SIM021", "SIM030", "SIM031", "SIM032"):
        assert grades[error_id] == "error", error_id
    for warn_id in ("SIM020", "MCP020"):
        assert grades[warn_id] == "warn", warn_id


def test_an_unknown_persona_key_is_a_warning_naming_the_real_one(run_script, tmp_agent):
    """`max_turns` is dropped on load, so the warning must name `max_user_turns`."""
    project = tmp_agent("good")
    (project / "evals" / "personas" / "stale.json").write_text(json.dumps({
        "name": "stale", "goal": "x", "style": "y",
        "max_turns": 4, "stop_when": "the desk answers", "follow_ups": ["and again"],
        "violation_rubrics": ["the generated user response stays in character"],
    }), encoding="utf-8")

    result = run_script(VALIDATE, str(project), "--json")
    sim004 = [f for f in json.loads(result.stdout)["findings"] if f["id"] == "SIM004"]
    assert sim004, "a persona key the runner does not read must be reported"
    assert all(f["severity"] == "warn" for f in sim004)
    by_key = {f["locator"]: f for f in sim004}
    assert {"max_turns", "stop_when", "follow_ups"} <= set(by_key)
    assert "max_user_turns" in by_key["max_turns"]["fix"]
    assert "stop_marker" in by_key["stop_when"]["fix"]
    assert result.returncode == EXIT_OK, "an ignored key is a warning, not an error"


def test_a_trajectory_grader_on_a_simulated_case_is_reported_as_info(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    prompt = case / "prompt.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(
            "mocks: [library]", "mocks: [library]\nsimulated_user: personas/impatient.json"),
        encoding="utf-8")
    result = run_script(VALIDATE, str(project), "--json")
    evc040 = [f for f in json.loads(result.stdout)["findings"] if f["id"] == "EVC040"]
    assert evc040, "the fixture case has a trajectory grader"
    assert evc040[0]["severity"] == "info"
    assert "eval-review" in evc040[0]["fix"]


def test_absent_levers_are_gaps_not_findings(run_script, tmp_agent):
    """A lever nobody built is a gap; a lever nobody references is a different gap."""
    project = tmp_agent("good")
    shutil.rmtree(project / "evals" / "faults")

    result = run_script(VALIDATE, str(project), "--json")
    assert result.returncode == EXIT_OK, "an absence is never a finding"
    payload = json.loads(result.stdout)
    gap_ids = {gap["id"] for gap in payload["gaps"]}
    assert "GAP-FAULTS" in gap_ids, "no faults file at all"
    assert "GAP-UNUSED-PERSONAS" in gap_ids, "the persona exists but no case names it"
    assert {f["id"] for f in payload["findings"]} == set()


def test_the_generated_files_validate_clean(run_script, tmp_agent):
    """The full loop: generate all three, wire them into a case, validate."""
    project = tmp_agent("good")
    run_script(GEN_PERSONA, str(project), "--name", "novice",
               "--behaviour", "Never name a tool.",
               "--violation", "the user never names a tool", "--json")
    run_script(GEN_FAULTS, str(project), "--tool", "mcp__library__lookup_book",
               "--error", "catalog service timed out", "--json")
    prompt = project / "evals" / "unknown-title" / "prompt.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(
            "mocks: [library]",
            "mocks: [library]\nsimulated_user: personas/novice.json\n"
            "faults: faults/library-lookup-book.json"),
        encoding="utf-8")
    result = run_script(VALIDATE, str(project), "--json")
    payload = json.loads(result.stdout)
    assert payload["summary"]["errors"] == 0, payload["findings"]
    generated_names = ("novice.json", "library-lookup-book.json")
    about_generated = [f for f in payload["findings"]
                       if any(name in (f.get("path") or "") for name in generated_names)]
    assert about_generated == [], about_generated
