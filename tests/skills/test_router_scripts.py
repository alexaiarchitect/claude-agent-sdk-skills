"""The router scripts, run the way a skill runs them."""

import json


def test_discover_prints_a_report_and_exits_clean_on_the_good_fixture(run_script, isolated_agent,
                                                                     fake_sdk):
    # `isolated_agent` puts the project outside this repository: a `.env`
    # anywhere above the checkout is read as the project's credential and would
    # make `cost_basis` depend on the developer's machine.
    result = run_script("skills/agent-sdk/scripts/discover.py", isolated_agent("good"),
                        "--json", "--no-cli", env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    assert result.returncode in (0, 1), result.stderr
    doc = result.json()
    assert doc["schema"] == "agent-sdk-skills.gap-report/1"
    assert doc["discovered"]["environment"]["sdk_version"] == "0.2.174", "the fake interpreter answered the probe"
    assert doc["discovered"]["environment"]["cost_basis"] == "subscription"


def test_discover_rejects_a_missing_target(run_script):
    result = run_script("skills/agent-sdk/scripts/discover.py", "/nonexistent/path")
    assert result.returncode == 2 and "does not exist" in result.stderr


def test_discover_rejects_an_unknown_focus(run_script, agent_dir):
    result = run_script("skills/agent-sdk/scripts/discover.py", agent_dir("good"), "--focus", "nope", "--no-probe", "--no-cli")
    assert result.returncode == 2


def test_check_env_is_blocked_without_any_credential(run_script, isolated_agent, fake_sdk):
    """"No credential" has to mean no credential anywhere, the environment included."""
    result = run_script("skills/agent-sdk/scripts/check_env.py", isolated_agent("no_evals"),
                        "--json", "--no-cli")
    doc = result.json()
    assert result.returncode == 1 and not doc["ready"]
    assert any("credential" in b for b in doc["blockers"])


def test_check_env_is_ready_with_a_token_and_the_fake_sdk(run_script, isolated_agent, fake_sdk):
    result = run_script("skills/agent-sdk/scripts/check_env.py", isolated_agent("good"),
                        "--json", "--no-cli", env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    doc = result.json()
    assert result.returncode == 0 and doc["ready"], doc["blockers"]
    assert doc["runner"]["sdk_version"] == "0.2.174"
    assert doc["model"]["grade"] == "current", "Sonnet 5.5 is a current id, not just a pinned one"


def test_inventory_lists_every_fixture_project(run_script, fixtures):
    result = run_script("skills/agent-sdk/scripts/inventory.py", fixtures / "agents", "--json")
    assert result.returncode == 0
    rows = {r["project"]: r for r in json.loads(result.stdout)["projects"]}
    assert {"good", "drift", "no_evals"} <= set(rows)
    assert rows["drift"]["legacy_sdk"] is True
    assert rows["good"]["style"] == "convention"
