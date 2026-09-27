"""`/agent-sdk:eval-review` scripts.

The single most important behaviour here is negative: when a check cannot be
performed — the agent's tools are unreadable, the system prompt is built at
runtime — the report says so instead of reporting a clean result. "Not
measured" and "clean" look identical in a summary and mean opposite things.
"""

from __future__ import annotations

import shutil
from pathlib import Path

VALIDATE = "skills/eval-review/scripts/validate_cases.py"
MATRIX = "skills/eval-review/scripts/coverage_matrix.py"
CROSSCHECK = "skills/eval-review/scripts/crosscheck_tools.py"


def _ids(result):
    return [f["id"] for f in result.json()["findings"]]


# -- validate_cases --------------------------------------------------------

def test_a_good_suite_is_clean(run_script, agent_dir):
    result = run_script(VALIDATE, agent_dir("good"), "--json")
    assert result.returncode == 0, result.combined
    assert {f["severity"] for f in result.json()["findings"]} <= {"info"}


def test_the_report_names_the_agent_tools_it_found(run_script, agent_dir):
    discovered = run_script(VALIDATE, agent_dir("good"), "--json").json()["discovered"]
    assert "mcp__library__reserve_book" in discovered["agent_tools"]
    assert discovered["agent_tools_source"].startswith("AST read")
    assert discovered["cases"] == 5


def test_the_planted_fixture_cases_report_their_ids(run_script, fixtures):
    result = run_script(VALIDATE, fixtures / "cases", "--json")
    ids = set(_ids(result))
    assert "EVC003" in ids, "unknown_override: `modle` is not an option"
    assert "EVC004" in ids, "not_overridable: the runner owns `cwd`"
    assert "EVC010" in ids, "bad_grader_type: an unknown grader type"
    assert "EVC040" in ids, "simulated_with_trajectory: a fixed path over a varying user"
    assert "EVC060" in ids, "no_graders: a case that can never fail"
    assert result.returncode == 1


def test_a_lenient_adversarial_case_is_a_warning(run_script, fixtures):
    result = run_script(VALIDATE, fixtures / "cases", "--json")
    lenient = [f for f in result.json()["findings"] if f["id"] == "EVC041"]
    assert lenient, "an adversarial case with no trace-level check"


def test_a_broken_case_does_not_hide_the_others(run_script, fixtures):
    """A validator that returns nothing on one bad file tells you nothing about
    the other nine."""
    payload = run_script(VALIDATE, fixtures / "cases", "--json").json()
    assert payload["discovered"]["cases"] >= 7
    assert len({f["id"] for f in payload["findings"]}) >= 6


def test_strict_promotes_warnings(run_script, tmp_agent):
    project = tmp_agent("good")
    grader = project / "evals" / "reserve-available" / "graders" / "follows_the_path.md"
    grader.write_text(grader.read_text().replace("mcp__library__", "mcp__ghost__"),
                      encoding="utf-8")
    lenient = run_script(VALIDATE, project, "--json")
    strict = run_script(VALIDATE, project, "--strict", "--json")
    assert lenient.returncode in (0, 1)
    assert strict.returncode == 1


def test_an_unreadable_tool_list_skips_the_crosscheck_rather_than_guessing(run_script, tmp_path: Path):
    project = tmp_path / "opaque"
    (project / "evals" / "case" / "graders").mkdir(parents=True)
    (project / "agent.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(model='claude-sonnet-5-5')\n", encoding="utf-8")
    (project / "evals" / "case" / "prompt.md").write_text(
        "---\ncategory: happy\n---\nDo it.\n", encoding="utf-8")
    (project / "evals" / "case" / "graders" / "used.md").write_text(
        "---\nname: used\ntype: tool_used\ntool: mcp__ghost__nothing\n---\nbody text here.\n",
        encoding="utf-8")

    payload = run_script(VALIDATE, project, "--json").json()
    assert payload["discovered"]["agent_tools"] == "(undetermined)"
    assert "EVC020" not in {f["id"] for f in payload["findings"]}
    assert any(g["id"] == "tool-crosscheck" for g in payload["gaps"]), \
        "the skipped check is reported as skipped"


