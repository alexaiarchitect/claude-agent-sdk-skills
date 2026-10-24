"""eval-ci writes the gate, checks the gate, and rates the practice around it.

The generators are exercised end to end: a plan that writes nothing, a write
that lands, and the rendered YAML read back for the things that make a gate
real — a secret reference rather than a literal, the PYTHONPATH the runner copy
needs, and no placeholder left behind.
"""

import json
import re
from pathlib import Path

import pytest

GEN = "skills/eval-ci/scripts/gen_workflows.py"
LINT = "skills/eval-ci/scripts/lint_workflows.py"
MATURITY = "skills/eval-ci/scripts/assess_maturity.py"

#: `{{NAME}}` that is not part of GitHub's own `${{ ... }}` syntax.
UNFILLED = re.compile(r"(?<!\$)\{\{[^}]*\}\}")

CASES = ("reserve_book", "refuse_double_booking")


def make_project(tmp_path: Path, *, cases=CASES, runner=True, config=None) -> Path:
    project = tmp_path / "proj"
    (project / "evals").mkdir(parents=True)
    (project / "agent.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n"
        "def build_options():\n    return ClaudeAgentOptions()\n")
    (project / "requirements.txt").write_text("claude-agent-sdk\n")
    for case in cases:
        (project / "evals" / case / "graders").mkdir(parents=True)
        (project / "evals" / case / "prompt.md").write_text("---\ncategory: happy\n---\nhi\n")
        (project / "evals" / case / "graders" / "ok.md").write_text(
            "---\ntype: regex\npattern: .\n---\n")
    if runner:
        package = project / "evals" / "runner" / "agent_sdk_evals"
        package.mkdir(parents=True)
        (package / "VERSION").write_text("0.1.4\n")
        (package / "__init__.py").write_text("")
    if config is not None:
        (project / "evals" / "eval_config.json").write_text(json.dumps(config, indent=2))
    return project


def stage_results(project: Path, stamp: str, *, cases=CASES, runs=1, status="PASSED") -> Path:
    """A results directory in the shape the runner writes (CONTRACTS §6–§7)."""
    directory = project / "evals" / "results" / stamp
    directory.mkdir(parents=True)
    for case in cases:
        (directory / f"{case}.result.json").write_text(json.dumps({
            "schema": "agent-sdk-skills.result/1",
            "case": case,
            "category": "happy",
            "runs": [
                {"run": index, "status": status,
                 "graders": [{"name": "ok", "type": "regex", "status": status}],
                 "result": {"total_cost_usd": 0.02, "num_turns": 3, "subtype": "success"}}
                for index in range(1, runs + 1)
            ],
        }, indent=2))
    (directory / "aggregate.json").write_text(json.dumps({
        "schema": "agent-sdk-skills.aggregate/1",
        "tier": "pr", "started": stamp, "finished": stamp,
        "cases": [{"case": c, "pass_rate": 1.0, "cost": 0.02, "not_evaluated": 0} for c in cases],
        "totals": {"cases": len(cases), "runs": len(cases) * runs,
                   "passed": len(cases) * runs, "failed": 0, "not_evaluated": 0,
                   "cost_usd": 0.04, "cost_basis": "subscription"},
        "exit_code": 0, "runner_version": "0.1.4",
    }, indent=2))
    return directory


TWO_TIER_CONFIG = {
    "schema": "agent-sdk-skills.eval-config/1",
    "runner_version": "0.1.4",
    "agent": "agent:build_options",
    "model": "claude-sonnet-5-5",
    "tiers": {
        "pr": {"graders": ["free"], "runs": 1, "threshold": 1.0},
        "nightly": {"graders": ["free", "judge"], "runs": 3, "threshold": 0.8},
    },
}


# -- gen_workflows ---------------------------------------------------------

def test_a_dry_run_prints_the_plan_and_writes_nothing(run_script, tmp_path):
    project = make_project(tmp_path)
    result = run_script(GEN, project, "--dry-run")
    assert result.returncode == 0, result.combined
    assert "Write plan" in result.stdout
    assert "agent-evals-pr.yml" in result.stdout and "agent-evals-nightly.yml" in result.stdout
    assert not (project / ".github").exists()


def test_writing_both_tiers_lands_two_workflows_with_the_oauth_secret(run_script, tmp_path):
    project = make_project(tmp_path)
    result = run_script(GEN, project, "--tier", "both", "--json")
    assert result.returncode == 0, result.combined
    doc = result.json()
    assert len(doc["written"]) == 2 and doc["secret"] == "CLAUDE_CODE_OAUTH_TOKEN"

    pr = (project / ".github/workflows/agent-evals-pr.yml").read_text()
    nightly = (project / ".github/workflows/agent-evals-nightly.yml").read_text()
    for text in (pr, nightly):
        assert "CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}" in text
        assert "# ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}" in text
        assert "PYTHONPATH: evals/runner:." in text
        assert "continue-on-error: true" in text
        assert "upload-artifact" in text and "path: evals/results/" in text
    assert "--tier pr" in pr and "cancel-in-progress: true" in pr
    assert "--tier nightly" in nightly and "--runs" in nightly
    assert "cancel-in-progress: false" in nightly and "cron:" in nightly


