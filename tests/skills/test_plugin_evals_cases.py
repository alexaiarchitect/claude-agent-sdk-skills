"""The `claude plugin eval` suite under `plugin-evals/`: scaffolding and rubrics.

A rubric is only honest if everything it demands by name is something the
plugin's scripts actually print for that case's fixture, and something a reply
that follows the SKILL.md would contain. These tests pin the parts of that which
can be checked without spending a judge call: the scaffold's staging contract,
the per-case wrappers that depend on it, and the rubric clauses the 2026-10-13
live run had to add after a judge voted FAIL 3/3 on nine cases.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from agent_sdk_skills import RUNNER_VERSION

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
EVALS = PLUGIN_ROOT / "plugin-evals"
SCAFFOLD = EVALS / "scaffold.sh"
RESULT_FIXTURES = sorted(p.name for p in (PLUGIN_ROOT / "tests" / "fixtures" / "results").iterdir() if p.is_dir())
CASES = sorted(p for p in EVALS.iterdir() if p.is_dir() and (p / "case.yaml").is_file())


def rubric(case: str) -> str:
    return (EVALS / case / "graders" / "criteria.md").read_text(encoding="utf-8")


def scaffold_args(case: str) -> str:
    """The arguments the per-case wrapper passes to the shared scaffold."""
    text = (EVALS / case / "scaffold.sh").read_text(encoding="utf-8")
    line = [l for l in text.splitlines() if "../scaffold.sh" in l][-1]
    return line.split("../scaffold.sh", 1)[1].strip().lstrip('"').strip()


def run_scaffold(workdir: Path, *args: str) -> subprocess.CompletedProcess:
    workdir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(["bash", str(SCAFFOLD), *args], cwd=workdir,
                          capture_output=True, text=True)


# -- the staging selector -------------------------------------------------

def test_stage_results_with_no_selector_still_stages_everything(tmp_path):
    """The selector is additive: the old spelling has to keep its old meaning."""
    assert run_scaffold(tmp_path, "none", "stage-results").returncode == 0
    staged = sorted(p.name for p in (tmp_path / "fixtures" / "results").iterdir())
    assert staged == RESULT_FIXTURES


def test_stage_results_takes_a_selector_naming_the_run_directories(tmp_path):
    """Four directories with identical timestamps make "the last run" a coin toss.

    A case that asks about one run has to say which, or `summarize_results.py`
    picks arbitrarily and `pass_at_k.py` pools unrelated series.
    """
    done = run_scaffold(tmp_path, "none", "stage-results=failure_only,import_failed")
    assert done.returncode == 0
    staged = sorted(p.name for p in (tmp_path / "fixtures" / "results").iterdir())
    assert staged == ["failure_only", "import_failed"]
    assert "results(failure_only,import_failed)" in (tmp_path / ".scaffold" / "manifest.txt").read_text()


def test_an_unknown_results_fixture_is_a_usage_error(tmp_path):
    done = run_scaffold(tmp_path, "none", "stage-results=no_such_run")
    assert done.returncode == 2 and "no such results fixture" in done.stderr


@pytest.mark.parametrize("case,expected", [
    ("analyze-results", {"failure_only", "not_evaluated"}),
    ("pass-at-k", {"series_5run"}),
])
def test_the_two_results_cases_each_stage_the_runs_their_prompt_describes(case, expected, tmp_path):
    """`analyze-results` needs a failure and a never-evaluated run; `pass-at-k`
    needs one series of repeats and nothing else to pool with it."""
    args = scaffold_args(case)
    assert "stage-results=" in args, f"{case} must name the runs it stages"
    assert run_scaffold(tmp_path, *args.split()).returncode == 0
    assert {p.name for p in (tmp_path / "fixtures" / "results").iterdir()} == expected


def test_the_pass_at_k_prompt_no_longer_implies_several_result_directories():
    """The scaffold stages one; a prompt that says "directories" invites pooling."""
    prompt = (EVALS / "pass-at-k" / "prompt.md").read_text(encoding="utf-8")
    assert "result directories" not in prompt


def test_the_analyze_results_prompt_says_there_are_two_runs():
    prompt = (EVALS / "analyze-results" / "prompt.md").read_text(encoding="utf-8")
    assert "two eval runs" in prompt and "never produced a verdict" in prompt


# -- rubric clauses the live run required ---------------------------------

def test_runner_stale_accepts_either_id_the_scripts_print_for_the_mismatch():
    """`DEP001` from `check_runner.py`/`discover.py`, `CFG050` from
    `validate_cases.py`. Demanding only the first failed a reply that had run
    the validator and reported what it printed."""
    text = rubric("runner-stale")
    assert "DEP001" in text and "CFG050" in text
    assert "0.0.1" in text and RUNNER_VERSION in text, "both version strings"
    assert "result schema" in text, "the risk in the validator's own words"


def test_pass_at_k_separates_the_single_run_rate_from_pass_at_k_without_predicting_production():
    text = rubric("pass-at-k")
    assert "production" not in text, "a rubric cannot demand a claim about production"
    assert "pass@1" in text and "pass@k" in text


def test_analyze_results_asks_for_the_quadrant_label_the_script_prints():
    text = rubric("analyze-results")
    assert "`Q4`" in text, "the fixture's own quadrant, not an abstract 'quadrant'"
    assert "estimate" in text and "subscription" in text


def test_create_edge_cases_accepts_a_fully_covered_matrix():
    """`coverage_matrix.py` reports 4/4 on the `good` fixture, so a rubric that
    demands uncovered rules by name is unsatisfiable."""
    text = rubric("create-edge-cases")
    assert "4/4" in text or "rule_coverage" in text
    assert "thinnest" in text, "name the rules with the fewest cases instead"
    assert "Unfiltered" in text or "unfiltered" in text, "the validator's whole report"


@pytest.mark.parametrize("case", ["ci-setup", "create-edge-cases", "simulation"])
def test_the_pre_approved_write_cases_accept_the_generators_own_plan(case):
    """Their prompts pre-approve writing, so the agents skipped `--dry-run` and
    the judge failed "write plan shown before writing". The generator prints the
    same `## Write plan` block either way, and that is what the rubric reads."""
    text = rubric(case)
    assert "## Write plan" in text
    assert "--dry-run" in text and "pre-approve" in text


@pytest.mark.parametrize("case", ["criteria-choice", "run-dry-run", "simulation", "ci-setup"])
def test_the_subscription_cases_accept_a_sandbox_with_no_credential(case):
    """Their prompts say "on my subscription" while the sandbox has no
    credential, so the honest answer is the script's `none found` plus the
    prompt's premise, and never a script-reported subscription."""
    text = rubric(case)
    assert "none found" in text or "no credential" in text
    assert "estimate" in text


