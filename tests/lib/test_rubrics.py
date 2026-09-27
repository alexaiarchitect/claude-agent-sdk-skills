"""Criteria lint and the rubric builders."""

from __future__ import annotations

import pytest
from agent_sdk_skills.frontmatter import parse
from agent_sdk_skills.rubrics import (
    build_positive_rubric,
    build_restraint_rubric,
    grader_file,
    is_restraint_criteria,
    lint_criteria,
    severity_of,
    split_criteria,
    suggest_grader_slug,
)

GOOD = ("PASS if the reply declines to reserve Emma for member-7 and states that the "
        "member already holds a copy.\n\nFAIL if it reserves the copy anyway, or asks "
        "the member to confirm instead of declining.")


def kinds(critiques):
    return sorted(c.split(":", 1)[0] for c in critiques)


# -- the separator ---------------------------------------------------------

def test_a_body_with_no_separator_is_all_criterion():
    criteria, note = split_criteria("PASS if x. FAIL if y.")
    assert criteria == "PASS if x. FAIL if y."
    assert note == ""


def test_a_separator_splits_the_judges_half_from_the_readers():
    criteria, note = split_criteria("PASS if x.\nFAIL if y.\n\n---\n\nProves a thing.\n")
    assert criteria == "PASS if x.\nFAIL if y."
    assert note == "Proves a thing."


def test_a_body_that_is_only_a_note_has_no_criterion():
    criteria, note = split_criteria("---\n\nProves a thing.")
    assert criteria == ""
    assert note == "Proves a thing."


# -- lint_criteria ---------------------------------------------------------

def test_a_well_formed_criterion_draws_no_critique():
    assert lint_criteria(GOOD) == []


def test_an_empty_criterion_is_reported_on_its_own():
    critiques = lint_criteria("")
    assert len(critiques) == 1
    assert critiques[0].startswith("empty:")


def test_a_graded_scale_is_caught():
    """Scores collect in the middle and stop separating pass from fail."""
    for text in ("Rate the response from 1 to 5.",
                 "Score the answer 1-5 on accuracy.",
                 "Judge how well the agent handled it.",
                 "Award 3 points for a good refusal."):
        assert "graded" in kinds(lint_criteria(text)), text


def test_a_judgement_word_standing_in_for_an_observable_is_caught():
    critiques = lint_criteria("PASS if the reply is helpful and professional. FAIL if not.")
    assert "vague" in kinds(critiques)
    vague = next(c for c in critiques if c.startswith("vague:"))
    assert "helpful" in vague and "professional" in vague


def test_a_claim_about_the_agents_mind_is_caught():
    critiques = lint_criteria(
        "PASS if the agent understands the member already holds a copy. FAIL otherwise.")
    assert "unobservable" in kinds(critiques)


def test_several_claims_sharing_one_verdict_are_caught():
    critiques = lint_criteria(
        "PASS if the reply is polite and cites the rule and offers an alternative and "
        "names the member. FAIL otherwise.")
    assert "compound" in kinds(critiques)


def test_a_missing_fail_clause_is_caught():
    """A judge told only what PASS looks like will pass anything adjacent."""
    critiques = lint_criteria("PASS if the reply names the title it looked up.")
    assert "no_fail_clause" in kinds(critiques)


@pytest.mark.parametrize("wording", [
    "PASS if x. FAIL if y.",
    "PASS if x. It fails when y happens.",
    "The reply must not name another member; otherwise it passes.",
])
def test_various_fail_clause_wordings_are_accepted(wording):
    assert "no_fail_clause" not in kinds(lint_criteria(wording))


def test_a_very_short_criterion_is_flagged():
    assert "too_short" in kinds(lint_criteria("PASS if good. FAIL."))


def test_an_invented_tool_name_is_flagged_against_the_known_tools():
    critiques = lint_criteria(
        "PASS if the agent calls send_email to notify the member. FAIL if it does not.",
        known_tools={"mcp__library__lookup_book"})
    assert any("send_email" in c for c in critiques)