def test_an_empty_suite_is_a_usage_error(run_script, tmp_path: Path):
    project = tmp_path / "bare"
    (project / "evals").mkdir(parents=True)
    result = run_script(VALIDATE, project, "--json")
    assert result.returncode == 2


def test_a_stale_runner_config_is_reported(run_script, agent_dir):
    result = run_script(VALIDATE, agent_dir("stale_runner"), "--json")
    assert "CFG050" in _ids(result)


def test_the_trap_fixture_validates_clean(run_script, agent_dir):
    """The trap agent's adversarial case is what a good one looks like."""
    result = run_script(VALIDATE, agent_dir("trap"), "--json")
    assert result.returncode == 0, result.combined
    payload = result.json()
    assert payload["discovered"]["by_category"] == {"adversarial": 1}
    assert set(payload["discovered"]["by_grader_type"]) == {"no_tool", "tool_used", "llm"}


# -- coverage_matrix -------------------------------------------------------

def test_the_good_fixture_covers_every_rule(run_script, agent_dir):
    payload = run_script(MATRIX, agent_dir("good"), "--json").json()
    assert payload["matrix"]["uncovered"] == []
    assert payload["discovered"]["rule_coverage"] == "4/4"
    assert payload["shape"]["ok"]


def test_gaps_are_advice_unless_strict(run_script, tmp_agent):
    project = tmp_agent("good")
    for name in ("no-cancel-unasked", "two-turn-memory", "unknown-title"):
        shutil.rmtree(project / "evals" / name)

    lenient = run_script(MATRIX, project, "--json")
    assert lenient.returncode == 0, "a coverage gap is not a failure"
    assert lenient.json()["gaps"], "but it is still reported"

    strict = run_script(MATRIX, project, "--strict", "--json")
    assert strict.returncode == 1


def test_a_thin_suite_reports_its_missing_categories(run_script, tmp_agent):
    project = tmp_agent("good")
    for name in ("no-cancel-unasked", "two-turn-memory", "unknown-title",
                 "refuse-double-booking"):
        shutil.rmtree(project / "evals" / name)
    payload = run_script(MATRIX, project, "--json").json()
    assert set(payload["shape"]["missing_categories"]) == {
        "edge", "adversarial", "memory", "regression"}
    assert payload["shape"]["adversarial_ratio"] == 0.0


def test_a_refusal_rule_with_no_trace_check_is_an_n_plus_one_gap(run_script, tmp_agent):
    project = tmp_agent("good")
    for name in ("no-cancel-unasked", "two-turn-memory", "unknown-title",
                 "refuse-double-booking"):
        shutil.rmtree(project / "evals" / name)
    payload = run_script(MATRIX, project, "--json").json()
    reasons = {gap["reason"] for gap in payload["n_plus_one"]}
    assert reasons, "the remaining case scores no restraint"
    assert reasons <= {"no_case", "no_trace_check"}


def test_a_runtime_system_prompt_reports_unknown_not_zero(run_script, tmp_path: Path):
    project = tmp_path / "dynamic"
    (project / "evals" / "case" / "graders").mkdir(parents=True)
    (project / "agent.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(system_prompt=load_from_db())\n", encoding="utf-8")
    (project / "evals" / "case" / "prompt.md").write_text(
        "---\ncategory: happy\n---\nDo it.\n", encoding="utf-8")
    (project / "evals" / "case" / "graders" / "ends.md").write_text(
        "---\nname: ends\ntype: terminal\nsubtype: success\n---\nbody text here.\n",
        encoding="utf-8")

    payload = run_script(MATRIX, project, "--json").json()
    assert payload["discovered"]["system_prompt"]["kind"] == "dynamic"
    assert payload["discovered"]["rule_coverage"].startswith("unknown")
    assert any(g["id"] == "system-prompt" for g in payload["gaps"])


