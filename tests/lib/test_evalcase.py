"""Loading a case directory, and every EVC finding it can produce."""

from __future__ import annotations

import pytest
from agent_sdk_skills.evalcase import (
    CATEGORIES,
    case_summary,
    iter_cases,
    load_case,
    stray_prompt_files,
    suite_summary,
    validate_case,
    validate_suite,
)

AGENT_TOOLS = {
    "mcp__library__lookup_book",
    "mcp__library__reserve_book",
    "mcp__library__cancel_reservation",
}


@pytest.fixture
def cases_dir(fixtures):
    return fixtures / "cases"


@pytest.fixture
def good_evals(fixtures):
    return fixtures / "agents" / "good" / "evals"


def check(case, **kwargs):
    kwargs.setdefault("agent_tools", AGENT_TOOLS)
    kwargs.setdefault("mock_tools", set())
    return validate_case(case, **kwargs)


def ids(findings):
    return sorted({f.id for f in findings})


def by_id(findings, wanted):
    return [f for f in findings if f.id == wanted]


# -- loading ---------------------------------------------------------------

def test_a_case_loads_its_frontmatter_body_and_graders(cases_dir):
    case = load_case(cases_dir / "valid")
    assert case.name == "reserve-available"
    assert case.category == "happy"
    assert case.tags == ["reservation", "happy"]
    assert "Reserve 'Dune'" in case.body
    assert [g.name for g in case.graders] == ["confirms", "looked_up_first"]
    assert case.ok


def test_a_case_with_a_broken_header_still_loads_its_body(cases_dir):
    """A validator that returns nothing on a broken file says nothing about the rest."""
    case = load_case(cases_dir / "broken_frontmatter")
    assert not case.ok
    assert case.errors
    assert "Reserve 'Dune'" in case.body


def test_a_missing_prompt_file_is_an_error_not_an_exception(tmp_path):
    case = load_case(tmp_path)
    assert not case.ok
    assert "prompt.md" in case.errors[0]


def test_the_directory_name_is_the_default_case_name(tmp_path):
    (tmp_path / "my-case").mkdir()
    (tmp_path / "my-case" / "prompt.md").write_text("Do the thing.\n")
    assert load_case(tmp_path / "my-case").name == "my-case"


def test_iter_cases_skips_the_runners_own_directories(good_evals):
    names = sorted(c.name for c in iter_cases(good_evals))
    assert names == ["no-cancel-unasked", "refuse-double-booking", "reserve-available",
                     "two-turn-memory", "unknown-title"]
    assert "mocks" not in names and "personas" not in names


# -- EVC001 / EVC006: the prompt itself ------------------------------------

def test_a_case_with_no_prompt_no_turns_and_no_persona_is_an_error(tmp_path):
    case_dir = tmp_path / "empty"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\ncategory: happy\n---\n\n")
    assert "EVC001" in ids(check(load_case(case_dir)))


def test_turns_and_simulated_user_are_mutually_exclusive(tmp_path):
    case_dir = tmp_path / "both"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text(
        '---\nturns: ["a", "b"]\nsimulated_user: p.json\n---\nx\n')
    findings = check(load_case(case_dir))
    assert "EVC006" in ids(findings)
    assert by_id(findings, "EVC006")[0].severity == "error"


def test_a_body_alongside_turns_is_reported_as_ignored(tmp_path):
    case_dir = tmp_path / "bodyandturns"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text('---\nturns: ["a"]\n---\nignored text\n')
    findings = [f for f in check(load_case(case_dir)) if f.id == "EVC002"]
    assert any("ignored" in f.message for f in findings)


# -- EVC002: unknown keys and wrong types ----------------------------------

def test_an_unknown_frontmatter_key_warns_and_suggests_the_real_one(tmp_path):
    case_dir = tmp_path / "typo"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\ncatgory: happy\n---\nx\n")
    findings = by_id(check(load_case(case_dir)), "EVC002")
    assert findings and findings[0].severity == "warn"
    assert "category" in (findings[0].fix or "")


def test_runs_must_be_a_positive_integer(tmp_path):
    case_dir = tmp_path / "runs"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\nruns: 0\n---\nx\n")
    assert "EVC002" in ids(check(load_case(case_dir)))