def test_api_key_auth_flips_which_line_is_commented(run_script, tmp_path):
    project = make_project(tmp_path)
    result = run_script(GEN, project, "--tier", "pr", "--auth", "api-key", "--json")
    assert result.returncode == 0 and result.json()["secret"] == "ANTHROPIC_API_KEY"
    text = (project / ".github/workflows/agent-evals-pr.yml").read_text()
    assert "\n          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}" in text
    assert "# CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}" in text


def test_an_existing_workflow_is_skipped_unless_forced(run_script, tmp_path):
    project = make_project(tmp_path)
    run_script(GEN, project, "--tier", "pr")
    target = project / ".github/workflows/agent-evals-pr.yml"
    target.write_text("# hand-edited\n")

    again = run_script(GEN, project, "--tier", "pr", "--json")
    assert [i["action"] for i in again.json()["write_plan"]["items"]] == ["skip"]
    assert target.read_text() == "# hand-edited\n"

    forced = run_script(GEN, project, "--tier", "pr", "--force", "--json")
    assert [i["action"] for i in forced.json()["write_plan"]["items"]] == ["overwrite"]
    assert "Agent evals (pr)" in target.read_text()


def test_no_placeholder_survives_rendering(run_script, tmp_path):
    project = make_project(tmp_path)
    run_script(GEN, project, "--tier", "both", "--pytest-gate", "--readme")
    rendered = list((project / ".github/workflows").glob("*.yml")) + [
        project / "tests/test_evals.py", project / "docs/ci-evals.md"]
    for path in rendered:
        left = UNFILLED.findall(path.read_text())
        assert left == [], f"{path.name} still holds {left}"


def test_a_project_without_cases_or_a_runner_copy_is_generated_with_warnings(run_script, tmp_path):
    project = make_project(tmp_path, cases=(), runner=False)
    result = run_script(GEN, project, "--tier", "pr", "--json")
    assert result.returncode == 1, result.combined
    warnings = " ".join(result.json()["warnings"])
    assert "no eval cases" in warnings and "no runner copy" in warnings


# -- lint_workflows --------------------------------------------------------

def ids_for(result, workflow: str | None = None) -> set[str]:
    findings = result.json()["findings"]
    if workflow is not None:
        findings = [f for f in findings if Path(f.get("path", "")).name == workflow]
    return {f["id"] for f in findings}


def test_the_generated_workflows_lint_clean(run_script, tmp_path):
    project = make_project(tmp_path, config=TWO_TIER_CONFIG)
    run_script(GEN, project, "--tier", "both")
    result = run_script(LINT, project, "--json")
    assert result.returncode == 0, result.stdout
    assert result.json()["findings"] == []


def test_the_good_fixture_workflow_has_no_findings_and_the_bad_one_has_them(run_script, agent_dir):
    project = agent_dir("ci_ready")
    result = run_script(LINT, project, "--json")
    assert ids_for(result, "agent-evals-pr.yml") == set()
    assert ids_for(result, "agent-evals-broken.yml") == {
        "CI010", "CI020", "CI022", "CI030", "CI040", "CI050"}
    assert result.returncode == 1, "a credential literal and a broken PYTHONPATH are errors"


def test_strict_makes_the_warnings_count(run_script, agent_dir):
    project = agent_dir("ci_ready")
    doc = run_script(LINT, project, "--json", "--strict").json()
    assert doc["summary"]["warnings"] == 0 and doc["summary"]["errors"] >= 5


def test_no_workflow_at_all_is_an_error_with_cases_and_a_note_without(run_script, tmp_path):
    with_cases = run_script(LINT, make_project(tmp_path / "a"), "--json")
    assert with_cases.returncode == 1
    assert [f["severity"] for f in with_cases.json()["findings"] if f["id"] == "CI001"] == ["error"]

    without = run_script(LINT, make_project(tmp_path / "b", cases=()), "--json")
    assert without.returncode == 0
    assert [f["severity"] for f in without.json()["findings"] if f["id"] == "CI001"] == ["info"]


def test_judge_graders_in_the_pr_tier_are_flagged_from_the_config(run_script, tmp_path):
    config = json.loads(json.dumps(TWO_TIER_CONFIG))
    config["tiers"]["pr"]["graders"] = ["free", "judge"]
    project = make_project(tmp_path, config=config)
    run_script(GEN, project, "--tier", "pr")
    doc = run_script(LINT, project, "--json").json()
    judge = [f for f in doc["findings"] if f["id"] == "CI011"]
    assert judge and judge[0]["path"].endswith("eval_config.json")


