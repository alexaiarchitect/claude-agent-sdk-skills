"""The grader catalog and one grader file's validation."""

from __future__ import annotations

import pytest
from agent_sdk_skills import (
    HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT, PYTHON_HOOK_EVENTS, SUBAGENT_TOOL_NAMES, SYNTHETIC_TOOLS,
)
from agent_sdk_skills.graders import (
    BUDGET_USAGE_KEYS,
    FREE_TYPES,
    GRADER_CATALOG,
    JUDGE_TYPES,
    SEMANTICS_NOTES,
    catalog_rows,
    catalog_table,
    grader_tool_names,
    is_synthetic,
    names_synthetic,
    normalize_tool_name,
    semantics_lines,
    spec_for,
    tier_of,
    tool_names_match,
    validate_grader,
)


def ids(findings):
    return [f.id for f in findings]


# -- the catalog itself ----------------------------------------------------

def test_the_catalog_has_the_twelve_types_the_contract_names():
    assert len(GRADER_CATALOG) == 12
    assert set(GRADER_CATALOG) == {
        "llm", "regex", "tool_used", "tool_order", "file_exists", "trajectory",
        "structured_output", "budget", "hook_event", "final_text", "no_tool", "terminal",
    }


def test_llm_is_the_only_judge_grader():
    assert JUDGE_TYPES == ("llm",)
    assert "llm" not in FREE_TYPES
    assert len(FREE_TYPES) == 11


def test_tier_is_derived_from_the_type_and_never_declared():
    assert tier_of("llm") == "judge"
    assert tier_of("regex") == "free"
    # A grader cannot make a judge check cheap by relabelling it: `tier` is not a
    # key any spec accepts.
    for spec in GRADER_CATALOG.values():
        assert "tier" not in spec.all_keys


def test_an_unknown_type_is_treated_as_free_rather_than_judge():
    """Guessing `judge` would inflate the cost estimate for what is usually a typo."""
    assert tier_of("vibe_check") == "free"
    assert tier_of(None) == "free"


def test_every_spec_says_what_it_does_not_prove():
    for spec in GRADER_CATALOG.values():
        assert spec.not_proven and len(spec.not_proven) > 30, spec.type
        assert spec.description
        assert spec.source


def test_every_spec_has_a_target_it_can_actually_read():
    for spec in GRADER_CATALOG.values():
        assert spec.targets, spec.type
        assert spec.default_target in spec.targets, spec.type


def test_the_catalog_renders_as_a_markdown_table():
    rows = catalog_rows()
    assert len(rows) == 12
    table = catalog_table()
    assert table.startswith("| type | tier |")
    assert "| llm | judge |" in table
    # A pipe inside a cell would break the table.
    assert "schema \\| schema_file" in table


def test_the_measured_semantics_are_available_as_data():
    notes = {note["id"] for note in SEMANTICS_NOTES}
    assert {"synthetic-tools", "subagent-alias", "budget-turns", "usage-keys",
            "session-import"} <= notes
    for note in SEMANTICS_NOTES:
        assert note["rule"] and note["why"] and note["source"]
    assert any("StructuredOutput" in line for line in semantics_lines())


def test_budget_ceilings_map_to_the_measured_usage_keys():
    """`usage.cache_creation` is a nested dict of TTL buckets, never a count."""
    assert BUDGET_USAGE_KEYS["max_input_tokens"] == "input_tokens"
    assert BUDGET_USAGE_KEYS["max_cache_read_tokens"] == "cache_read_input_tokens"
    assert "cache_creation" not in BUDGET_USAGE_KEYS.values()


# -- tool name semantics --------------------------------------------------

def test_task_and_agent_are_the_same_tool_under_two_names():
    assert normalize_tool_name("Agent") == normalize_tool_name("Task")
    assert tool_names_match("Agent", "Task")
    assert tool_names_match("Task", "Agent")
    assert not tool_names_match("Task", "Bash")
    assert set(SUBAGENT_TOOL_NAMES) == {"Task", "Agent"}


def test_structured_output_is_recognised_as_synthetic():
    assert is_synthetic("StructuredOutput")
    assert not is_synthetic("mcp__library__lookup_book")
    assert "StructuredOutput" in SYNTHETIC_TOOLS