def test_an_agent_entry_must_be_module_colon_function(tmp_path):
    case_dir = tmp_path / "agent"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\nagent: agent.build_options\n---\nx\n")
    findings = by_id(check(load_case(case_dir)), "EVC002")
    assert any("module:function" in f.message for f in findings)


# -- EVC003 / EVC004 / EVC042: overrides -----------------------------------

def test_an_override_that_is_not_an_option_is_an_error(cases_dir):
    findings = by_id(check(load_case(cases_dir / "unknown_override")), "EVC003")
    assert findings and findings[0].severity == "error"
    assert "modle" in findings[0].message
    assert "model" in (findings[0].fix or "")


def test_a_real_option_the_runner_owns_is_a_different_finding(cases_dir):
    """`cwd` exists but the runner creates a fresh working directory per run."""
    findings = check(load_case(cases_dir / "not_overridable"))
    assert "EVC004" in ids(findings)
    assert "EVC003" not in ids(findings)
    assert "cwd" in by_id(findings, "EVC004")[0].message


def test_an_overridable_option_is_accepted(tmp_path):
    case_dir = tmp_path / "ok"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text(
        "---\noverrides:\n  max_turns: 4\n  model: claude-sonnet-5-5\n---\nx\n")
    findings = ids(check(load_case(case_dir)))
    assert "EVC003" not in findings and "EVC004" not in findings


@pytest.mark.parametrize("override", [
    "  max_thinking_tokens: 2000\n",
    '  allowed_tools: [Skill, Bash]\n',
])
def test_a_deprecated_override_warns(tmp_path, override):
    case_dir = tmp_path / "dep"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text(f"---\noverrides:\n{override}---\nx\n")
    findings = by_id(check(load_case(case_dir)), "EVC042")
    assert findings
    assert all(f.severity == "warn" for f in findings)


def test_an_option_that_is_both_deprecated_and_runner_owned_reports_the_stronger_id(tmp_path):
    """CONTRACTS §1.1 lists `debug_stderr` as runner-owned *and* deprecated.

    EVC004 wins: "the runner owns it" is the reason it is rejected outright,
    while EVC042 would only suggest a replacement that does not exist.
    """
    case_dir = tmp_path / "both"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\noverrides:\n  debug_stderr: true\n---\nx\n")
    found = ids(check(load_case(case_dir)))
    assert "EVC004" in found
    assert "EVC042" not in found


def test_overriding_the_isolation_defaults_is_reported_with_the_cost(tmp_path):
    case_dir = tmp_path / "iso"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text(
        "---\noverrides:\n  setting_sources: [user, project]\n---\nx\n")
    findings = by_id(check(load_case(case_dir)), "EVC042")
    assert findings and findings[0].severity == "info"
    assert "17x" in (findings[0].fix or "")


# -- EVC007: env namespace -------------------------------------------------

def test_an_env_key_outside_the_eval_namespace_is_an_error(tmp_path):
    case_dir = tmp_path / "env"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text(
        "---\nenv:\n  ANTHROPIC_API_KEY: sk-test\n---\nx\n")
    findings = by_id(check(load_case(case_dir)), "EVC007")
    assert findings and findings[0].severity == "error"
    assert "EVAL_" in findings[0].fix


def test_an_eval_prefixed_env_key_is_accepted(tmp_path):
    case_dir = tmp_path / "env-ok"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\nenv:\n  EVAL_BRANCH: main\n---\nx\n")
    assert "EVC007" not in ids(check(load_case(case_dir)))


# -- EVC005: stray prompts -------------------------------------------------

def test_a_prompt_outside_a_case_directory_never_runs(tmp_path):
    (tmp_path / "prompt.md").write_text("orphan\n")
    (tmp_path / "group" / "nested").mkdir(parents=True)
    (tmp_path / "group" / "nested" / "prompt.md").write_text("also orphan\n")
    stray = stray_prompt_files(tmp_path)
    assert len(stray) == 2
    findings = by_id(validate_suite(tmp_path), "EVC005")
    assert len(findings) == 2
    assert all(f.severity == "warn" for f in findings)


