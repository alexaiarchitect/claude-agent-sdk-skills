"""`agent-deploy`: the `HST0xx` band, and two generators that ship no secrets.

The `deploy_ready` fixture is deliberately clean, so each test here plants
exactly one problem in a copy of it and watches exactly one finding appear.
"""

from __future__ import annotations

import json

import pytest

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE

CHECK = "skills/agent-deploy/scripts/deploy_check.py"
GEN_DOCKERFILE = "skills/agent-deploy/scripts/gen_dockerfile.py"
GEN_SETTINGS = "skills/agent-deploy/scripts/gen_secure_settings.py"


def ids_of(result) -> set[str]:
    return {finding["id"] for finding in json.loads(result.stdout)["findings"]}


@pytest.fixture
def check(run_script):
    def _run(project, *args: str):
        return run_script(CHECK, str(project), "--json", *args)

    return _run


# -- the clean case -------------------------------------------------------

def test_the_deploy_ready_fixture_comes_back_clean(check, agent_dir):
    result = check(agent_dir("deploy_ready"))
    assert ids_of(result) == set()
    assert result.returncode == EXIT_OK


def test_a_laptop_agent_is_not_judged_as_a_hosted_one(check, agent_dir):
    """No container definition means no hosting claims, so only the advisory
    telemetry note applies."""
    found = ids_of(check(agent_dir("good")))
    assert found == {"HST030"}
    assert not any(i in found for i in ("HST001", "HST002", "HST020"))


# -- credentials ----------------------------------------------------------

