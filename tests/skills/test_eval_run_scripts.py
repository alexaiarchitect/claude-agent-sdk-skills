"""eval-run wraps the project's runner copy and gates on the result directory."""

import json
from pathlib import Path


def make_project(tmp_path: Path, *, runner_version="0.1.2", cases=("a", "b")) -> Path:
    project = tmp_path / "proj"
    (project / "evals").mkdir(parents=True)
    (project / "agent.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\ndef build_options():\n    return ClaudeAgentOptions()\n")
    for case in cases:
        (project / "evals" / case / "graders").mkdir(parents=True)
        (project / "evals" / case / "prompt.md").write_text("---\ncategory: happy\n---\nhi")
        (project / "evals" / case / "graders" / "ok.md").write_text("---\ntype: regex\npattern: .\n---\n")
    if runner_version:
        package = project / "evals" / "runner" / "agent_sdk_evals"
        package.mkdir(parents=True)
        (package / "VERSION").write_text(runner_version + "\n")
        (package / "__init__.py").write_text("")
    return project


def test_dry_run_prints_the_command_and_starts_nothing(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    result = run_script("skills/eval-run/scripts/run_evals.py", project, "--dry-run", "--json", "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    assert result.returncode == 0, result.stderr
    doc = result.json()
    assert doc["dry_run"] and "agent_sdk_evals run evals --tier pr" in doc["command"]
    assert doc["cost_basis"] == "subscription"
    assert not (project / "evals" / "results").exists()


def pin_runs(project: Path, case: str, runs: int) -> None:
    path = project / "evals" / case / "prompt.md"
    path.write_text(path.read_text().replace("category:", f"runs: {runs}\ncategory:", 1))


def write_config(project: Path, tier_runs: int = 1) -> None:
    (project / "evals" / "eval_config.json").write_text(json.dumps({
        "schema": "agent-sdk-skills.eval-config/1", "agent": "agent:build_options",
        "tiers": {"pr": {"graders": ["free"], "runs": tier_runs, "threshold": 1.0}},
    }))


def test_a_dry_run_counts_sessions_including_the_runs_a_case_pinned(run_script, tmp_path, fake_sdk):
    """`cases` alone under-counts: a case's own `runs:` outranks the tier's.

    Two cases, a `pr` tier at `runs: 1`, one case pinning `runs: 3` — the run
    starts four sessions, not two, and the dry run has to say four or the cost
    estimate built on it is wrong.
    """
    project = make_project(tmp_path)
    write_config(project)
    pin_runs(project, "a", 3)
    result = run_script("skills/eval-run/scripts/run_evals.py", project, "--dry-run", "--json",
                        "--no-cli", env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    doc = result.json()
    assert doc["cases"] == 2
    assert doc["sessions_total"] == 4, doc
    assert doc["runs_per_case"]["a"] == {"runs": 3, "runs_source": "case", "tier_runs": 1}
    assert doc["runs_per_case"]["b"] == {"runs": 1, "runs_source": "tier", "tier_runs": 1}

    prose = run_script("skills/eval-run/scripts/run_evals.py", project, "--dry-run", "--no-cli",
                       env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    assert "- sessions_total: 4 (1 case(s) pin runs: 3)" in prose.stdout, prose.stdout


def test_the_runs_flag_decides_every_case_in_the_dry_run(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    write_config(project)
    pin_runs(project, "a", 3)
    doc = run_script("skills/eval-run/scripts/run_evals.py", project, "--dry-run", "--json",
                     "--no-cli", "--runs", "2",
                     env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"}).json()
    assert doc["sessions_total"] == 4
    assert {c["runs_source"] for c in doc["runs_per_case"].values()} == {"cli"}


def test_a_case_filter_only_counts_the_sessions_it_leaves(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    write_config(project)
    pin_runs(project, "a", 3)
    doc = run_script("skills/eval-run/scripts/run_evals.py", project, "--dry-run", "--json",
                     "--no-cli", "--case", "b",
                     env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"}).json()
    assert doc["sessions_total"] == 1 and list(doc["runs_per_case"]) == ["b"]


def test_missing_runner_copy_is_refused_before_anything_runs(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path, runner_version=None)
    result = run_script("skills/eval-run/scripts/run_evals.py", project, "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    assert result.returncode == 2 and "DEP003" in result.stderr


def test_a_failed_case_exits_one_even_though_the_runner_wrote_files(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    result = run_script("skills/eval-run/scripts/run_evals.py", project, "--json", "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok", "FAKE_SDK_PASSED": "1", "FAKE_SDK_FAILED": "1"})
    doc = result.json()
    assert result.returncode == 1, doc
    assert doc["status_counts"]["FAILED"] == 1 and doc["status_counts"]["PASSED"] == 1
    assert Path(doc["results_dir"]).is_dir()


def test_never_evaluated_is_inconclusive_by_default_and_a_failure_in_ci_mode(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "FAKE_SDK_PASSED": "1", "FAKE_SDK_NOT_EVALUATED": "1"}
    warn = run_script("skills/eval-run/scripts/run_evals.py", project, "--no-cli", env=env)
    assert warn.returncode == 3, warn.combined
    fail = run_script("skills/eval-run/scripts/run_evals.py", project, "--no-cli", "--not-evaluated", "fail", env=env)
    assert fail.returncode == 1


def test_a_rejected_usage_limit_is_inconclusive(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    result = run_script("skills/eval-run/scripts/run_evals.py", project, "--json", "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok", "FAKE_SDK_USAGE_LIMIT": "1"})
    doc = result.json()
    assert result.returncode == 3 and doc["stopped"]["reason"] == "rate_limit_rejected"


def test_an_import_failure_is_an_environment_error(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    result = run_script("skills/eval-run/scripts/run_evals.py", project, "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok", "FAKE_SDK_IMPORT_ERROR": "1"})
    assert result.returncode == 2


def test_no_credential_blocks_a_real_run_but_not_a_dry_run(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    real = run_script("skills/eval-run/scripts/run_evals.py", project, "--no-cli")
    assert real.returncode == 2 and "setup-token" in real.stderr
    dry = run_script("skills/eval-run/scripts/run_evals.py", project, "--no-cli", "--dry-run", "--json")
    assert dry.returncode == 0 and any("no credential" in w for w in dry.json()["warnings"])


def test_check_runner_reports_versions(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path, runner_version="0.0.1")
    result = run_script("skills/eval-run/scripts/check_runner.py", project, "--json")
    doc = result.json()
    assert result.returncode == 1 and [f["id"] for f in doc["findings"]] == ["DEP001"]
    assert doc["reported"]["runner_version"]
    missing = run_script("skills/eval-run/scripts/check_runner.py", make_project(tmp_path / "m", runner_version=None), "--json")
    assert missing.returncode == 2


def test_replay_needs_a_runner_copy_and_a_trace(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    trace = tmp_path / "x.trace.jsonl"
    trace.write_text('{"type": "init"}\n')
    result = run_script("skills/eval-run/scripts/replay_trace.py", project, trace, "--json")
    assert result.returncode in (0, 1, 3), result.stderr
    bad = run_script("skills/eval-run/scripts/replay_trace.py", project, tmp_path / "missing.jsonl")
    assert bad.returncode == 2


def test_a_backend_error_mid_suite_is_an_environment_error(run_script, tmp_path, fake_sdk):
    project = make_project(tmp_path)
    result = run_script("skills/eval-run/scripts/run_evals.py", project, "--json", "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok", "FAKE_SDK_BACKEND_ERROR": "1"})
    assert result.returncode == 2 and result.json()["stopped"]["reason"] == "backend_error"