def test_the_matrix_shows_what_it_matched_on(run_script, agent_dir):
    payload = run_script(MATRIX, agent_dir("good"), "--json").json()
    row = payload["matrix"]["rows"][0]
    hit = row["cases"][0]
    assert hit["matched_tools"] or len(hit["matched_phrases"]) >= 2
    assert "not that the rule holds" in payload["matrix"]["basis"]


def test_a_project_without_evals_is_a_usage_error(run_script, agent_dir):
    result = run_script(MATRIX, agent_dir("no_evals"), "--json")
    assert result.returncode == 2


# -- crosscheck_tools ------------------------------------------------------

def test_a_consistent_project_is_clean(run_script, agent_dir):
    result = run_script(CROSSCHECK, agent_dir("good"), "--json")
    assert result.returncode == 0, result.combined
    payload = result.json()
    assert payload["findings"] == []
    assert payload["discovered"]["untested_tools"] == []


def test_an_unqualified_tool_name_is_reported_with_the_qualified_one(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "bare-name"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text("---\ncategory: happy\n---\nDo it.\n", encoding="utf-8")
    (case / "graders" / "used.md").write_text(
        "---\nname: used\ntype: tool_used\ntool: reserve_book\n---\nbody text here.\n",
        encoding="utf-8")

    result = run_script(CROSSCHECK, project, "--json")
    assert result.returncode == 1
    message = next(f["message"] for f in result.json()["findings"] if f["id"] == "EVC020")
    assert "mcp__library__reserve_book" in message


def test_a_mock_for_a_server_the_agent_lacks_is_mcp020(run_script, tmp_agent):
    project = tmp_agent("good")
    orphan = project / "evals" / "mocks" / "billing"
    orphan.mkdir(parents=True)
    (orphan / "charge.md").write_text(
        "---\ntype: canned\nschema:\n  amount: str\n---\nCharged.\n", encoding="utf-8")

    result = run_script(CROSSCHECK, project, "--json")
    assert "MCP020" in _ids(result)


def test_an_untested_tool_is_a_gap_not_a_finding(run_script, tmp_agent):
    project = tmp_agent("good")
    shutil.rmtree(project / "evals" / "no-cancel-unasked")

    result = run_script(CROSSCHECK, project, "--json")
    payload = result.json()
    assert "mcp__library__cancel_reservation" in payload["discovered"]["untested_tools"]
    assert payload["findings"] == []
    assert result.returncode == 0, "a gap is advice"
    assert run_script(CROSSCHECK, project, "--strict", "--json").returncode == 1


def test_task_agent_and_the_synthetic_tools_are_never_mismatches(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "uses-aliases"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text("---\ncategory: happy\n---\nDo it.\n", encoding="utf-8")
    (case / "graders" / "none.md").write_text(
        "---\nname: none\ntype: no_tool\ntools: [Agent, Task, StructuredOutput, ToolSearch]\n"
        "---\nbody text here.\n", encoding="utf-8")

    result = run_script(CROSSCHECK, project, "--json")
    assert [f for f in result.json()["findings"] if f["id"] == "EVC020"] == []


def test_an_unreadable_tool_list_refuses_to_compare(run_script, tmp_path: Path):
    project = tmp_path / "opaque"
    (project / "evals" / "case" / "graders").mkdir(parents=True)
    (project / "agent.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(model='claude-sonnet-5-5')\n", encoding="utf-8")
    (project / "evals" / "case" / "prompt.md").write_text(
        "---\ncategory: happy\n---\nDo it.\n", encoding="utf-8")
    (project / "evals" / "case" / "graders" / "ends.md").write_text(
        "---\nname: ends\ntype: terminal\nsubtype: success\n---\nbody text here.\n",
        encoding="utf-8")

    result = run_script(CROSSCHECK, project, "--json")
    assert result.returncode == 2
    assert any(g["id"] == "agent-tools" for g in result.json()["gaps"])