def test_a_subscription_token_beside_a_dockerfile_is_an_error(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    (project / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-abcdefghijkl\n")
    result = check(project)
    assert "HST001" in ids_of(result)
    assert result.returncode == EXIT_FINDINGS
    message = next(f for f in json.loads(result.stdout)["findings"] if f["id"] == "HST001")
    assert "third-party" in message["fix"] or "third party" in message["fix"]


def test_no_credential_path_at_all_is_an_error(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    for name in (".env.example", "compose.yaml"):
        (project / name).unlink()
    dockerfile = (project / "Dockerfile").read_text()
    (project / "Dockerfile").write_text(dockerfile.replace("ANTHROPIC_BASE_URL", "NOTHING"))
    assert "HST002" in ids_of(check(project))


def test_a_key_literal_in_a_dockerfile_is_an_error(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    with (project / "Dockerfile").open("a") as handle:
        handle.write("\nENV ANTHROPIC_API_KEY=sk-ant-api03-notarealkeybutaliteral\n")
    result = check(project)
    assert "HST040" in ids_of(result)
    assert result.returncode == EXIT_FINDINGS


def test_a_key_literal_in_a_compose_file_is_an_error(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    with (project / "compose.yaml").open("a") as handle:
        handle.write("      ANTHROPIC_API_KEY: sk-ant-api03-alsonotreal\n")
    assert "HST040" in ids_of(check(project))


def test_an_environment_reference_is_not_mistaken_for_a_literal(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    with (project / "compose.yaml").open("a") as handle:
        handle.write("      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}\n")
    assert "HST040" not in ids_of(check(project))


def test_copying_dotenv_into_the_image_is_an_error(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    dockerfile = (project / "Dockerfile").read_text()
    (project / "Dockerfile").write_text(dockerfile.replace("COPY agent.py ./",
                                                           "COPY agent.py .env ./"))
    assert "HST041" in ids_of(check(project))


def test_copying_everything_while_a_dotenv_exists_is_an_error(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    (project / ".env").write_text("ANTHROPIC_BASE_URL=http://gw.internal:8080\n")
    dockerfile = (project / "Dockerfile").read_text()
    (project / "Dockerfile").write_text(dockerfile.replace("COPY agent.py ./", "COPY . ."))
    assert "HST041" in ids_of(check(project))


# -- ceilings, isolation, telemetry, state -------------------------------

@pytest.mark.parametrize("removed,expected", [
    ("        max_turns=6,\n", "HST010"),
    ("        max_budget_usd=0.50,\n", "HST011"),
    ("        setting_sources=[],\n", "HST020"),
    ('        cwd=str(session_dir(session_id)),\n', "HST022"),
])
def test_removing_one_guard_produces_one_finding(check, tmp_agent, removed, expected):
    project = tmp_agent("deploy_ready")
    source = (project / "agent.py").read_text()
    assert removed in source
    (project / "agent.py").write_text(source.replace(removed, ""))
    assert expected in ids_of(check(project))


def test_auto_memory_not_disabled_is_informational(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    for name in ("Dockerfile", "agent.py", ".env.example"):
        path = project / name
        path.write_text(path.read_text().replace("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "UNUSED_VAR"))
    findings = json.loads(check(project).stdout)["findings"]
    hst021 = [f for f in findings if f["id"] == "HST021"]
    assert hst021 and hst021[0]["severity"] == "info"


def test_subagents_without_caps_are_informational(check, agent_dir):
    assert "HST012" in ids_of(check(agent_dir("subagents")))


def test_otel_exporters_without_the_switch_are_a_warning(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    dockerfile = (project / "Dockerfile").read_text()
    (project / "Dockerfile").write_text(
        dockerfile.replace("ENV CLAUDE_CODE_ENABLE_TELEMETRY=1 \\", "ENV \\")
    )
    findings = {f["id"]: f["severity"] for f in json.loads(check(project).stdout)["findings"]}
    assert findings.get("HST030") == "warn"


def test_a_resumable_design_without_a_session_store_is_informational(check, tmp_agent):
    project = tmp_agent("deploy_ready")
    source = (project / "agent.py").read_text()
    (project / "agent.py").write_text(
        source.replace("        max_turns=6,", "        resume=session_id,\n        max_turns=6,")
    )
    assert "HST050" in ids_of(check(project))


def test_a_directory_with_no_agent_exits_two(run_script, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n")
    assert run_script(CHECK, str(tmp_path)).returncode == EXIT_USAGE


def test_the_found_block_records_the_credential_style_and_the_ceilings(check, agent_dir):
    discovered = json.loads(check(agent_dir("deploy_ready")).stdout)["discovered"]
    assert "ANTHROPIC_BASE_URL" in discovered["credential"]["api_style"]
    assert discovered["credential"]["subscription_style"] == []
    assert discovered["ceilings"]["max_budget_usd"] == 0.5
    assert discovered["isolation"]["per_session_cwd"] is True


# -- gen_dockerfile -------------------------------------------------------

def test_dockerfile_dry_run_writes_nothing(run_script, tmp_path):
    result = run_script(GEN_DOCKERFILE, str(tmp_path), "--dry-run")
    assert result.returncode == EXIT_OK
    assert "Write plan" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_the_generated_dockerfile_follows_the_content_rules(run_script, tmp_path):
    assert run_script(GEN_DOCKERFILE, str(tmp_path)).returncode == EXIT_OK
    dockerfile = (tmp_path / "Dockerfile").read_text()
    assert "FROM python:3.12-slim" in dockerfile
    assert "useradd" in dockerfile and "USER agent" in dockerfile
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "OTEL_TRACES_EXPORTER" in dockerfile
    assert "# ENV CLAUDE_CODE_ENABLE_TELEMETRY=1" in dockerfile, "telemetry is commented"
    copy_lines = [line for line in dockerfile.splitlines()
                  if line.strip().upper().startswith(("COPY ", "ADD "))]
    assert copy_lines and all(".env" not in line and not line.strip().endswith(". .")
                              for line in copy_lines)
    assert "sk-ant-" not in dockerfile
    assert "claude-agent-sdk" in (tmp_path / "requirements.txt").read_text()
    assert ".env" in (tmp_path / ".dockerignore").read_text()


def test_the_generated_dockerfile_passes_the_deploy_check(run_script, tmp_agent):
    project = tmp_agent("deploy_ready")
    (project / "Dockerfile").unlink()
    (project / "compose.yaml").unlink()
    assert run_script(GEN_DOCKERFILE, str(project)).returncode == EXIT_OK
    result = run_script(CHECK, str(project), "--json")
    assert ids_of(result) == set(), "the generator and the checker must agree"


def test_an_unsupported_python_version_is_refused(run_script, tmp_path):
    result = run_script(GEN_DOCKERFILE, str(tmp_path), "--python", "3.9")
    assert result.returncode != EXIT_OK
    assert list(tmp_path.iterdir()) == []


def test_existing_files_are_skipped_until_force(run_script, tmp_path):
    run_script(GEN_DOCKERFILE, str(tmp_path))
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / ".dockerignore").unlink()
    (tmp_path / "requirements.txt").unlink()

    second = run_script(GEN_DOCKERFILE, str(tmp_path))
    assert (tmp_path / "Dockerfile").read_text() == "FROM scratch\n"
    assert "skip" in second.stdout

    run_script(GEN_DOCKERFILE, str(tmp_path), "--force")
    assert "FROM python:3.12-slim" in (tmp_path / "Dockerfile").read_text()


# -- gen_secure_settings --------------------------------------------------

def test_settings_dry_run_writes_nothing(run_script, tmp_path):
    result = run_script(GEN_SETTINGS, str(tmp_path), "--dry-run")
    assert result.returncode == EXIT_OK
    assert list(tmp_path.iterdir()) == []


def test_the_generated_settings_lock_the_agent_down(run_script, tmp_path):
    assert run_script(GEN_SETTINGS, str(tmp_path), "--allow", "mcp__library__*").returncode == EXIT_OK
    settings = json.loads((tmp_path / "agent_settings.json").read_text())
    assert settings["permissions"]["defaultMode"] == "dontAsk"
    assert settings["permissions"]["allow"] == ["mcp__library__*"]
    assert "Bash" in settings["permissions"]["deny"]
    assert settings["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert "egress" in settings["$comment"]


def test_the_generated_env_example_carries_no_credential_value(run_script, tmp_path):
    run_script(GEN_SETTINGS, str(tmp_path))
    example = (tmp_path / ".env.deploy.example").read_text()
    assert "ANTHROPIC_API_KEY=" in example
    assert "sk-ant-" not in example
    assert "CLAUDE_CODE_OAUTH_TOKEN=" not in example, "a subscription token is not an option here"
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1" in example
    assert "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH" in example


def test_the_snippet_names_the_three_isolation_options(run_script, tmp_path):
    result = run_script(GEN_SETTINGS, str(tmp_path), "--dry-run", "--json")
    snippet = json.loads(result.stdout)["snippet"]
    for option in ("setting_sources=[]", "strict_mcp_config=True", "cwd="):
        assert option in snippet


def test_a_missing_directory_is_refused(run_script, tmp_path):
    assert run_script(GEN_SETTINGS, str(tmp_path / "nope")).returncode == EXIT_USAGE
