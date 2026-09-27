"""`/agent-sdk:agent-create` scripts, run the way a skill runs them.

Three promises are under test: the readiness check tells the truth about a
project it did not write, nothing is written before a plan has been shown, and
an installed runner copy is never replaced by accident.
"""

from __future__ import annotations

import json
from pathlib import Path

READINESS = "skills/agent-create/scripts/readiness.py"
SCAFFOLD = "skills/agent-create/scripts/eval_scaffold.py"
INSTALL = "skills/agent-create/scripts/install_runner.py"
CHECK_RUNNER = "skills/eval-run/scripts/check_runner.py"


# -- readiness -------------------------------------------------------------

def test_a_ready_project_reports_its_entry_point(run_script, agent_dir):
    result = run_script(READINESS, agent_dir("good"), "--json", "--no-cli", "--no-probe")
    payload = result.json()
    assert payload["discovered"]["entry_point"] == "agent:build_options"
    assert payload["discovered"]["style"] == "convention"
    assert payload["discovered"]["evals"]["cases"] == 5


def test_a_project_with_no_agent_exits_two(run_script, agent_dir, tmp_path: Path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    result = run_script(READINESS, empty, "--no-cli", "--no-probe")
    assert result.returncode == 2, result.combined
    assert "AGT001" in result.stdout


def test_options_built_inline_are_reported_as_not_injectable(run_script, agent_dir):
    result = run_script(READINESS, agent_dir("inline_main"), "--json", "--no-cli", "--no-probe")
    ids = [f["id"] for f in result.json()["findings"]]
    assert "AGT003" in ids, "options inside main() cannot be obtained by a runner"


def test_a_project_without_a_runner_copy_reports_dep003(run_script, agent_dir):
    result = run_script(READINESS, agent_dir("no_evals"), "--json", "--no-cli", "--no-probe")
    payload = result.json()
    assert "DEP003" in [f["id"] for f in payload["findings"]]
    assert result.returncode == 1


def test_readiness_reports_whether_the_dev_plugin_is_installed(run_script, agent_dir):
    result = run_script(READINESS, agent_dir("good"), "--json", "--no-cli", "--no-probe")
    reported = result.json()["discovered"]["agent_sdk_dev_plugin"]
    assert reported in ("installed", "not installed")


def test_a_missing_env_example_is_a_finding(run_script, tmp_agent):
    project = tmp_agent("good")
    (project / ".env.example").unlink()
    result = run_script(READINESS, project, "--json", "--no-cli", "--no-probe")
    assert "AGT021" in [f["id"] for f in result.json()["findings"]]


def test_an_untracked_env_file_is_an_error(run_script, tmp_agent):
    project = tmp_agent("good")
    (project / ".env").write_text("CLAUDE_MODEL=x\n", encoding="utf-8")
    (project / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    result = run_script(READINESS, project, "--json", "--no-cli", "--no-probe")
    ids = [f["id"] for f in result.json()["findings"]]
    assert "ENV020" in ids


# -- eval_scaffold ---------------------------------------------------------

def test_a_dry_run_writes_nothing(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    before = sorted(p.name for p in project.rglob("*"))
    result = run_script(SCAFFOLD, project, "--dry-run", "--json")
    payload = result.json()
    assert payload["dry_run"] and payload["written"] == []
    assert payload["plan"]["will_write"], "the plan still says what it would do"
    assert sorted(p.name for p in project.rglob("*")) == before


def test_the_scaffold_writes_the_config_a_case_and_the_gate(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    run_script(SCAFFOLD, project, "--json")
    config = json.loads((project / "evals" / "eval_config.json").read_text())
    assert config["schema"] == "agent-sdk-skills.eval-config/1"
    assert config["isolation"] == {"setting_sources": [], "strict_mcp_config": True}
    assert (project / "evals" / "smoke" / "prompt.md").is_file()
    assert (project / "evals" / "mocks" / "README.md").is_file()
    assert (project / "tests" / "test_evals.py").is_file()


def test_the_starter_case_carries_two_free_graders_that_parse(run_script, tmp_agent):
    from agent_sdk_skills import evalcase

    project = tmp_agent("no_evals")
    run_script(SCAFFOLD, project, "--json")
    cases = list(evalcase.iter_cases(project / "evals"))
    assert [c.name for c in cases] == ["smoke"]
    assert sorted(cases[0].grader_types) == ["regex", "terminal"]
    assert evalcase.validate_case(cases[0]) == [], "the generated case validates clean"


def test_the_model_is_env_driven_unless_asked_otherwise(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    run_script(SCAFFOLD, project, "--json")
    config = json.loads((project / "evals" / "eval_config.json").read_text())
    assert config["model"] == "${CLAUDE_MODEL:-claude-sonnet-5-5}"


def test_an_explicit_model_is_written_literally(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    run_script(SCAFFOLD, project, "--model", "claude-opus-5-5", "--json")
    config = json.loads((project / "evals" / "eval_config.json").read_text())
    assert config["model"] == "claude-opus-5-5"


def test_an_existing_gitignore_is_merged_not_replaced(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    (project / ".gitignore").write_text("# mine\nbuild/\n", encoding="utf-8")
    result = run_script(SCAFFOLD, project, "--json")
    actions = {Path(i["path"]).name: i["action"] for i in result.json()["plan"]["items"]}
    assert actions[".gitignore"] == "merge"
    text = (project / ".gitignore").read_text()
    assert "build/" in text and ".env" in text and "evals/results/" in text


def test_a_gitignore_that_already_covers_both_is_left_alone(run_script, tmp_agent):
    project = tmp_agent("good")
    before = (project / ".gitignore").read_text()
    run_script(SCAFFOLD, project, "--json")
    assert (project / ".gitignore").read_text() == before


def test_existing_files_are_skipped_without_force(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(SCAFFOLD, project, "--json")
    actions = {Path(i["path"]).name: i["action"] for i in result.json()["plan"]["items"]}
    assert actions["eval_config.json"] == "skip"
    assert result.returncode == 1, "a skip is a warning, not silence"


def test_force_replaces_them(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(SCAFFOLD, project, "--force", "--json")
    actions = {Path(i["path"]).name: i["action"] for i in result.json()["plan"]["items"]}
    assert actions["eval_config.json"] == "overwrite"


def test_scaffolding_a_project_with_no_agent_warns(run_script, tmp_path: Path):
    project = tmp_path / "bare"
    project.mkdir()
    result = run_script(SCAFFOLD, project, "--json")
    assert any("no agent module" in w for w in result.json()["warnings"])


# -- install_runner --------------------------------------------------------

def test_installing_the_runner_then_checking_it_reports_same(run_script, tmp_agent):
    project = tmp_agent("good")
    installed = run_script(INSTALL, project, "--json")
    assert installed.returncode == 0, installed.combined
    package = project / "evals" / "runner" / "agent_sdk_evals"
    assert (package / "VERSION").is_file()
    assert (package / "MANIFEST.sha256").is_file()

    checked = run_script(CHECK_RUNNER, project, "--json", "--no-probe")
    assert checked.returncode == 0, checked.combined
    assert checked.json()["copy"]["status"] == "same"


def test_no_pycache_is_copied(run_script, tmp_agent):
    project = tmp_agent("good")
    run_script(INSTALL, project, "--json")
    package = project / "evals" / "runner" / "agent_sdk_evals"
    assert not list(package.rglob("__pycache__"))


def test_a_dry_run_installs_nothing(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(INSTALL, project, "--dry-run", "--json")
    assert result.json()["dry_run"] and result.json()["written"] == 0
    assert not (project / "evals" / "runner").exists()


def test_an_existing_copy_is_refused_without_upgrade(run_script, tmp_agent):
    project = tmp_agent("good")
    run_script(INSTALL, project, "--json")
    again = run_script(INSTALL, project, "--json")
    assert again.returncode == 1
    assert again.json()["refused"] is True


def test_upgrade_names_the_local_edits_it_would_replace(run_script, tmp_agent):
    project = tmp_agent("good")
    run_script(INSTALL, project, "--json")
    edited = project / "evals" / "runner" / "agent_sdk_evals" / "cli.py"
    edited.write_text(edited.read_text() + "\n# local change\n", encoding="utf-8")

    planned = run_script(INSTALL, project, "--upgrade", "--dry-run", "--json")
    payload = planned.json()
    assert "cli.py" in payload["would_overwrite_local_edits"]
    assert "cli.py" in payload["files"]["changed"]
    assert edited.read_text().endswith("# local change\n"), "a dry run changes nothing"


def test_a_stale_copy_is_reported_as_older(run_script, agent_dir):
    result = run_script(CHECK_RUNNER, agent_dir("stale_runner"), "--json", "--no-probe")
    assert result.json()["copy"]["version"] == "0.0.1"
    assert "DEP001" in [f["id"] for f in result.json()["findings"]]


def test_upgrading_a_stale_copy_brings_it_to_the_plugin_version(run_script, tmp_agent):
    from agent_sdk_skills import RUNNER_VERSION

    project = tmp_agent("stale_runner")
    result = run_script(INSTALL, project, "--upgrade", "--json")
    assert result.returncode == 0, result.combined
    version = (project / "evals" / "runner" / "agent_sdk_evals" / "VERSION")
    assert version.read_text().strip() == RUNNER_VERSION


def test_a_missing_project_is_a_usage_error(run_script, tmp_path: Path):
    for script in (READINESS, SCAFFOLD, INSTALL):
        result = run_script(script, tmp_path / "nope", "--json")
        assert result.returncode == 2, f"{script}: {result.combined}"