# -- EVC020: the tool cross-check ------------------------------------------

def test_a_grader_naming_a_tool_nothing_provides_warns(tmp_path):
    case_dir = tmp_path / "toolcheck"
    (case_dir / "graders").mkdir(parents=True)
    (case_dir / "prompt.md").write_text("---\ncategory: happy\n---\nx\n")
    (case_dir / "graders" / "g.md").write_text(
        "---\ntype: tool_used\ntool: mcp__library__email_member\n---\nnote\n")
    findings = by_id(check(load_case(case_dir)), "EVC020")
    assert findings and findings[0].severity == "warn"


def test_an_unqualified_tool_name_is_reported_with_the_qualified_form(tmp_path):
    case_dir = tmp_path / "unqualified"
    (case_dir / "graders").mkdir(parents=True)
    (case_dir / "prompt.md").write_text("---\ncategory: happy\n---\nx\n")
    (case_dir / "graders" / "g.md").write_text(
        "---\ntype: tool_used\ntool: reserve_book\n---\nnote\n")
    findings = by_id(check(load_case(case_dir)), "EVC020")
    assert findings
    assert "mcp__library__reserve_book" in (findings[0].fix or "")


def test_the_subagent_alias_and_synthetic_tools_do_not_trip_the_check(tmp_path):
    case_dir = tmp_path / "alias"
    (case_dir / "graders").mkdir(parents=True)
    (case_dir / "prompt.md").write_text("---\ncategory: happy\n---\nx\n")
    (case_dir / "graders" / "a.md").write_text("---\ntype: no_tool\ntools: [Agent]\n---\nn\n")
    (case_dir / "graders" / "b.md").write_text(
        "---\ntype: tool_used\ntool: StructuredOutput\n---\nn\n")
    assert "EVC020" not in ids(check(load_case(case_dir)))


def test_the_cross_check_is_skipped_when_the_tools_are_unknown(cases_dir):
    """An empty set means 'exposes nothing'; None means 'we could not tell'."""
    case = load_case(cases_dir / "unknown_override")
    assert "EVC020" not in ids(validate_case(case, agent_tools=None, mock_tools=None))


# -- EVC030 / EVC031: category ---------------------------------------------

def test_a_missing_category_is_an_informational_note(tmp_path):
    case_dir = tmp_path / "nocat"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\nname: x\n---\nx\n")
    findings = by_id(check(load_case(case_dir)), "EVC030")
    assert findings and findings[0].severity == "info"


def test_an_unknown_category_warns_and_lists_the_real_ones(tmp_path):
    case_dir = tmp_path / "badcat"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("---\ncategory: smoke\n---\nx\n")
    findings = by_id(check(load_case(case_dir)), "EVC031")
    assert findings and findings[0].severity == "warn"
    for category in CATEGORIES:
        assert category in findings[0].fix


# -- EVC040 / EVC041: does the scoring match the case? ---------------------

def test_a_trajectory_grader_on_a_simulated_user_case_is_an_error(cases_dir):
    findings = by_id(check(load_case(cases_dir / "simulated_with_trajectory")), "EVC040")
    assert findings and findings[0].severity == "error"
    assert "persona" in findings[0].fix


def test_an_adversarial_case_scored_with_a_lenient_match_warns(cases_dir):
    findings = by_id(check(load_case(cases_dir / "adversarial_lenient")), "EVC041")
    assert findings and all(f.severity == "warn" for f in findings)
    assert any("IN_ORDER" in f.message for f in findings)


def test_an_adversarial_case_with_exact_and_no_tool_is_not_flagged(good_evals):
    case = load_case(good_evals / "no-cancel-unasked")
    assert case.category == "adversarial"
    assert "EVC041" not in ids(check(case))


def test_a_refusal_shaped_name_is_treated_as_a_restraint_case(tmp_path):
    case_dir = tmp_path / "no_reserve_twice"
    (case_dir / "graders").mkdir(parents=True)
    (case_dir / "prompt.md").write_text("---\ncategory: edge\n---\nx\n")
    (case_dir / "graders" / "g.md").write_text(
        "---\ntype: regex\npattern: sorry\n---\nnote\n")
    findings = by_id(check(load_case(case_dir)), "EVC041")
    assert any("restraint check" in f.message for f in findings)


