"""Credential precedence, model policy and the interpreter chain."""

from pathlib import Path

from agent_sdk_skills import CLI_BUNDLED_WITH_TARGET, DEFAULT_MODEL, SDK_TARGET
from agent_sdk_skills.env import (
    CHECKED_AGAINST, CredentialInfo, classify_model_id, detect_credential,
    model_retirement_date, read_dotenv, resolve_runner, version_at_least,
    version_is_supported, version_newer_than_target,
)


def test_read_dotenv_handles_quotes_comments_and_export(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# c\nexport CLAUDE_MODEL="claude-sonnet-5-5"\nANTHROPIC_API_KEY=sk-x # trailing\n\n')
    assert read_dotenv(env) == {"CLAUDE_MODEL": "claude-sonnet-5-5", "ANTHROPIC_API_KEY": "sk-x"}


def test_api_key_wins_over_oauth_token_and_login(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    info = detect_credential(tmp_path, ask_cli=False)
    assert info.kind == "api_key" and info.cost_basis == "api_key"
    assert any("API key wins" in n for n in info.notes)
    assert info.values["ANTHROPIC_API_KEY"] == "<set>", "secrets never appear in reports"


def test_oauth_token_means_subscription(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    info = detect_credential(tmp_path, ask_cli=False)
    assert info.kind == "oauth_token" and info.cost_basis == "subscription"


def test_dotenv_values_count_but_the_process_environment_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    (tmp_path / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=from-file\nCLAUDE_MODEL=claude-opus-5-5\n")
    info = detect_credential(tmp_path, ask_cli=False)
    assert info.kind == "oauth_token" and info.source == str(tmp_path / ".env")
    assert info.model_env == "claude-opus-5-5"
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    assert detect_credential(tmp_path, ask_cli=False).model_env == "claude-sonnet-5-5"


def test_provider_switch_changes_the_cost_basis(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    info = detect_credential(tmp_path, ask_cli=False)
    assert info.kind == "provider" and info.provider == "bedrock" and info.cost_basis == "provider"


def test_no_credential_without_asking_the_cli(tmp_path, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS"):
        monkeypatch.delenv(key, raising=False)
    info = detect_credential(tmp_path, ask_cli=False)
    assert info.kind == "none" and not info.ready
    assert "setup-token" in info.describe()


def test_model_policy_grades():
    assert classify_model_id("sonnet") == "alias"
    assert classify_model_id(DEFAULT_MODEL) == "current"
    assert classify_model_id("claude-haiku-5-5") == "current", "Haiku 5.5 joined the current ids"
    assert classify_model_id("claude-sonnet-5-5-20260401") == "pinned", "a dated snapshot is not in the list"
    assert classify_model_id("claude-sonnet-4-5-20250929") == "deprecated", "retires 2026-11-30"
    assert classify_model_id("claude-haiku-4-5-20251001") == "retiring"
    assert classify_model_id("claude-opus-4-5-20251101") == "retiring"
    assert classify_model_id("claude-3-5-sonnet-20241022") == "retired"
    assert classify_model_id("claude-opus-4-1-20250805") == "retired"
    assert classify_model_id("gpt-5") == "unknown"
    assert classify_model_id(None) == "unknown"


def test_only_a_deprecated_id_reports_a_committed_retirement_date():
    """A `retiring` id has a floor, not a promise, so it reports no date."""
    assert model_retirement_date("claude-sonnet-4-5-20250929") == "2026-11-30"
    assert model_retirement_date("claude-haiku-4-5-20251001") is None
    assert model_retirement_date(DEFAULT_MODEL) is None
    assert model_retirement_date(None) is None


def test_the_checked_against_pins_are_reported_verbatim():
    assert CHECKED_AGAINST == {"sdk": SDK_TARGET, "cli": CLI_BUNDLED_WITH_TARGET}
    assert version_newer_than_target("0.2.166") and version_newer_than_target("0.3.0")
    assert not version_newer_than_target(SDK_TARGET), "equal is not newer"
    assert not version_newer_than_target("0.2.164")
    assert not version_newer_than_target(None), "unknown is not newer"


def test_version_comparison_is_numeric():
    assert version_at_least("0.2.165", "0.2.100")
    assert not version_at_least("0.2.99", "0.2.100"), "string comparison would get this wrong"
    assert version_is_supported("0.2.165") and not version_is_supported(None)


def test_explicit_interpreter_is_used_first(monkeypatch, fixtures):
    fake = fixtures / "bin" / "fake_sdk.py"
    monkeypatch.setenv("AGENT_SDK_PYTHON", str(fake))
    monkeypatch.setenv("FAKE_SDK_VERSION", "0.2.150")
    runner = resolve_runner(None, probe=True, allow_uv=False)
    assert runner.kind == "explicit" and runner.verified and runner.sdk_version == "0.2.150"


def test_missing_interpreter_says_how_to_get_one(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_SDK_PYTHON", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))     # nothing on PATH
    runner = resolve_runner(tmp_path, probe=True, allow_uv=False)
    assert not runner.available and "venv" in (runner.note or "")


def test_credential_description_is_plain_english():
    assert "subscription" in CredentialInfo(kind="login", plan="max").describe()
