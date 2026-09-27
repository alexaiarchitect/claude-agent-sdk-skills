"""`/agent-sdk:eval-criteria` scripts.

The promises: the catalog tells you what a grader cannot prove as loudly as
what it can, a generated grader satisfies the same validator that would later
reject it, and a config is checked against the runner copy that will actually
read it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

INFO = "skills/eval-criteria/scripts/grader_info.py"
GEN_GRADER = "skills/eval-criteria/scripts/gen_grader.py"
GEN_CONFIG = "skills/eval-criteria/scripts/gen_config.py"
VALIDATE = "skills/eval-criteria/scripts/validate_config.py"

ALL_TYPES = ("llm", "regex", "tool_used", "tool_order", "file_exists", "trajectory",
             "structured_output", "budget", "hook_event", "final_text", "no_tool", "terminal")


# -- grader_info -----------------------------------------------------------

def test_the_catalog_lists_every_type_with_what_it_cannot_prove(run_script):
    payload = run_script(INFO, "--json").json()
    assert {row["type"] for row in payload["types"]} == set(ALL_TYPES)
    assert all(row["not_proven"] for row in payload["types"])
    assert payload["judge"] == ["llm"], "exactly one type costs a model call"


def test_the_catalog_names_the_tool_shaped_and_result_shaped_types(run_script):
    payload = run_script(INFO, "--json").json()
    assert set(payload["tool_shaped"]) == {"tool_used", "tool_order", "trajectory", "no_tool"}
    assert set(payload["result_shaped"]) == {"budget", "terminal", "structured_output"}


@pytest.mark.parametrize("grader_type", ALL_TYPES)
def test_every_type_can_be_described_on_its_own(run_script, grader_type):
    result = run_script(INFO, "--type", grader_type)
    assert result.returncode == 0
    assert "Does not prove" in result.stdout


def test_an_unknown_type_is_a_usage_error(run_script):
    result = run_script(INFO, "--type", "vibes")
    assert result.returncode == 2
    assert "unknown grader type" in result.stderr


# -- gen_grader ------------------------------------------------------------

@pytest.mark.parametrize("grader_type", ALL_TYPES)
def test_every_generated_grader_has_its_required_fields(run_script, tmp_agent, grader_type):
    from agent_sdk_skills import frontmatter, graders

    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    run_script(GEN_GRADER, case, "--type", grader_type, "--name", f"g_{grader_type}",
               "--tool", "mcp__library__reserve_book",
               "--after", "mcp__library__lookup_book",
               "--pattern", "copies left", "--reference", "copies left",
               "--path", "out/*.json", "--criteria", "the reply names the copies left",
               "--json")
    path = case / "graders" / f"g_{grader_type}.md"
    document = frontmatter.parse(path.read_text())
    findings = graders.validate_grader(document.meta, body=document.body, path=str(path))
    assert [f.id for f in findings] == [], [f.message for f in findings]


def test_a_generated_grader_carries_a_prose_body(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    run_script(GEN_GRADER, case, "--type", "no_tool", "--name", "held_back",
               "--tool", "mcp__library__cancel_reservation", "--json")
    body = (case / "graders" / "held_back.md").read_text()
    assert "does not prove" in body.lower()


def test_a_dry_run_writes_nothing(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    result = run_script(GEN_GRADER, case, "--type", "terminal", "--name", "ends",
                        "--dry-run", "--json")
    assert result.json()["written"] == []
    assert not (case / "graders" / "ends.md").exists()


def test_an_existing_grader_is_skipped_unless_forced(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    target = case / "graders" / "follows_the_path.md"
    before = target.read_text()
    result = run_script(GEN_GRADER, case, "--type", "terminal",
                        "--name", "follows_the_path", "--json")
    assert target.read_text() == before
    assert all(i["action"] == "skip" for i in result.json()["plan"]["items"])


def test_an_llm_grader_gets_a_pass_fail_skeleton_split_from_its_note(run_script, tmp_agent):
    from agent_sdk_skills import rubrics

    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    run_script(GEN_GRADER, case, "--type", "llm", "--name", "names_the_count",
               "--criteria", "the reply states how many copies remain", "--json")
    body = (case / "graders" / "names_the_count.md").read_text().split("---", 2)[2]
    criteria, note = rubrics.split_criteria(body)
    assert criteria.startswith("PASS if") and "FAIL if" in criteria
    assert note, "the reader's note lives below the separator, out of the judge's prompt"
    assert "does not prove" in note.lower()


def test_vague_criteria_are_linted(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    result = run_script(GEN_GRADER, case, "--type", "llm", "--name", "vague",
                        "--criteria", "the answer is mostly good and the agent understood it",
                        "--json")
    payload = result.json()
    assert result.returncode == 1
    kinds = {c.split(":")[0] for c in payload["critiques"]}
    assert {"vague", "unobservable"} <= kinds
    assert all(f["id"] == "EVC050" for f in payload["findings"])


def test_a_sharp_criterion_passes_the_lint(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    result = run_script(GEN_GRADER, case, "--type", "llm", "--name", "sharp",
                        "--criteria", "the reply states how many copies remain after "
                                      "the reservation", "--json")
    assert result.returncode == 0, result.json()["critiques"]


def test_a_placeholder_tool_keeps_the_exit_code_honest(run_script, tmp_agent):
    project = tmp_agent("good")
    case = project / "evals" / "reserve-available"
    result = run_script(GEN_GRADER, case, "--type", "no_tool", "--name", "unfinished", "--json")
    assert result.returncode == 1
    assert result.json()["has_placeholders"] is True


def test_a_directory_that_is_not_a_case_is_a_usage_error(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(GEN_GRADER, project / "evals", "--type", "terminal", "--json")
    assert result.returncode == 2
    assert "no prompt.md" in result.stderr


# -- gen_config ------------------------------------------------------------

def test_the_generated_config_matches_the_contract(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN_CONFIG, project, "--json")
    config = result.json()["config"]
    assert config["schema"] == "agent-sdk-skills.eval-config/1"
    assert config["model"] == "${CLAUDE_MODEL:-claude-sonnet-5-5}"
    assert config["isolation"] == {"setting_sources": [], "strict_mcp_config": True}
    assert config["concurrency"] == 1
    assert set(config["tiers"]) == {"pr", "nightly"}
    assert config["tiers"]["pr"]["graders"] == ["free"], "no judge on the per-PR path"
    assert json.loads((project / "evals" / "eval_config.json").read_text()) == config


def test_a_dry_run_writes_no_config(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN_CONFIG, project, "--dry-run", "--json")
    assert result.json()["written"] == []
    assert not (project / "evals" / "eval_config.json").exists()


def test_the_flags_reach_the_document(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    config = run_script(GEN_CONFIG, project, "--judge-model", "claude-opus-5-5",
                        "--samples", "5", "--pr-threshold", "0.9",
                        "--nightly-runs", "7", "--json").json()["config"]
    assert config["judge"]["model"] == "claude-opus-5-5"
    assert config["judge"]["samples"] == 5
    assert config["tiers"]["pr"]["threshold"] == 0.9
    assert config["tiers"]["nightly"]["runs"] == 7
    assert config["tiers"]["nightly"]["pass_k"] <= 7, "pass_k above runs can never be met"


def test_the_generator_validates_what_it_is_about_to_write(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN_CONFIG, project, "--samples", "0", "--json")
    assert result.returncode == 1
    assert "CFG012" in [f["id"] for f in result.json()["findings"]]


def test_an_existing_config_is_not_replaced(run_script, tmp_agent):
    project = tmp_agent("good")
    before = (project / "evals" / "eval_config.json").read_text()
    run_script(GEN_CONFIG, project, "--json")
    assert (project / "evals" / "eval_config.json").read_text() == before


# -- validate_config -------------------------------------------------------

def test_a_good_config_is_clean(run_script, agent_dir):
    result = run_script(VALIDATE, agent_dir("good"), "--no-cli", "--json")
    assert result.returncode == 0
    severities = {f["severity"] for f in result.json()["findings"]}
    assert severities <= {"info"}


def test_a_broken_config_reports_every_id(run_script, fixtures):
    result = run_script(VALIDATE, fixtures / "eval_configs" / "bad.json", "--no-cli", "--json")
    ids = {f["id"] for f in result.json()["findings"]}
    assert {"CFG003", "CFG011", "CFG030"} <= ids
    assert result.returncode == 1


def test_an_unparseable_config_is_a_usage_error(run_script, fixtures):
    result = run_script(VALIDATE, fixtures / "eval_configs" / "invalid_json.json",
                        "--no-cli", "--json")
    assert result.returncode == 2
    assert "CFG002" in {f["id"] for f in result.json()["findings"]}


def test_a_retiring_judge_model_is_a_warning_not_an_error(run_script, fixtures):
    result = run_script(VALIDATE, fixtures / "eval_configs" / "judge_retiring.json",
                        "--no-cli", "--json")
    findings = {f["id"]: f["severity"] for f in result.json()["findings"]}
    assert findings["CFG010"] == "warn"
    assert result.returncode == 0, "a warning alone does not fail without --strict"


def test_strict_promotes_warnings(run_script, fixtures):
    result = run_script(VALIDATE, fixtures / "eval_configs" / "judge_retiring.json",
                        "--no-cli", "--strict", "--json")
    assert result.returncode == 1


def test_a_stale_runner_copy_produces_cfg050_and_dep001(run_script, agent_dir):
    result = run_script(VALIDATE, agent_dir("stale_runner"), "--no-cli", "--json")
    ids = {f["id"] for f in result.json()["findings"]}
    assert "CFG050" in ids, "the config declares a runner this plugin does not ship"
    assert "DEP001" in ids, "and the copy itself is behind"


def test_a_missing_isolation_block_is_reported(run_script, fixtures):
    result = run_script(VALIDATE, fixtures / "eval_configs" / "no_isolation.json",
                        "--no-cli", "--json")
    assert "CFG042" in {f["id"] for f in result.json()["findings"]}


def test_a_missing_target_is_a_usage_error(run_script, tmp_path: Path):
    result = run_script(VALIDATE, tmp_path / "nowhere", "--no-cli", "--json")
    assert result.returncode == 2
