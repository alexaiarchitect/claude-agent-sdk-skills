"""`/agent-sdk:eval-create` scripts.

What is worth defending here: a generated case validates clean against the same
validator `/agent-sdk:eval-review` runs, a frozen trace never includes the
CLI's synthetic calls, and the three destructive operations refuse to run on
their own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

GEN = "skills/eval-create/scripts/gen_cases.py"
FREEZE = "skills/eval-create/scripts/trace_to_case.py"
MANAGE = "skills/eval-create/scripts/manage_cases.py"

TOOL = "mcp__library__reserve_book"
OTHER_TOOL = "mcp__library__lookup_book"
AGENT_TOOLS = {TOOL, OTHER_TOOL, "mcp__library__cancel_reservation"}


def _cases(evals: Path):
    from agent_sdk_skills import evalcase

    return {case.name: case for case in evalcase.iter_cases(evals)}


# -- gen_cases -------------------------------------------------------------

@pytest.mark.parametrize("category,expected", [
    ("happy", {"trajectory", "terminal"}),
    ("edge", {"terminal", "llm"}),
    ("adversarial", {"no_tool", "llm"}),
    ("memory", {"tool_order"}),
    ("regression", {"terminal", "regex"}),
])
def test_each_category_gets_the_graders_it_needs(run_script, tmp_agent, category, expected):
    project = tmp_agent("no_evals")
    result = run_script(GEN, project, "--category", category, "--tool", TOOL,
                        "--name", f"c-{category}", "--rule", "reserve a title on request",
                        "--json")
    assert result.json()["case"] == f"c-{category}"
    case = _cases(project / "evals")[f"c-{category}"]
    assert set(case.grader_types) == expected


def test_a_generated_case_validates_clean(run_script, tmp_agent):
    from agent_sdk_skills import evalcase

    project = tmp_agent("good")
    run_script(GEN, project, "--category", "adversarial", "--tool", TOOL,
               "--name", "no-second-copy", "--rule",
               "never reserve a title the member already holds", "--json")
    case = _cases(project / "evals")["no-second-copy"]
    findings = evalcase.validate_case(case, agent_tools=AGENT_TOOLS)
    assert findings == [], [f.message for f in findings]


def test_a_dry_run_writes_nothing(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN, project, "--category", "happy", "--tool", TOOL,
                        "--name", "planned", "--dry-run", "--json")
    assert result.json()["written"] == []
    assert not (project / "evals" / "planned").exists()


def test_a_real_run_writes_the_case(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN, project, "--category", "happy", "--tool", TOOL,
                        "--name", "written", "--json")
    assert len(result.json()["written"]) == 3
    assert (project / "evals" / "written" / "prompt.md").is_file()


def test_an_existing_case_is_skipped_unless_forced(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    run_script(GEN, project, "--category", "happy", "--tool", TOOL, "--name", "twice", "--json")
    prompt = project / "evals" / "twice" / "prompt.md"
    prompt.write_text(prompt.read_text() + "\nedited by hand\n", encoding="utf-8")

    again = run_script(GEN, project, "--category", "happy", "--tool", TOOL,
                       "--name", "twice", "--json")
    assert again.returncode == 1
    assert "edited by hand" in prompt.read_text()

    forced = run_script(GEN, project, "--category", "happy", "--tool", TOOL,
                        "--name", "twice", "--force", "--json")
    assert all(i["action"] == "overwrite" for i in forced.json()["plan"]["items"])
    assert "edited by hand" not in prompt.read_text()


def test_a_case_with_no_tool_warns_about_its_placeholder(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN, project, "--category", "adversarial", "--name", "placeholder",
                        "--rule", "never do the thing", "--json")
    assert result.returncode == 1
    assert any("TODO-tool" in w for w in result.json()["warnings"])


def test_a_refusal_rule_in_a_non_adversarial_category_is_flagged(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN, project, "--category", "happy", "--tool", TOOL,
                        "--name", "mismatched", "--rule", "never reserve a sealed title",
                        "--json")
    assert any("adversarial" in w for w in result.json()["warnings"])


def test_a_multi_turn_case_has_turns_and_no_body(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    run_script(GEN, project, "--category", "memory", "--tool", TOOL, "--name", "two-turn", "--json")
    case = _cases(project / "evals")["two-turn"]
    assert len(case.turns) == 2
    assert case.body.strip() == "", "a body would be silently ignored (EVC002)"


def test_an_adversarial_case_repeats_more_than_the_others(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    run_script(GEN, project, "--category", "adversarial", "--tool", TOOL,
               "--name", "restraint", "--rule", "never release a sealed document", "--json")
    assert _cases(project / "evals")["restraint"].meta["runs"] == 5


def test_every_generated_grader_carries_a_prose_body(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    run_script(GEN, project, "--category", "happy", "--tool", TOOL, "--name", "prose", "--json")
    for grader in _cases(project / "evals")["prose"].graders:
        assert len(grader.body.split()) > 20, f"{grader.name} has no argument in it"


def test_an_unknown_category_is_a_usage_error(run_script, tmp_agent):
    project = tmp_agent("no_evals")
    result = run_script(GEN, project, "--category", "vibes", "--json")
    assert result.returncode == 2


# -- trace_to_case ---------------------------------------------------------

def test_a_happy_trace_becomes_a_trajectory_and_a_terminal_grader(run_script, tmp_agent, fixtures):
    project = tmp_agent("no_evals")
    trace = fixtures / "traces" / "happy.trace.jsonl"
    result = run_script(FREEZE, trace, "--name", "golden", "--project", project, "--json")
    assert result.returncode == 0, result.combined
    payload = result.json()
    assert [c["tool"] for c in payload["calls"]] == [OTHER_TOOL, TOOL]
    assert payload["terminal_subtype"] == "success"

    case = _cases(project / "evals")["golden"]
    assert sorted(case.grader_types) == ["terminal", "trajectory"]
    assert case.body.strip() == "Reserve 'Dune' for member-42."


def test_the_frozen_trajectory_carries_the_arguments_the_run_sent(run_script, tmp_agent, fixtures):
    from agent_sdk_skills import frontmatter

    project = tmp_agent("no_evals")
    run_script(FREEZE, fixtures / "traces" / "happy.trace.jsonl",
               "--name", "golden", "--project", project, "--json")
    grader = (project / "evals" / "golden" / "graders" / "follows_the_golden_path.md")
    meta = frontmatter.parse(grader.read_text()).meta
    assert meta["match"] == "IN_ORDER" and meta["args_match"] == "subset"
    assert meta["expected"][1]["args"] == {"title": "Dune", "member_id": "member-42"}


def test_synthetic_calls_never_reach_the_expectation(run_script, tmp_agent, fixtures):
    project = tmp_agent("no_evals")
    result = run_script(FREEZE, fixtures / "traces" / "structured_output.trace.jsonl",
                        "--name", "structured", "--project", project, "--json")
    payload = result.json()
    assert payload["dropped_synthetic"] >= 1
    assert "StructuredOutput" not in json.dumps(payload["calls"])
    assert result.returncode == 1, "a trajectory that expects nothing is worth a warning"


def test_an_existing_case_is_never_overwritten_from_a_trace(run_script, tmp_agent, fixtures):
    project = tmp_agent("good")
    prompt = project / "evals" / "reserve-available" / "prompt.md"
    before = prompt.read_text()
    result = run_script(FREEZE, fixtures / "traces" / "happy.trace.jsonl",
                        "--name", "reserve-available", "--project", project, "--json")
    assert result.returncode == 1
    assert all(i["action"] == "skip" for i in result.json()["plan"]["items"])
    assert prompt.read_text() == before


def test_exact_over_a_long_path_is_called_brittle(run_script, tmp_agent, fixtures, tmp_path: Path):
    project = tmp_agent("no_evals")
    source = (fixtures / "traces" / "happy.trace.jsonl").read_text().splitlines()
    tool_line = next(line for line in source if '"type": "tool_use"' in line)
    long_trace = tmp_path / "long.trace.jsonl"
    long_trace.write_text("\n".join(source + [tool_line] * 6) + "\n", encoding="utf-8")

    result = run_script(FREEZE, long_trace, "--name", "brittle", "--project", project,
                        "--match", "EXACT", "--json")
    assert any("brittle" in w for w in result.json()["warnings"])


def test_a_missing_trace_is_a_usage_error(run_script, tmp_agent, tmp_path: Path):
    result = run_script(FREEZE, tmp_path / "nope.jsonl", "--name", "x",
                        "--project", tmp_agent("no_evals"), "--json")
    assert result.returncode == 2


# -- manage_cases ----------------------------------------------------------

def test_list_reports_every_case_with_its_tier(run_script, agent_dir):
    result = run_script(MANAGE, agent_dir("good"), "list", "--json")
    payload = result.json()
    assert payload["count"] == 5
    tiers = {row["name"]: row["tier"] for row in payload["cases"]}
    assert tiers["refuse-double-booking"] == "judge", "it has an llm grader"
    assert tiers["reserve-available"] == "free"


def test_rename_refuses_without_yes(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(MANAGE, project, "rename", "--from", "unknown-title",
                        "--to", "unknown-title-v2", "--json")
    assert result.returncode == 1
    assert "refused" in result.json()
    assert (project / "evals" / "unknown-title").is_dir()


def test_rename_moves_the_directory_and_the_frontmatter_name(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(MANAGE, project, "rename", "--from", "unknown-title",
                        "--to", "unknown-title-v2", "--yes", "--json")
    assert result.returncode == 0, result.combined
    assert not (project / "evals" / "unknown-title").exists()
    case = _cases(project / "evals")["unknown-title-v2"]
    assert case.meta["name"] == "unknown-title-v2", "results are keyed by name, not directory"


def test_rename_refuses_an_unusable_directory_name(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(MANAGE, project, "rename", "--from", "unknown-title",
                        "--to", "Unknown Title", "--yes", "--json")
    assert result.returncode == 2


def test_delete_refuses_without_yes_then_removes(run_script, tmp_agent):
    project = tmp_agent("good")
    refused = run_script(MANAGE, project, "delete", "--from", "unknown-title", "--json")
    assert refused.returncode == 1
    assert (project / "evals" / "unknown-title").is_dir()

    done = run_script(MANAGE, project, "delete", "--from", "unknown-title", "--yes", "--json")
    assert done.returncode == 0
    assert not (project / "evals" / "unknown-title").exists()


def test_dedupe_finds_identical_prompt_bodies(run_script, tmp_agent):
    import shutil

    project = tmp_agent("good")
    shutil.copytree(project / "evals" / "reserve-available",
                    project / "evals" / "reserve-available-copy")

    found = run_script(MANAGE, project, "dedupe", "--json")
    assert found.returncode == 1
    payload = found.json()
    assert len(payload["duplicates"]) == 1
    assert payload["would_remove"] == [str(project / "evals" / "reserve-available-copy")]
    assert "NOT merged" in payload["note"]
    assert (project / "evals" / "reserve-available-copy").is_dir(), "nothing removed yet"

    removed = run_script(MANAGE, project, "dedupe", "--yes", "--json")
    assert removed.returncode == 0
    assert not (project / "evals" / "reserve-available-copy").exists()
    assert (project / "evals" / "reserve-available").is_dir(), "the first of the group is kept"


def test_dedupe_is_quiet_when_there_are_none(run_script, agent_dir):
    result = run_script(MANAGE, agent_dir("good"), "dedupe", "--json")
    assert result.returncode == 0
    assert result.json()["duplicates"] == []


def test_renaming_a_case_that_does_not_exist_is_a_usage_error(run_script, tmp_agent):
    project = tmp_agent("good")
    result = run_script(MANAGE, project, "rename", "--from", "ghost", "--to", "other",
                        "--yes", "--json")
    assert result.returncode == 2
