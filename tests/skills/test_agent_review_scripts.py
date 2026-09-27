"""`agent-review`: the findings each fixture must produce, and the load check.

Findings are asserted by id, because an id is what a skill branches on and what
a user quotes back. Scripts run as subprocesses, the way a skill runs them, so
argument parsing and exit codes are covered too.
"""

from __future__ import annotations

import json

import pytest

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE

LINT = "skills/agent-review/scripts/lint_agent.py"
LOAD = "skills/agent-review/scripts/load_agent.py"


def ids_of(result) -> set[str]:
    return {finding["id"] for finding in json.loads(result.stdout)["findings"]}


@pytest.fixture
def lint(run_script, agent_dir):
    def _run(name: str, *args: str):
        return run_script(LINT, str(agent_dir(name)), "--json", *args)

    return _run


# -- per fixture ----------------------------------------------------------

@pytest.mark.parametrize("fixture,expected", [
    ("good", set()),
    ("drift", {"AGT003", "AGT010", "AGT011", "AGT020", "AGT030", "AGT031",
               "OPT001", "OPT002", "OPT010", "OPT011", "HOK001"}),
    ("inline_main", {"AGT003", "OPT020"}),
    ("entry_env", {"OPT004"}),
    ("external_mcp", {"AGT004", "MCP001", "MCP002", "OPT001", "OPT010", "OPT011"}),
    ("subagents", {"SUB001", "SUB002", "SUB003", "SUB010"}),
    ("hooks_bad", {"HOK001", "HOK002", "HOK003", "HOK010", "HOK020", "HOK030"}),
    ("deploy_ready", set()),
])
def test_each_fixture_reports_the_findings_it_was_built_for(lint, fixture, expected):
    found = ids_of(lint(fixture))
    assert expected <= found, f"missing {sorted(expected - found)}"


def test_a_clean_agent_produces_no_errors_and_exits_zero(lint):
    result = lint("good")
    assert json.loads(result.stdout)["summary"]["errors"] == 0
    assert result.returncode == EXIT_OK


def test_the_drift_fixture_fails(lint):
    assert lint("drift").returncode == EXIT_FINDINGS


# -- individual rules, where a fixture would be the wrong place ----------

