"""Discovery composes layout, credential and runner facts into one report."""

from agent_sdk_skills import CLI_BUNDLED_WITH_TARGET, SDK_TARGET
from agent_sdk_skills.discover import discover


def test_good_fixture_reports_gaps_not_errors(isolated_agent, monkeypatch):
    # `isolated_agent`, not `agent_dir`: the credential has to be the one this
    # test sets, and a `.env` anywhere above the repository would outrank it.
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    report = discover(isolated_agent("good"), probe_runner=False, ask_cli=False)
    ids = report.ids()
    assert "ENV013" in ids, "subscription runs are labelled as estimates"
    errors = {f.id for f in report.findings if f.severity == "error"}
    assert errors <= {"DEP003"}, "the only acceptable error is the missing runner copy"
    assert report.discovered["layout"]["style"] == "convention"


def test_drift_fixture_reports_legacy_and_inline(isolated_agent, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    report = discover(isolated_agent("drift"), probe_runner=False, ask_cli=False)
    ids = report.ids()
    assert "AGT030" in ids and "AGT003" in ids and "ENV012" in ids


def test_no_evals_fixture_gets_the_scaffolding_option(isolated_agent, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    report = discover(isolated_agent("no_evals"), probe_runner=False, ask_cli=False)
    gap_ids = [g.id for g in report.gaps]
    assert "GAP-EVALS" in gap_ids
    recommended = [o for o in report.options if o.recommended]
    assert len(recommended) == 1 and "agent-create" in recommended[0].detail


def test_empty_directory_is_not_an_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    report = discover(tmp_path, probe_runner=False, ask_cli=False)
    assert [g.id for g in report.gaps] == ["GAP-AGENT"]


# -- the pins the plugin was checked against -------------------------------

def test_the_environment_block_reports_what_the_plugin_was_checked_against(
    agent_dir, fake_sdk, monkeypatch,
):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    report = discover(agent_dir("good"), probe_runner=True, ask_cli=False)
    env = report.discovered["environment"]
    assert env["checked_against"] == {"sdk": SDK_TARGET, "cli": CLI_BUNDLED_WITH_TARGET}
    assert env["sdk_version"] == SDK_TARGET, "the fake interpreter answers with the target"
    assert env["sdk_newer_than_checked"] is False
    assert "ENV003" not in report.ids(), "the target itself is not newer than the target"


def test_an_sdk_newer_than_the_target_is_info_never_an_error(agent_dir, fake_sdk, monkeypatch):
    """0.2.166+ is expected to work; what is not known is whether the pins still hold."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    monkeypatch.setenv("FAKE_SDK_VERSION", "0.2.200")
    report = discover(agent_dir("good"), probe_runner=True, ask_cli=False)
    assert report.discovered["environment"]["sdk_newer_than_checked"] is True
    finding = next(f for f in report.findings if f.id == "ENV003")
    assert finding.severity == "info"
    assert SDK_TARGET in finding.message and "0.2.200" in finding.message
    assert "sync checker" in finding.message
    assert not [f for f in report.findings if f.id == "ENV002"], "newer is not older"