def test_a_per_change_job_running_the_nightly_tier_is_flagged(run_script, tmp_path):
    project = make_project(tmp_path)
    write_workflow(project, "nightly-on-pr.yml", """\
name: evals
on:
  pull_request:
jobs:
  evals:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Evals
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          PYTHONPATH: evals/runner:.
        run: python -m agent_sdk_evals run evals --tier nightly --max-cost-usd 5
      - uses: actions/upload-artifact@v4
        with:
          path: evals/results/
""")
    assert "CI011" in ids_for(run_script(LINT, project, "--json"), "nightly-on-pr.yml")


def test_a_runner_step_with_no_credential_is_an_error(run_script, tmp_path):
    project = make_project(tmp_path)
    write_workflow(project, "bare.yml", """\
name: evals
on:
  pull_request:
jobs:
  evals:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Evals
        env:
          PYTHONPATH: evals/runner:.
        run: python -m agent_sdk_evals run evals --tier pr --max-cost-usd 5
      - uses: actions/upload-artifact@v4
        with:
          path: evals/results/
""")
    result = run_script(LINT, project, "--json")
    assert ids_for(result, "bare.yml") == {"CI021"} and result.returncode == 1


def test_the_action_shape_is_reported_as_non_deterministic(run_script, tmp_path):
    project = make_project(tmp_path)
    write_workflow(project, "claude.yml", """\
name: Claude
on:
  pull_request:
jobs:
  claude:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          prompt: "/agent-sdk:eval-run"
""")
    ids = ids_for(run_script(LINT, project, "--json"))
    assert "CI060" in ids and "CI001" in ids, "an agent deciding what to run is not a gate"


def test_a_credential_literal_in_an_action_input_is_an_error(run_script, tmp_path):
    project = make_project(tmp_path)
    write_workflow(project, "claude.yml", """\
name: Claude
on:
  pull_request:
jobs:
  claude:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: a-literal-value-committed-to-the-repository
""")
    assert "CI020" in ids_for(run_script(LINT, project, "--json"), "claude.yml")


def write_workflow(project: Path, name: str, text: str) -> Path:
    directory = project / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text)
    return path


# -- assess_maturity -------------------------------------------------------

def level_of(run_script, project) -> dict:
    result = run_script(MATURITY, project, "--json")
    assert result.returncode == 0, result.combined
    return result.json()


def test_a_project_with_no_cases_is_l0(run_script, agent_dir):
    doc = level_of(run_script, agent_dir("no_evals"))
    assert doc["level"] == 0 and "eval-create" in doc["next_step"]


def test_cases_that_have_never_run_are_l1(run_script, tmp_path):
    doc = level_of(run_script, make_project(tmp_path))
    assert doc["level"] == 1 and doc["facts"]["cases"] == len(CASES)
    assert "eval-run" in doc["next_step"]


def test_the_good_fixture_sits_at_l1_once_it_has_cases(run_script, agent_dir):
    doc = level_of(run_script, agent_dir("good"))
    if doc["facts"]["cases"] == 0:
        pytest.skip("the `good` fixture has no evals/ yet; another lane owns that file")
    assert doc["level"] == 1, "cases but no results, no workflow and no pytest gate"


def test_one_recorded_run_with_a_runner_copy_is_l2(run_script, tmp_path):
    project = make_project(tmp_path)
    stage_results(project, "20260929T101500")
    doc = level_of(run_script, project)
    assert doc["level"] == 2 and doc["evidence"]["2"]
    assert "gen_workflows.py" in doc["next_step"]


def test_the_ci_ready_fixture_is_l3_although_its_results_are_gitignored(run_script, agent_dir):
    doc = level_of(run_script, agent_dir("ci_ready"))
    assert doc["level"] == 3
    assert doc["facts"]["gating_workflows"] and doc["facts"]["pytest_gate"]
    assert doc["evidence"].get("2") is None
    assert any("gitignored" in note for note in doc["observations"])


def test_a_judged_tier_with_repeated_runs_is_l4(run_script, tmp_agent):
    project = tmp_agent("ci_ready")
    stage_results(project, "20260929T101500", runs=3)
    doc = level_of(run_script, project)
    assert doc["level"] == 4, doc["evidence"]
    assert doc["facts"]["nightly_lists_judge"] and doc["facts"]["max_runs_in_one_dir"] == 3


def test_enough_samples_over_enough_runs_is_l5(run_script, tmp_agent):
    project = tmp_agent("ci_ready")
    for index, stamp in enumerate(("20260927T090000", "20260928T090000", "20260929T090000")):
        stage_results(project, stamp, runs=2, status="PASSED" if index else "FAILED")
    doc = level_of(run_script, project)
    assert doc["level"] == 5, doc["evidence"]
    assert doc["facts"]["max_samples_per_case"] == 6
    assert doc["facts"]["pass_at_1"]["reserve_book"] == pytest.approx(4 / 6, abs=0.01)


def test_the_markdown_report_names_the_level_and_one_next_step(run_script, agent_dir):
    result = run_script(MATURITY, agent_dir("ci_ready"))
    assert result.returncode == 0
    assert "# Evaluation maturity: L3" in result.stdout
    assert "## Next step (towards L4)" in result.stdout