def test_a_retired_model_is_an_error(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    source = (project / "agent.py").read_text()
    (project / "agent.py").write_text(
        source.replace('os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")',
                       '"claude-3-5-sonnet-20241022"')
    )
    result = run_script(LINT, str(project), "--json")
    assert "AGT012" in ids_of(result)
    assert result.returncode == EXIT_FINDINGS


def test_no_model_anywhere_is_a_warning_about_the_inherited_default(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    source = (project / "agent.py").read_text()
    (project / "agent.py").write_text(
        source.replace('        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),\n', "")
    )
    assert "OPT012" in ids_of(run_script(LINT, str(project), "--json"))


def test_a_malformed_output_format_is_an_error(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    source = (project / "agent.py").read_text()
    (project / "agent.py").write_text(
        source.replace("        max_turns=2,",
                       '        output_format={"type": "json", "schema": {}},\n'
                       "        max_turns=2,")
    )
    result = run_script(LINT, str(project), "--json")
    assert "OPT050" in ids_of(result)
    assert result.returncode == EXIT_FINDINGS


@pytest.mark.parametrize("snippet,expected", [
    ('        permission_mode="whenever",', "OPT060"),
    ('        effort="gentle",', "OPT061"),
])
def test_a_value_outside_the_literal_set_is_an_error(run_script, tmp_agent, snippet, expected):
    project = tmp_agent("no_evals")
    source = (project / "agent.py").read_text()
    (project / "agent.py").write_text(
        source.replace('        permission_mode="dontAsk",', snippet)
        if expected == "OPT060"
        else source.replace("        max_turns=2,", snippet + "\n        max_turns=2,")
    )
    assert expected in ids_of(run_script(LINT, str(project), "--json"))


def test_several_agent_modules_with_no_named_builder_is_a_warning(run_script, tmp_agent):
    project = tmp_agent("inline_main")
    (project / "other.py").write_text(
        "import asyncio\n"
        "from claude_agent_sdk import ClaudeAgentOptions, query\n\n"
        "async def go():\n"
        "    async for m in query(prompt='hi', options=ClaudeAgentOptions(max_turns=1)):\n"
        "        print(m)\n"
    )
    assert "AGT002" in ids_of(run_script(LINT, str(project), "--json"))


def test_a_module_with_no_subagents_is_never_told_about_a_neighbours(run_script, tmp_agent):
    """Reviewing one file must not read its whole directory: that is how a sweep
    reported the same AgentDefinition against 25 unrelated modules."""
    project = tmp_agent("subagents")
    (project / "plain.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(max_turns=2, tools=[], max_budget_usd=0.1)\n"
    )
    found = ids_of(run_script(LINT, str(project / "plain.py"), "--json"))
    assert not any(i.startswith("SUB") for i in found), found
    assert "OPT040" not in found


def test_subagents_defined_but_not_callable_is_a_warning(run_script, tmp_agent):
    project = tmp_agent("subagents")
    source = (project / "agent.py").read_text()
    (project / "agent.py").write_text(
        source.replace('"mcp__loans__loan_record", "Task", "Read", "Grep"',
                       '"mcp__loans__loan_record", "Read", "Grep"')
    )
    assert "OPT040" in ids_of(run_script(LINT, str(project), "--json"))


def test_setting_sources_empty_on_an_old_pinned_sdk_is_a_warning(run_script, tmp_agent):
    project = tmp_agent("entry_env")
    (project / "requirements.txt").write_text("claude-agent-sdk<=0.1.59\n")
    assert "OPT021" in ids_of(run_script(LINT, str(project), "--json"))


def test_a_missing_stdio_command_can_be_skipped_for_another_machine(lint):
    assert "MCP002" in ids_of(lint("external_mcp"))
    assert "MCP002" not in ids_of(lint("external_mcp", "--no-path-check"))


# -- exit codes and arguments --------------------------------------------

def test_strict_turns_warnings_into_a_failure(lint):
    assert lint("subagents").returncode == EXIT_OK
    assert lint("subagents", "--strict").returncode == EXIT_FINDINGS


def test_strict_promotes_bypass_permissions_to_an_error(lint):
    plain = json.loads(lint("drift").stdout)["findings"]
    strict = json.loads(lint("drift", "--strict").stdout)["findings"]
    severity = {f["id"]: f["severity"] for f in plain}
    severity_strict = {f["id"]: f["severity"] for f in strict}
    assert severity["OPT002"] == "warn"
    assert severity_strict["OPT002"] == "error"


def test_a_directory_with_no_agent_exits_two(run_script, tmp_path):
    (tmp_path / "notes.md").write_text("nothing here\n")
    assert run_script(LINT, str(tmp_path)).returncode == EXIT_USAGE


def test_a_missing_path_exits_two(run_script, tmp_path):
    assert run_script(LINT, str(tmp_path / "nope")).returncode == EXIT_USAGE


def test_the_markdown_report_names_the_ids_and_the_sources(lint, agent_dir, run_script):
    result = run_script(LINT, str(agent_dir("drift")))
    assert "`AGT030`" in result.stdout
    assert "Source:" in result.stdout
    assert "code.claude.com" in result.stdout


def test_the_report_says_what_it_found_before_what_is_wrong(lint):
    discovered = json.loads(lint("good").stdout)["discovered"]
    assert discovered["entry"]["builder"] == "build_options"
    assert discovered["tools"]["in_process"] == [
        "mcp__library__cancel_reservation", "mcp__library__lookup_book",
        "mcp__library__reserve_book",
    ]


def test_the_review_never_writes_anything(lint, agent_dir):
    project = agent_dir("drift")
    before = {p: p.stat().st_mtime for p in project.rglob("*") if p.is_file()}
    lint("drift")
    after = {p: p.stat().st_mtime for p in project.rglob("*") if p.is_file()}
    assert before == after


# -- load_agent -----------------------------------------------------------

def test_the_load_probe_runs_through_the_resolved_interpreter(run_script, agent_dir, fake_sdk):
    result = run_script(LOAD, str(agent_dir("good")), "--json",
                        env={"AGENT_SDK_PYTHON": str(fake_sdk)})
    assert result.returncode == EXIT_OK
    payload = json.loads(result.stdout)
    assert payload["loaded"]
    assert payload["entry"] == "agent:build_options"
    assert payload["options"]["model"] == "claude-sonnet-5-5"


def test_the_probe_source_is_recognisable_to_the_fake_interpreter():
    from pathlib import Path

    probe = Path("skills/agent-review/scripts/load_agent.py").read_text()
    assert "build_options" in probe, "fake_sdk.py keys the load probe on this literal"


def test_an_import_failure_is_reported_with_a_plain_english_hint(run_script, agent_dir, fake_sdk):
    result = run_script(LOAD, str(agent_dir("good")), "--json",
                        env={"AGENT_SDK_PYTHON": str(fake_sdk), "FAKE_SDK_IMPORT_ERROR": "1"})
    assert result.returncode == EXIT_FINDINGS
    payload = json.loads(result.stdout)
    assert not payload["loaded"]
    assert "claude_agent_sdk" in payload["hint"]


def test_no_interpreter_with_the_sdk_exits_two(run_script, agent_dir, fake_sdk):
    result = run_script(LOAD, str(agent_dir("good")),
                        env={"AGENT_SDK_PYTHON": "/nonexistent/python", "PATH": ""})
    assert result.returncode == EXIT_USAGE
    assert "claude-agent-sdk" in result.stderr


def test_a_project_with_nothing_to_load_exits_two(run_script, tmp_path, fake_sdk):
    (tmp_path / "notes.md").write_text("nothing\n")
    result = run_script(LOAD, str(tmp_path), env={"AGENT_SDK_PYTHON": str(fake_sdk)})
    assert result.returncode == EXIT_USAGE


def test_the_text_output_says_no_session_was_started(run_script, agent_dir, fake_sdk):
    result = run_script(LOAD, str(agent_dir("good")), env={"AGENT_SDK_PYTHON": str(fake_sdk)})
    assert "No session was started" in result.stdout
