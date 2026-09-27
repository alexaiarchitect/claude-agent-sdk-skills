"""Coverage analysis: rules out of a prompt, cases against rules, honest gaps.

The thing these tests defend is the honesty of the report. A matrix that says
"0 of 0 rules covered" when the prompt could not be read, or that reports every
tool as untested when the tool list is unknown, is worse than no matrix at all:
it turns "not measured" into "clean".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_sdk_skills import coverage


# -- rule extraction -------------------------------------------------------

NUMBERED = """You are a desk.

Rules:
1. Look a book up before reserving it; never reserve a title you have not
   looked up.
2. A member may hold at most one copy. If they already hold it, refuse and do
   not call reserve_book.
3. Answer in one short paragraph.
"""


def test_numbered_rules_are_extracted_with_their_continuations():
    rules = coverage.extract_rules(NUMBERED)
    assert [r.index for r in rules] == [1, 2, 3]
    assert all(r.kind == "numbered" for r in rules)
    assert "looked up" in rules[0].text, "an indented continuation joins the rule above it"


def test_refusal_and_ordering_rules_are_flagged():
    rules = coverage.extract_rules(NUMBERED)
    assert rules[0].is_refusal and rules[0].is_ordering
    assert rules[1].is_refusal
    assert not rules[2].is_refusal


def test_a_rule_names_the_tools_it_mentions():
    rules = coverage.extract_rules(NUMBERED)
    assert "reserve_book" in rules[1].tools


def test_prose_without_markers_falls_back_to_obligation_sentences():
    rules = coverage.extract_rules(
        "You help with bookings. You must never double-book a member. "
        "Answer briefly.")
    assert rules, "a prose prompt still has rules"
    assert all(r.kind == "sentence" for r in rules), "and says it guessed"


def test_an_empty_prompt_has_no_rules():
    assert coverage.extract_rules("") == []
    assert coverage.extract_rules(None) == []


# -- reading the prompt ----------------------------------------------------

def test_a_literal_module_constant_is_read(agent_dir):
    prompt = coverage.read_system_prompt(agent_dir("good"))
    assert prompt.readable and prompt.kind == "literal"
    assert prompt.locator == "SYSTEM_PROMPT"
    assert "reservations desk" in prompt.text


def test_a_runtime_prompt_is_dynamic_not_absent(tmp_path: Path):
    module = tmp_path / "agent.py"
    module.write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n"
        "import os\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(system_prompt=load_prompt())\n",
        encoding="utf-8")
    prompt = coverage.read_system_prompt(module)
    assert prompt.kind == "dynamic"
    assert not prompt.readable
    assert prompt.note and "runtime" in prompt.note


def test_reading_a_prompt_never_executes_the_module(tmp_path: Path):
    """A review has to work on a project whose imports are the problem."""
    marker = tmp_path / "executed"
    module = tmp_path / "agent.py"
    module.write_text(
        f"open({str(marker)!r}, 'w').write('x')\n"
        'SYSTEM_PROMPT = "1. Never do the thing."\n', encoding="utf-8")
    prompt = coverage.read_system_prompt(module)
    assert prompt.readable
    assert not marker.exists()


def test_a_syntax_error_is_reported_not_raised(tmp_path: Path):
    (tmp_path / "agent.py").write_text("def (:\n", encoding="utf-8")
    prompt = coverage.read_system_prompt(tmp_path / "agent.py")
    assert prompt.kind == "unreadable"


# -- cases -----------------------------------------------------------------

def test_case_summaries_carry_the_tools_their_graders_name(agent_dir):
    cases = coverage.summarize_cases(agent_dir("good") / "evals")
    by_name = {c["name"]: c for c in cases}
    assert "mcp__library__reserve_book" in by_name["reserve-available"]["tools"]
    assert by_name["refuse-double-booking"]["restraint_scored"], "it has a no_tool grader"


def test_a_case_scored_only_by_a_judge_is_not_restraint_scored(tmp_path: Path):
    case = tmp_path / "evals" / "talks-about-it"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text("---\ncategory: adversarial\n---\nDo the thing.\n",
                                    encoding="utf-8")
    (case / "graders" / "says_no.md").write_text(
        "---\nname: says_no\ntype: llm\n---\nPASS if it declines.\n", encoding="utf-8")
    rows = coverage.summarize_cases(tmp_path / "evals")
    assert rows[0]["restraint_scored"] is False


# -- the matrix ------------------------------------------------------------

def test_the_good_fixture_covers_every_rule_it_declares(agent_dir):
    project = agent_dir("good")
    rules = coverage.extract_rules(coverage.read_system_prompt(project).text)
    grid = coverage.matrix(rules, coverage.summarize_cases(project / "evals"))
    assert grid["uncovered"] == []
    assert grid["covered"] == grid["total_rules"] == len(rules)


def test_a_covered_row_carries_the_evidence_it_matched_on(agent_dir):
    project = agent_dir("good")
    rules = coverage.extract_rules(coverage.read_system_prompt(project).text)
    grid = coverage.matrix(rules, coverage.summarize_cases(project / "evals"))
    hit = next(c for row in grid["rows"] for c in row["cases"])
    assert hit["matched_tools"] or len(hit["matched_phrases"]) >= 2


def test_one_shared_phrase_is_not_coverage():
    rule = coverage.Rule(index=1, text="Never reveal the vault combination",
                         is_refusal=True, phrases=["reveal", "vault", "combination"])
    case = {"name": "unrelated", "tools": [], "text": "please open the vault door"}
    grid = coverage.matrix([rule], [case])
    assert grid["uncovered"] == ["rule-1"], "one word in common is a coincidence"


# -- shape -----------------------------------------------------------------

def test_the_good_fixture_has_the_target_shape(agent_dir):
    result = coverage.shape(coverage.summarize_cases(agent_dir("good") / "evals"))
    assert result["ok"], result["gaps"]
    assert result["adversarial_ratio"] >= coverage.ADVERSARIAL_SHARE


def test_a_suite_of_happy_paths_is_reported_as_thin():
    cases = [{"name": f"c{i}", "category": "happy", "adversarial": False,
              "tools": [], "text": ""} for i in range(5)]
    result = coverage.shape(cases)
    assert not result["ok"]
    ids = {g["id"] for g in result["gaps"]}
    assert "shape-adversarial" in ids
    assert "shape-adversarial-share" in ids


def test_uncategorized_cases_are_called_out():
    result = coverage.shape([{"name": "x", "category": None, "adversarial": False,
                              "tools": [], "text": ""}])
    assert any(g["id"] == "shape-uncategorized" for g in result["gaps"])


def test_an_empty_suite_does_not_divide_by_zero():
    result = coverage.shape([])
    assert result["total"] == 0 and result["adversarial_ratio"] == 0.0


# -- n + 1 -----------------------------------------------------------------

def test_a_refusal_rule_with_no_case_is_an_n_plus_one_gap():
    rule = coverage.Rule(index=1, text="Never call reserve_book twice",
                         is_refusal=True, tools=["reserve_book"])
    gaps = coverage.n_plus_one_gaps([rule], [])
    assert [g["reason"] for g in gaps] == ["no_case"]


def test_a_refusal_case_scored_only_on_the_reply_is_a_different_gap():
    rule = coverage.Rule(index=1, text="Never call reserve_book twice",
                         is_refusal=True, tools=["reserve_book"])
    case = {"name": "apologizes", "tools": ["reserve_book"], "text": "reserve_book",
            "restraint_scored": False}
    gaps = coverage.n_plus_one_gaps([rule], [case])
    assert [g["reason"] for g in gaps] == ["no_trace_check"]
    assert "no_tool" in gaps[0]["recommendation"]


def test_a_trace_scored_refusal_case_closes_the_gap():
    rule = coverage.Rule(index=1, text="Never call reserve_book twice",
                         is_refusal=True, tools=["reserve_book"])
    case = {"name": "holds_back", "tools": ["reserve_book"], "text": "reserve_book",
            "restraint_scored": True}
    assert coverage.n_plus_one_gaps([rule], [case]) == []


def test_a_non_refusal_rule_never_produces_an_n_plus_one_gap():
    rule = coverage.Rule(index=1, text="Answer in one paragraph")
    assert coverage.n_plus_one_gaps([rule], []) == []


# -- tools -----------------------------------------------------------------

def test_tool_coverage_lists_the_cases_that_assert_about_each_tool(agent_dir):
    cases = coverage.summarize_cases(agent_dir("good") / "evals")
    result = coverage.tool_coverage(
        ["mcp__library__lookup_book", "mcp__library__reserve_book"], cases)
    assert result["status"] == "ok"
    assert result["untested"] == []
    assert "reserve-available" in result["by_tool"]["mcp__library__reserve_book"]


def test_an_unknown_tool_list_reports_unknown_rather_than_everything_untested():
    result = coverage.tool_coverage(None, [{"name": "c", "tools": ["x"], "text": ""}])
    assert result["status"] == coverage.UNKNOWN
    assert result["untested"] == []
    assert "could not be read" in result["note"]


def test_synthetic_and_subagent_names_are_never_grader_only():
    cases = [{"name": "c", "tools": ["StructuredOutput", "ToolSearch", "Task"], "text": ""}]
    result = coverage.tool_coverage(["mcp__a__b"], cases)
    assert result["grader_only"] == []


@pytest.mark.parametrize("name", ["extract_rules", "summarize_cases", "matrix",
                                  "shape", "n_plus_one_gaps", "tool_coverage"])
def test_the_public_surface_is_exported(name):
    assert name in coverage.__all__
    assert callable(getattr(coverage, name))
