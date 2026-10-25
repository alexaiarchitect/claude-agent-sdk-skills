"""`agent-design`: the design checker, the brief, and the skill's own files.

`design_check.py` is held to two fixtures. `tool_design` was built to trip
every DSG rule once, so all eight ids must appear; `good` is the plugin's clean
convention agent, so nothing at warn or above may appear on it. Every finding
must say where its rule comes from: one of the cited Anthropic articles and a
`code.claude.com` page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILL = PLUGIN_ROOT / "skills" / "agent-design"
CHECK = "skills/agent-design/scripts/design_check.py"
BRIEF = "skills/agent-design/scripts/design_brief.py"
ALL_IDS = {f"DSG00{n}" for n in range(1, 9)}
AGENT_FIXTURES = sorted(p.name for p in (PLUGIN_ROOT / "tests" / "fixtures" / "agents").iterdir()
                        if p.is_dir())

#: The fourteen articles of the 2026-10-29 sync, by canonical URL.
CANONICAL_ARTICLES = (
    "https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk",
    "https://www.anthropic.com/research/building-effective-agents",
    "https://www.anthropic.com/research/effective-context-engineering-for-ai-agents",
    "https://www.anthropic.com/research/writing-tools-for-agents",
    "https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills",
    "https://www.anthropic.com/research/code-execution-with-mcp",
    "https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop",
    "https://www.anthropic.com/research/effective-harnesses-for-long-running-agents",
    "https://www.anthropic.com/research/harness-design-long-running-apps",
    "https://www.anthropic.com/research/multi-agent-research-system",
    "https://www.anthropic.com/research/managed-agents",
    "https://www.anthropic.com/research/claude-code-auto-mode",
    "https://www.anthropic.com/research/claude-code-sandboxing",
    "https://www.anthropic.com/research/infrastructure-noise",
)


@pytest.fixture
def check(run_script, agent_dir):
    def _run(name: str, *args: str):
        return run_script(CHECK, str(agent_dir(name)), *args)

    return _run


@pytest.fixture
def brief(run_script, agent_dir):
    def _run(name: str, *args: str):
        return run_script(BRIEF, str(agent_dir(name)), *args)

    return _run


# -- design_check.py --------------------------------------------------------

def test_the_tool_design_fixture_trips_every_rule(check):
    result = check("tool_design", "--json")
    assert result.returncode == EXIT_FINDINGS, result.stderr
    found = {f["id"] for f in result.json()["findings"]}
    assert found == ALL_IDS, f"missing {sorted(ALL_IDS - found)}, extra {sorted(found - ALL_IDS)}"


@pytest.mark.parametrize("fid,needle", [
    ("DSG001", "`lookup`"),
    ("DSG002", "`lookup`"),
    ("DSG003", "`list_books`"),
    ("DSG004", "`catalog`"),
    ("DSG005", "`find_book`"),
    ("DSG006", "32 tool definitions"),
    ("DSG007", "`catalog-search`"),
    ("DSG008", "max_turns"),
])
def test_each_finding_names_what_triggered_it(check, fid, needle):
    findings = [f for f in check("tool_design", "--json").json()["findings"] if f["id"] == fid]
    assert findings and any(needle in f["message"] for f in findings)


def test_the_overlap_finding_groups_all_three_read_tools(check):
    overlap = [f for f in check("tool_design", "--json").json()["findings"] if f["id"] == "DSG005"]
    assert len(overlap) == 1
    for name in ("lookup", "find_book", "search_books"):
        assert f"`{name}`" in overlap[0]["message"]


def test_severities_are_warn_for_tools_and_info_for_subagents_and_long_runs(check):
    by_id = {f["id"]: f["severity"] for f in check("tool_design", "--json").json()["findings"]}
    assert {by_id[f"DSG00{n}"] for n in range(1, 7)} == {"warn"}
    assert by_id["DSG007"] == by_id["DSG008"] == "info"


def test_the_good_fixture_has_no_warning(check):
    result = check("good", "--json")
    assert result.returncode == EXIT_OK, result.stdout
    assert [f for f in result.json()["findings"] if f["severity"] != "info"] == []


def test_strict_counts_notes_too(check):
    assert check("good", "--strict").returncode == EXIT_FINDINGS
    assert check("tool_design", "--strict").returncode == EXIT_FINDINGS


def test_the_json_carries_path_findings_and_summary(check):
    data = check("tool_design", "--json").json()
    assert {"path", "findings", "summary", "discovered"} <= set(data)
    assert data["summary"] == {"errors": 0, "warnings": 6, "infos": 2}
    for finding in data["findings"]:
        assert {"id", "severity", "message", "fix", "source"} <= set(finding)
    assert data["discovered"]["reachable_tools"] == 32


def test_every_source_cites_an_article_and_the_docs(check):
    for finding in check("tool_design", "--json").json()["findings"]:
        source = finding["source"]
        assert any(url in source for url in CANONICAL_ARTICLES), finding["id"]
        assert "https://code.claude.com/docs/en/" in source, finding["id"]
        assert re.search(r'\("[^"]+", \d{4}-\d{2}-\d{2}, ', source), finding["id"]
        assert "anthropic.com/engineering/" not in source


def test_the_markdown_report_prints_every_source(check):
    text = check("tool_design").stdout
    assert text.count("Source: ") == 8


def test_a_file_that_does_not_parse_is_a_usage_error(run_script, tmp_path):
    broken = tmp_path / "agent.py"
    broken.write_text("from claude_agent_sdk import ClaudeAgentOptions\n"
                      "def build_options(:\n    return ClaudeAgentOptions()\n")
    for script in (CHECK, BRIEF):
        result = run_script(script, str(broken))
        assert result.returncode == EXIT_USAGE
        assert "could not parse" in result.stderr


def test_a_missing_path_or_a_project_without_the_sdk_is_a_usage_error(run_script, tmp_path):
    (tmp_path / "plain.py").write_text("print('no agent here')\n")
    assert run_script(CHECK, str(tmp_path / "absent")).returncode == EXIT_USAGE
    assert run_script(CHECK, str(tmp_path)).returncode == EXIT_USAGE


@pytest.mark.parametrize("fixture", AGENT_FIXTURES)
def test_both_scripts_run_on_every_fixture(run_script, agent_dir, fixture):
    for script in (CHECK, BRIEF):
        result = run_script(script, str(agent_dir(fixture)), "--json")
        assert result.returncode in (EXIT_OK, EXIT_FINDINGS), result.stderr
        assert "Traceback" not in result.stderr
        json.loads(result.stdout)


# -- design_brief.py --------------------------------------------------------

def test_the_brief_has_its_four_sections_and_a_sources_line(brief):
    result = brief("tool_design")
    assert result.returncode == EXIT_OK
    for heading in ("## 1. Tool inventory", "## 2. Subagents: keep or fold",
                    "## 3. Verification ladder", "## 4. Long-running checklist"):
        assert heading in result.stdout
    assert "### `catalog-search`" in result.stdout
    assert "Fold procedure:" in result.stdout
    assert "\nSources: " in result.stdout


def test_the_brief_json_carries_the_same_structure(brief):
    data = brief("tool_design", "--json").json()
    assert {"path", "tools", "subagents", "no_subagents", "fold_procedure",
            "verification_ladder", "long_running", "sources", "findings"} <= set(data)
    assert [t["name"] for t in data["tools"]] == [
        "list_books", "lookup", "find_book", "search_books", "place_hold"]
    lookup = next(t for t in data["tools"] if t["name"] == "lookup")
    assert {"DSG001", "DSG002", "DSG005"} <= set(lookup["findings"])
    assert data["subagents"][0]["name"] == "catalog-search"
    assert data["subagents"][0]["states_output"] is False
    assert [r["rung"][0] for r in data["verification_ladder"]] == ["1", "2", "3"]
    assert "llm" in data["verification_ladder"][2]["graders"]
    assert any(url in " ".join(data["sources"]) for url in CANONICAL_ARTICLES)


def test_the_brief_says_when_there_are_no_subagents(brief):
    data = brief("good", "--json").json()
    assert data["subagents"] == [] and data["no_subagents"]["applies"] is True
    assert "No subagents" in brief("good").stdout


def test_the_brief_marks_undetectable_items_ask(brief):
    rows = brief("tool_design", "--json").json()["long_running"]
    assert {row["status"] for row in rows} <= {"yes", "no", "ask"}
    assert any(row["status"] == "ask" for row in rows)
    ceiling = rows[0]
    assert ceiling["status"] == "no" and "plus one" in ceiling["why"]


def test_neither_script_writes(run_script, tmp_agent):
    project = tmp_agent("tool_design")
    before = sorted(p.relative_to(project) for p in project.rglob("*"))
    for script in (CHECK, BRIEF):
        run_script(script, str(project))
        run_script(script, str(project), "--json")
    assert sorted(p.relative_to(project) for p in project.rglob("*")) == before


# -- the skill's own files ---------------------------------------------------

def test_the_skill_body_fits_and_routes_away_what_it_does_not_do():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 200
    assert "name: agent-design" in text
    for other in ("/agent-sdk:agent-harness", "/agent-sdk:agent-review", "/agent-sdk:agent-debug",
                  "/agent-sdk:agent-deploy", "/agent-sdk-dev:new-sdk-app"):
        assert other in text
    assert "## Completion checklist" in text


REFERENCES = sorted((SKILL / "references").glob("*.md"))


def test_there_are_five_references():
    assert [p.name for p in REFERENCES] == [
        "agent-loop.md", "context-engineering.md", "long-running-harness.md",
        "subagent-decisions.md", "tool-design.md"]


@pytest.mark.parametrize("reference", REFERENCES, ids=lambda p: p.name)
def test_each_reference_is_sized_and_ends_in_a_dated_footer(reference):
    text = reference.read_text(encoding="utf-8")
    assert 25 <= len(text.splitlines()) <= 250
    footer = text[text.rindex("Sources:"):]
    assert footer.rstrip().endswith((".", ")", "`"))
    assert "anthropic.com/engineering/" not in text
    urls = list(re.finditer(r"https://\S+", footer))
    for match, following in zip(urls, [*urls[1:], None]):
        # Articles and docs pages alike: "(..., YYYY-MM-DD, ...)" before the next URL.
        segment = footer[match.end():following.start() if following else len(footer)]
        assert re.match(r"\s*\(.*?\d{4}-\d{2}-\d{2}", segment, re.DOTALL), f"undated: {match.group(0)}"
    assert "code.claude.com/docs/en/" in footer
    assert any(url in footer for url in CANONICAL_ARTICLES)
    assert "re-read" in footer or "Written 2026-10-29" in footer


def test_every_reference_has_an_in_this_plugin_section():
    for reference in REFERENCES:
        assert "## In this plugin" in reference.read_text(encoding="utf-8"), reference.name


def test_the_plugin_eval_case_points_at_the_fixture_and_the_scripts():
    case = PLUGIN_ROOT / "plugin-evals" / "design-review"
    assert "tool_design" in (case / "scaffold.sh").read_text(encoding="utf-8")
    assert "design_check" in (case / "graders" / "check-ran.md").read_text(encoding="utf-8")
    assert "agent-design" in (case / "graders" / "skill-fired.md").read_text(encoding="utf-8")
    criteria = (case / "graders" / "criteria.md").read_text(encoding="utf-8")
    for needle in ("DSG003", "DSG005", "DSG002", "agent-sdk/subagents", "focus: trace"):
        assert needle in criteria