# -- EVC050: criteria quality ----------------------------------------------

def test_weak_llm_criteria_produce_one_finding_with_every_critique(tmp_path):
    case_dir = tmp_path / "weak"
    (case_dir / "graders").mkdir(parents=True)
    (case_dir / "prompt.md").write_text("---\ncategory: happy\n---\nx\n")
    (case_dir / "graders" / "g.md").write_text(
        "---\ntype: llm\n---\nRate the response from 1 to 5 on how good and "
        "professional it is, and whether the agent understands the request.\n")
    findings = by_id(check(load_case(case_dir)), "EVC050")
    assert len(findings) == 1, "one paragraph is one problem, not five"
    assert findings[0].severity == "error"        # a graded scale cannot be repaired by voting
    for kind in ("graded", "vague", "unobservable"):
        assert kind in findings[0].message


def test_a_strong_criterion_produces_no_finding(good_evals):
    case = load_case(good_evals / "no-cancel-unasked")
    assert "EVC050" not in ids(check(case))


def test_the_prose_note_after_the_separator_is_not_linted(tmp_path):
    """The note names other graders; a judge never sees it and nor does the lint."""
    case_dir = tmp_path / "note"
    (case_dir / "graders").mkdir(parents=True)
    (case_dir / "prompt.md").write_text("---\ncategory: happy\n---\nx\n")
    (case_dir / "graders" / "g.md").write_text(
        "---\ntype: llm\n---\nPASS if the reply names the title.\n\n"
        "FAIL if it does not.\n\n---\n\nIt does not prove the agent was helpful "
        "or appropriate; see no_second_copy and looked_up_first.\n")
    assert "EVC050" not in ids(check(load_case(case_dir)))


# -- EVC060: a case that cannot fail ---------------------------------------

def test_a_case_with_no_graders_can_never_fail(cases_dir):
    findings = by_id(check(load_case(cases_dir / "no_graders")), "EVC060")
    assert findings and findings[0].severity == "warn"
    assert "never fail" in findings[0].message


# -- EVC010/011 reach through from the grader validator --------------------

def test_a_bad_grader_type_reaches_the_case_report(cases_dir):
    assert "EVC010" in ids(check(load_case(cases_dir / "bad_grader_type")))


# -- summaries -------------------------------------------------------------

def test_a_case_summary_names_the_tier_it_needs(good_evals):
    free = case_summary(load_case(good_evals / "reserve-available"))
    judge = case_summary(load_case(good_evals / "refuse-double-booking"))
    assert free["tier"] == "free"
    assert judge["tier"] == "judge", "any llm grader makes the whole case a judge case"
    assert "trajectory" in free["grader_types"]


def test_the_suite_summary_shows_the_shape_of_the_suite(good_evals):
    summary = suite_summary(good_evals)
    assert summary["cases"] == 5
    assert set(summary["by_category"]) == set(CATEGORIES)
    assert summary["by_tier"] == {"free": 3, "judge": 2}
    assert summary["without_graders"] == []


def test_the_good_fixture_suite_is_clean(good_evals):
    """The fixture is the worked example, so it must pass its own rules."""
    from agent_sdk_skills.mocks import mock_tool_names

    findings = validate_suite(good_evals, agent_tools=AGENT_TOOLS,
                              mock_tools=mock_tool_names(good_evals))
    assert findings == [], [f"{f.id} {f.message}" for f in findings]


def test_two_cases_with_the_same_name_would_overwrite_each_other(tmp_path):
    for directory in ("a", "b"):
        case_dir = tmp_path / directory
        case_dir.mkdir()
        (case_dir / "prompt.md").write_text("---\nname: same\n---\nx\n")
    findings = [f for f in validate_suite(tmp_path) if "both named" in f.message]
    assert findings


def test_every_finding_cites_a_source(cases_dir):
    for name in ("unknown_override", "not_overridable", "adversarial_lenient", "no_graders"):
        for finding in check(load_case(cases_dir / name)):
            assert finding.source, f"{name}: {finding.id} has no source"
