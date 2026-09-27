"""The gap report is the one shape every script prints."""

from agent_sdk_skills.report import (
    EXIT_FINDINGS, EXIT_INCONCLUSIVE, EXIT_OK, SCHEMA, GapReport, Option, exit_code_for,
)


def make() -> GapReport:
    report = GapReport(subject="/tmp/x", skill="agent-review", discovered={"layout": {"style": "convention"}})
    report.add("AGT010", "warn", "agent", "hardcoded model", path="/tmp/x/agent.py", locator="line 12",
               fix="read CLAUDE_MODEL", source="this plugin")
    report.add("AGT030", "error", "agent", "legacy import", path="/tmp/x/agent.py")
    report.add_gap("GAP-EVALS", "no cases", "nothing to replay", "run eval-create")
    report.add_option(Option("1", "Review", recommended=True, cost="free"))
    report.add_option(Option("2", "Run", cost="run", runs=["python -m agent_sdk_evals run evals"]))
    return report


def test_json_shape_carries_schema_and_summary():
    doc = make().to_dict()
    assert doc["schema"] == SCHEMA == "agent-sdk-skills.gap-report/1"
    assert doc["summary"] == {"errors": 1, "warnings": 1, "infos": 0}
    assert doc["findings"][0]["id"] == "AGT010"
    assert "path" in doc["findings"][0] and "fix" in doc["findings"][0]


def test_markdown_orders_errors_before_warnings_and_strips_the_subject_path():
    md = make().to_md()
    assert md.index("## Errors") < md.index("## Warnings")
    assert "`AGT030` agent.py" in md, "the subject path is not repeated on every line"
    assert "**(recommended)**" in md and "cost: run" in md
    assert "Runs: python -m agent_sdk_evals run evals" in md


def test_exit_codes_follow_the_contract():
    report = make()
    assert exit_code_for(report) == EXIT_FINDINGS
    clean = GapReport("x", "y")
    assert exit_code_for(clean) == EXIT_OK
    assert exit_code_for(clean, inconclusive=True) == EXIT_INCONCLUSIVE


def test_option_cost_tiers_are_the_three_this_plugin_uses():
    assert Option("1", "a").cost == "free"
    assert Option("1", "a", cost="judge").to_dict()["cost"] == "judge"
