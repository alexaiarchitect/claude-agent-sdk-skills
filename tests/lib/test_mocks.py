"""Mock MCP tool files: loading, grouping and the SIM/MCP findings."""

from __future__ import annotations

import pytest
from agent_sdk_skills.mocks import (
    MOCK_TYPES,
    iter_mocks,
    load_mock,
    mock_server_names,
    mock_summary,
    mock_tool_names,
    mocks_by_server,
    validate_mock,
    validate_mocks,
)


@pytest.fixture
def mocks_root(fixtures):
    return fixtures


@pytest.fixture
def good_evals(fixtures):
    return fixtures / "agents" / "good" / "evals"


def ids(findings):
    return sorted({f.id for f in findings})


# -- loading ---------------------------------------------------------------

def test_a_mock_takes_its_names_from_its_path(mocks_root):
    """The runner builds the server from the directory, so the path is the truth."""
    mock = load_mock(mocks_root / "mocks" / "library" / "lookup_book.md")
    assert mock.server == "library"
    assert mock.tool == "lookup_book"
    assert mock.qualified_name == "mcp__library__lookup_book"
    assert mock.ok


def test_a_mock_parses_its_frontmatter_and_body(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "library" / "lookup_book.md")
    assert mock.meta["schema"] == {"title": "str"}
    assert mock.meta["latency_ms"] == 40
    assert mock.meta["type"] == "canned"
    assert "{{input.title}}" in mock.body


def test_the_substitutions_a_body_uses_are_listed(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "library" / "reserve_book.md")
    assert set(mock.substitutions) == {"input.title", "input.member_id"}


def test_a_missing_file_is_an_error_not_an_exception(tmp_path):
    mock = load_mock(tmp_path / "library" / "absent.md")
    assert not mock.ok and "unreadable" in mock.errors[0]


def test_a_file_with_no_frontmatter_cannot_be_built(tmp_path):
    path = tmp_path / "library" / "x.md"
    path.parent.mkdir(parents=True)
    path.write_text("just a body\n")
    mock = load_mock(path)
    assert not mock.ok
    assert "schema" in mock.errors[0]


def test_mocks_are_grouped_by_server(mocks_root):
    grouped = mocks_by_server(mocks_root)
    assert set(grouped) == {"library", "broken"}
    assert sorted(m.tool for m in grouped["library"]) == [
        "cancel_reservation", "lookup_book", "reserve_book"]


def test_the_qualified_tool_names_are_what_the_model_sees(good_evals):
    assert mock_tool_names(good_evals) == {
        "mcp__library__lookup_book",
        "mcp__library__reserve_book",
        "mcp__library__cancel_reservation",
    }


def test_server_names_list_only_directories_with_files(good_evals):
    assert mock_server_names(good_evals) == ["library"]


def test_iter_mocks_on_a_directory_without_mocks_yields_nothing(tmp_path):
    assert list(iter_mocks(tmp_path)) == []
    assert mock_tool_names(tmp_path) == set()


def test_the_summary_describes_a_suites_mocks(good_evals):
    summary = mock_summary(good_evals)
    assert summary["servers"] == ["library"]
    assert summary["count"] == 3
    assert "lookup_book" in summary["tools"]["library"]


# -- SIM010: the schema ----------------------------------------------------

def test_a_mock_without_a_schema_is_an_error(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "broken" / "no_schema.md")
    findings = [f for f in validate_mock(mock) if f.id == "SIM010"]
    assert findings and findings[0].severity == "error"
    assert "validated against it before the handler runs" in findings[0].fix


def test_the_good_mocks_are_clean(good_evals):
    assert validate_mocks(good_evals, agent_servers={"library"}) == []


def test_a_substitution_the_schema_does_not_declare_warns(tmp_path):
    path = tmp_path / "library" / "x.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nschema:\n  title: str\n---\nfor {{input.member_id}}\n")
    findings = [f for f in validate_mock(load_mock(path)) if f.id == "SIM010"]
    assert findings and findings[0].severity == "warn"
    assert "member_id" in findings[0].message


def test_a_mock_with_no_body_and_no_error_warns(tmp_path):
    path = tmp_path / "library" / "x.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nschema:\n  title: str\n---\n")
    findings = [f for f in validate_mock(load_mock(path)) if f.id == "SIM010"]
    assert any("empty text" in f.message for f in findings)


# -- SIM011 / SIM012 / SIM013 ---------------------------------------------

def test_a_mock_with_both_an_error_and_a_body_is_ambiguous(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "broken" / "error_and_body.md")
    findings = [f for f in validate_mock(mock) if f.id == "SIM011"]
    assert findings and findings[0].severity == "error"
    assert "replaces the body" in findings[0].fix


def test_an_error_only_mock_is_fine(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "library" / "cancel_reservation.md")
    assert "SIM011" not in ids(validate_mock(mock))


def test_a_negative_latency_is_an_error(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "broken" / "bad_latency.md")
    findings = [f for f in validate_mock(mock) if f.id == "SIM012"]
    assert findings and findings[0].severity == "error"


def test_a_non_numeric_latency_is_an_error(tmp_path):
    path = tmp_path / "library" / "x.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nschema:\n  title: str\nlatency_ms: soon\n---\nbody\n")
    assert "SIM012" in ids(validate_mock(load_mock(path)))


def test_an_unknown_mock_type_is_an_error(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "broken" / "bad_type.md")
    findings = [f for f in validate_mock(mock) if f.id == "SIM013"]
    assert findings and findings[0].severity == "error"
    for name in MOCK_TYPES:
        assert name in findings[0].fix


# -- MCP020: a mock for a server the agent lacks ---------------------------

def test_a_mock_for_a_server_the_agent_lacks_warns(mocks_root):
    mock = load_mock(mocks_root / "mocks" / "library" / "lookup_book.md")
    findings = [f for f in validate_mock(mock, agent_servers={"catalog"}) if f.id == "MCP020"]
    assert findings and findings[0].severity == "warn"
    assert "never exercised" in findings[0].fix


def test_the_server_check_is_skipped_when_the_servers_are_unknown(mocks_root):
    """An empty set and 'we could not parse it' are different things."""
    mock = load_mock(mocks_root / "mocks" / "library" / "lookup_book.md")
    assert "MCP020" not in ids(validate_mock(mock, agent_servers=None))
    assert "MCP020" in ids(validate_mock(mock, agent_servers=set()))


def test_every_finding_cites_a_source(mocks_root):
    for name in ("no_schema", "error_and_body", "bad_latency", "bad_type"):
        mock = load_mock(mocks_root / "mocks" / "broken" / f"{name}.md")
        for finding in validate_mock(mock, agent_servers={"broken"}):
            assert finding.source, f"{name}: {finding.id}"
