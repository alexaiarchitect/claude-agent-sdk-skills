"""Discovery composes layout, credential and runner facts into one report."""

from agent_sdk_skills.discover import discover


def test_good_fixture_reports_gaps_not_errors(agent_dir, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    report = discover(agent_dir("good"), probe_runner=False, ask_cli=False)
    ids = report.ids()
    assert "ENV013" in ids, "subscription runs are labelled as estimates"
    errors = {f.id for f in report.findings if f.severity == "error"}
    assert errors <= {"DEP003"}, "the only acceptable error is the missing runner copy"
    assert report.discovered["layout"]["style"] == "convention"


def test_drift_fixture_reports_legacy_and_inline(agent_dir, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    report = discover(agent_dir("drift"), probe_runner=False, ask_cli=False)
    ids = report.ids()
    assert "AGT030" in ids and "AGT003" in ids and "ENV012" in ids


def test_no_evals_fixture_gets_the_scaffolding_option(agent_dir, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    report = discover(agent_dir("no_evals"), probe_runner=False, ask_cli=False)
    gap_ids = [g.id for g in report.gaps]
    assert "GAP-EVALS" in gap_ids
    recommended = [o for o in report.options if o.recommended]
    assert len(recommended) == 1 and "agent-create" in recommended[0].detail


def test_empty_directory_is_not_an_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    report = discover(tmp_path, probe_runner=False, ask_cli=False)
    assert [g.id for g in report.gaps] == ["GAP-AGENT"]