def test_a_grader_that_names_a_synthetic_tool_is_asking_about_it_on_purpose():
    assert names_synthetic({"tool": "StructuredOutput"})
    assert names_synthetic({"tools": ["StructuredOutput"]})
    assert names_synthetic({"expected": [{"tool": "StructuredOutput"}]})
    assert not names_synthetic({"tool": "mcp__library__lookup_book"})


def test_every_tool_name_a_grader_mentions_is_collected_in_reading_order():
    meta = {"tool": "a", "before": "b", "after": "c", "tools": ["d", "a"],
            "expected": [{"tool": "e"}, "f"]}
    assert grader_tool_names(meta) == ["a", "b", "c", "d", "e", "f"]


# -- EVC010: the type ------------------------------------------------------

def test_an_unknown_grader_type_is_an_error_and_stops_further_checks():
    findings = validate_grader({"type": "vibe_check", "threshold": 0.8}, "")
    assert ids(findings) == ["EVC010"]
    assert findings[0].severity == "error"
    assert "vibe_check" in findings[0].message


def test_a_missing_grader_type_reports_the_same_id():
    findings = validate_grader({"pattern": "x"}, "")
    assert ids(findings) == ["EVC010"]
    assert "(missing)" in findings[0].message


# -- EVC011: required fields ----------------------------------------------

@pytest.mark.parametrize("meta,missing", [
    ({"type": "regex"}, "pattern"),
    ({"type": "tool_used"}, "tool"),
    ({"type": "tool_order", "before": "a"}, "after"),
    ({"type": "file_exists"}, "path"),
    ({"type": "trajectory"}, "expected"),
    ({"type": "final_text"}, "reference"),
    ({"type": "no_tool"}, "tools"),
    ({"type": "hook_event"}, "event"),
])
def test_a_missing_required_field_is_an_error_naming_the_field(meta, missing):
    findings = validate_grader(meta, "")
    assert "EVC011" in ids(findings)
    assert any(missing in f.message for f in findings if f.id == "EVC011")


def test_a_one_of_group_is_satisfied_by_any_member():
    assert "EVC011" not in ids(validate_grader({"type": "structured_output",
                                                "schema": {"type": "object"}}, ""))
    assert "EVC011" not in ids(validate_grader({"type": "structured_output",
                                                "schema_file": "out.json"}, ""))
    findings = validate_grader({"type": "structured_output"}, "")
    assert "EVC011" in ids(findings)
    assert "schema, schema_file" in " ".join(f.message for f in findings)


def test_a_budget_grader_needs_at_least_one_ceiling():
    assert "EVC011" in ids(validate_grader({"type": "budget"}, ""))
    assert "EVC011" not in ids(validate_grader({"type": "budget", "max_turns": 4}, ""))


def test_a_terminal_grader_needs_a_subtype_or_a_terminal_reason():
    assert "EVC011" in ids(validate_grader({"type": "terminal", "allow_error": True}, ""))
    assert "EVC011" not in ids(validate_grader({"type": "terminal", "subtype": "success"}, ""))


def test_an_llm_grader_takes_its_criteria_from_the_body():
    findings = validate_grader({"type": "llm"}, "")
    assert "EVC011" in ids(findings)
    assert any("body" in (f.locator or "") for f in findings)
    assert "EVC011" not in ids(validate_grader({"type": "llm"}, "PASS if x. FAIL if y."))


def test_a_body_that_is_only_a_prose_note_has_no_criterion():
    """A `---` line ends the criterion; a file starting with one has none."""
    body = "---\n\nProves something, does not prove something else."
    assert "EVC011" in ids(validate_grader({"type": "llm"}, body))


# -- EVC012: targets and enums --------------------------------------------

def test_a_target_the_type_cannot_read_is_an_error():
    findings = validate_grader({"type": "budget", "max_turns": 2, "target": "last_message"}, "")
    assert "EVC012" in ids(findings)
    assert "result" in " ".join(f.fix or "" for f in findings)


def test_a_valid_target_passes():
    assert "EVC012" not in ids(validate_grader(
        {"type": "regex", "pattern": "x", "target": "mock_calls"}, ""))