def test_criteria_choice_asks_for_the_catalogs_does_not_prove_column():
    text = rubric("criteria-choice")
    assert "does not prove" in text
    assert "grader_info.py" in text and "crosscheck_tools.py" in text
    assert "IN_ORDER" in text and "no_tool" in text and "EXACT" in text


def test_run_dry_run_asks_for_the_arithmetic_the_dry_run_now_prints():
    text = rubric("run-dry-run")
    assert "sessions_total" in text
    assert "unverified" in text
    assert "does not have to end with a question" in text, "the old closing demand is dropped"


def test_harness_hooks_keeps_its_ids_and_explains_where_each_item_comes_from():
    text = rubric("harness-hooks")
    for finding_id in ("HOK001", "HOK002", "HOK020"):
        assert finding_id in text
    assert "gen_hook.py" in text and "Source:" in text


def test_the_simulation_case_has_room_for_the_work_its_skill_asks_for():
    """It ran out of turns mid-answer on 2026-10-13 and produced no reply at all.

    The skill now asks for the generators' plans, unfiltered validator output
    and a wiring step, which is more tool calls than `max_turns: 14` allowed.
    """
    prompt = (EVALS / "simulation" / "prompt.md").read_text(encoding="utf-8")
    turns = int(re.search(r"max_turns:\s*(\d+)", prompt).group(1))
    assert turns >= 18, "a truncated run cannot satisfy any rubric"


# -- rules that hold for every case --------------------------------------

@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_every_case_scaffold_delegates_to_the_shared_script(case):
    assert "../scaffold.sh" in (case / "scaffold.sh").read_text(encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_no_rubric_demands_a_pre_write_confirmation_its_prompt_waived(case):
    """A prompt that says "do not wait for confirmation" cannot be graded on one."""
    prompt = (case / "prompt.md").read_text(encoding="utf-8")
    if "do not wait for confirmation" not in prompt:
        return
    text = rubric(case.name)
    assert "pre-approve" in text, "say that pre-approval skips the confirmation, not the dry run"