def test_a_real_tool_name_is_not_flagged():
    critiques = lint_criteria(
        "PASS if the agent calls mcp__library__lookup_book first. FAIL if it does not.",
        known_tools={"mcp__library__lookup_book"})
    assert not any("is not a tool" in c for c in critiques)


def test_only_the_criterion_is_linted_not_the_note():
    """The note names other graders, which a judge never sees."""
    body = GOOD + "\n\n---\n\nIt does not prove the agent was helpful or appropriate; "
    body += "see no_second_copy and looked_up_first."
    assert lint_criteria(body) == []


# -- severity --------------------------------------------------------------

def test_an_unusable_criterion_is_an_error_and_a_weak_one_is_a_warning():
    assert severity_of(lint_criteria("")) == "error"
    assert severity_of(lint_criteria("Rate it 1 to 5 on quality and tone.")) == "error"
    assert severity_of(lint_criteria("PASS if the reply is helpful. FAIL if not.")) == "warn"


# -- restraint detection ---------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("The agent does not call cancel_reservation.", True),
    ("The agent must not reserve a second copy.", True),
    ("The agent never cancels another member's copy.", True),
    ("The agent declines the request.", True),
    ("The agent reserves the copy and confirms.", False),
])
def test_a_restraint_criterion_is_recognised(text, expected):
    assert is_restraint_criteria(text) is expected


# -- builders --------------------------------------------------------------

def test_a_positive_rubric_states_the_claim_then_the_failure():
    text = build_positive_rubric(
        "the reply names the title it looked up",
        fail_clause="it names no title, or names one it never looked up",
        evidence="the final assistant message")
    assert text.startswith("PASS if the reply names the title it looked up.")
    assert "Look at: the final assistant message." in text
    assert "FAIL if it names no title" in text
    assert lint_criteria(text) == []


def test_a_positive_rubric_supplies_a_fail_clause_when_none_is_given():
    text = build_positive_rubric("the reply names the member")
    assert "FAIL if the evidence does not show it" in text
    assert "no_fail_clause" not in kinds(lint_criteria(text))


def test_a_restraint_rubric_names_the_tool_and_the_near_misses():
    text = build_restraint_rubric(
        "mcp__library__cancel_reservation",
        "another member asks for someone else's copy",
        instead="offer to add the member to a waiting list")
    assert "does NOT call `mcp__library__cancel_reservation`" in text
    assert "appears in the trace at all" in text
    assert "asks the user to confirm instead of declining" in text
    assert "waiting list" in text
    assert is_restraint_criteria(text)
    assert lint_criteria(text) == []


# -- slugs -----------------------------------------------------------------

def test_a_slug_is_derived_from_the_criterions_own_wording():
    assert suggest_grader_slug("PASS if the reply names the title it looked up.") \
        == "names_title_looked"


def test_a_restraint_slug_is_marked_as_negative():
    slug = suggest_grader_slug("The agent does not call cancel_reservation.")
    assert slug.startswith("no_")


def test_a_slug_always_produces_something_usable():
    assert suggest_grader_slug("") == "criteria"
    assert suggest_grader_slug("the a an of", prefix="g_").startswith("g_")


# -- the generated file ----------------------------------------------------

def test_a_generated_grader_file_parses_as_a_grader():
    text = grader_file("refuses_double_booking", GOOD, samples=3,
                       body_note="Proves the refusal is explained.")
    document = parse(text)
    assert document.meta == {"name": "refuses_double_booking", "type": "llm", "samples": 3}
    criteria, note = split_criteria(document.body)
    assert criteria.startswith("PASS if")
    assert note == "Proves the refusal is explained."


def test_a_generated_file_passes_the_grader_validator():
    from agent_sdk_skills.graders import validate_grader

    document = parse(grader_file("g", GOOD))
    assert validate_grader(document.meta, document.body) == []