def test_only_an_llm_grader_may_take_a_file_target():
    ok = validate_grader({"type": "llm", "target": {"source": "file", "path": "out.md"}},
                         "PASS if x. FAIL if y.")
    assert "EVC012" not in ids(ok)
    bad = validate_grader({"type": "regex", "pattern": "x",
                           "target": {"source": "file", "path": "out.md"}}, "")
    assert "EVC012" in ids(bad)


@pytest.mark.parametrize("meta", [
    {"type": "regex", "pattern": "x", "match": "maybe"},
    {"type": "trajectory", "expected": [{"tool": "a"}], "match": "LOOSE"},
    {"type": "trajectory", "expected": [{"tool": "a"}], "args_match": "fuzzy"},
    {"type": "final_text", "reference": "x", "mode": "bleu"},
    {"type": "hook_event", "event": "PreToolUse", "decision": "maybe"},
])
def test_an_enum_value_the_runner_does_not_implement_is_an_error(meta):
    assert "EVC012" in ids(validate_grader(meta, ""))


def test_regex_match_accepts_the_count_form():
    assert "EVC012" not in ids(validate_grader(
        {"type": "regex", "pattern": "x", "match": "count:3"}, ""))


def test_a_pattern_that_does_not_compile_is_an_error():
    findings = validate_grader({"type": "regex", "pattern": "([unclosed"}, "")
    assert "EVC012" in ids(findings)
    assert "compile" in " ".join(f.message for f in findings)


def test_session_start_is_not_a_python_hook_event():
    """`SessionStartHookSpecificOutput` exists, but the HookEvent literal has 10
    values and SessionStart is not one of them."""
    findings = validate_grader({"type": "hook_event", "event": "SessionStart"}, "")
    assert "EVC012" in ids(findings)
    assert "SessionStart" in " ".join(f.fix or "" for f in findings)
    assert "EVC012" not in ids(validate_grader({"type": "hook_event", "event": "PreToolUse"}, ""))


def test_stop_and_subagent_stop_are_valid_hook_events_with_a_specific_output():
    """From SDK 0.2.166, of the 10 Python events only `PreCompact` lacks a
    `*HookSpecificOutput` type; `Stop`/`SubagentStop` take `additionalContext`."""
    assert HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT == ("PreCompact",)
    assert set(HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT) <= set(PYTHON_HOOK_EVENTS)
    for event in ("Stop", "SubagentStop", "PreCompact"):
        assert "EVC012" not in ids(validate_grader({"type": "hook_event", "event": event}, ""))


def test_a_threshold_outside_zero_to_one_is_an_error():
    assert "EVC012" in ids(validate_grader(
        {"type": "trajectory", "expected": [{"tool": "a"}], "threshold": 1.5}, ""))


def test_min_and_max_must_be_non_negative_integers():
    assert "EVC012" in ids(validate_grader({"type": "tool_used", "tool": "a", "max": -1}, ""))
    assert "EVC012" not in ids(validate_grader({"type": "tool_used", "tool": "a", "max": 0}, ""))


def test_an_expected_entry_without_a_tool_is_reported():
    findings = validate_grader({"type": "trajectory", "expected": [{"args": {"x": 1}}]}, "")
    assert "EVC011" in ids(findings)


# -- EVC002: unknown keys -------------------------------------------------

def test_an_unknown_key_is_a_warning_with_a_suggestion():
    findings = validate_grader({"type": "regex", "pattern": "x", "paterns": "y"}, "")
    warnings = [f for f in findings if f.id == "EVC002"]
    assert warnings and warnings[0].severity == "warn"
    assert "pattern" in (warnings[0].fix or "")


def test_the_common_keys_are_accepted_on_every_type():
    for type_name, extra in (("regex", {"pattern": "x"}), ("no_tool", {"tools": ["a"]})):
        meta = {"type": type_name, "name": "n", "description": "d", **extra}
        assert "EVC002" not in ids(validate_grader(meta, ""))


def test_every_finding_carries_a_source_citation():
    findings = validate_grader({"type": "hook_event", "event": "SessionEnd"}, "")
    assert findings
    for finding in findings:
        assert finding.source


def test_spec_for_returns_none_for_an_unknown_type():
    assert spec_for("nope") is None
    assert spec_for("llm") is not None
