"""`agent-harness`: the wiring linter, and three generators that never surprise.

The generators are held to one rule above all: `--dry-run` writes nothing and
shows exactly what it would have written.
"""

from __future__ import annotations

import json

import pytest

from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE

LINT = "skills/agent-harness/scripts/lint_harness.py"
GEN_HOOK = "skills/agent-harness/scripts/gen_hook.py"
GEN_MCP = "skills/agent-harness/scripts/gen_mcp_config.py"
GEN_SUBAGENT = "skills/agent-harness/scripts/gen_subagent.py"


def ids_of(result) -> set[str]:
    return {finding["id"] for finding in json.loads(result.stdout)["findings"]}


def gaps_of(result) -> set[str]:
    return {gap["id"] for gap in json.loads(result.stdout)["gaps"]}


@pytest.fixture
def lint(run_script, agent_dir):
    def _run(name: str, *args: str):
        return run_script(LINT, str(agent_dir(name)), "--json", *args)

    return _run


# -- the linter -----------------------------------------------------------

@pytest.mark.parametrize("fixture,expected", [
    ("hooks_bad", {"HOK001", "HOK002", "HOK003", "HOK010", "HOK020", "HOK030"}),
    ("external_mcp", {"MCP001", "MCP002", "OPT001"}),
    ("subagents", {"SUB001", "SUB002", "SUB003", "SUB010"}),
    ("good", set()),
    ("deploy_ready", set()),
])
def test_each_fixture_reports_the_wiring_it_was_built_for(lint, fixture, expected):
    found = ids_of(lint(fixture))
    assert expected <= found, f"missing {sorted(expected - found)}"


def test_wiring_errors_fail_and_a_clean_harness_does_not(lint):
    assert lint("hooks_bad").returncode == EXIT_FINDINGS
    assert lint("good").returncode == EXIT_OK


def test_absences_are_reported_as_gaps_not_findings(lint):
    assert {"GAP-HOOKS", "GAP-SUBAGENTS"} <= gaps_of(lint("good"))
    assert "GAP-HOOKS" not in gaps_of(lint("hooks_bad"))


def test_the_linter_stays_out_of_the_review_skills_territory(lint):
    found = ids_of(lint("drift"))
    assert not any(i.startswith("AGT") for i in found), "model and entry point belong to agent-review"


def test_hooks_without_include_hook_events_is_an_informational_finding(run_script, tmp_agent):
    project = tmp_agent("hooks_bad")
    source = (project / "agent.py").read_text()
    (project / "agent.py").write_text(source.replace("        include_hook_events=True,\n", ""))
    assert "HOK031" in ids_of(run_script(LINT, str(project), "--json"))


def test_the_found_block_lists_every_matcher_and_server(lint):
    discovered = json.loads(lint("hooks_bad").stdout)["discovered"]
    assert discovered["hooks"]["unsupported_events"] == ["SessionStart"]
    assert discovered["context"]["setting_sources"] == []
    discovered = json.loads(lint("external_mcp").stdout)["discovered"]
    kinds = {s["name"]: s["kind"] for s in discovered["mcp"]["servers"]}
    assert kinds == {"catalogue": "stdio", "members": "http"}


def test_a_directory_with_no_agent_exits_two(run_script, tmp_path):
    (tmp_path / "readme.md").write_text("nothing\n")
    assert run_script(LINT, str(tmp_path)).returncode == EXIT_USAGE


def test_naming_one_module_reviews_that_module_alone(run_script, tmp_path):
    """A sweep over a directory of unrelated examples must not attribute one
    file's subagents to its neighbours."""
    (tmp_path / "with_agents.py").write_text(
        "from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions\n\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(allowed_tools=['Agent'], agents={\n"
        "        'helper': AgentDefinition(description='d', prompt='p', tools=['Read'])})\n"
    )
    (tmp_path / "no_agents.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(max_turns=2, tools=[])\n"
    )
    assert "SUB003" in ids_of(run_script(LINT, str(tmp_path / "with_agents.py"), "--json"))
    neighbour = ids_of(run_script(LINT, str(tmp_path / "no_agents.py"), "--json"))
    assert not any(i.startswith("SUB") for i in neighbour), neighbour
    assert "OPT040" not in neighbour


def test_a_return_of_only_common_fields_is_not_a_hook_finding(run_script, tmp_path):
    """`continue_`/`stopReason` are accepted on every event, so a hook that
    halts a turn that way is correct, not malformed."""
    (tmp_path / "agent.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions, HookMatcher\n\n"
        "async def halt(input_data, tool_use_id, context):\n"
        "    return {'continue_': False, 'stopReason': 'critical error'}\n\n"
        "def build_options():\n"
        "    return ClaudeAgentOptions(tools=[], include_hook_events=True,\n"
        "        hooks={'PostToolUse': [HookMatcher(matcher='Read', hooks=[halt])]})\n"
    )
    assert "HOK002" not in ids_of(run_script(LINT, str(tmp_path), "--json"))


# -- gen_hook -------------------------------------------------------------

def test_dry_run_writes_nothing_and_prints_the_plan(run_script, tmp_path):
    result = run_script(GEN_HOOK, "--event", "PreToolUse", "--purpose", "deny",
                        "--tool", "Bash", "--dry-run", cwd=tmp_path)
    assert result.returncode == EXIT_OK
    assert "Write plan" in result.stdout
    assert "not written" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_a_real_run_writes_the_file(run_script, tmp_path):
    result = run_script(GEN_HOOK, "--event", "PreToolUse", "--purpose", "deny",
                        "--tool", "Bash", cwd=tmp_path)
    assert result.returncode == EXIT_OK
    written = tmp_path / "hooks" / "pre_tool_use_deny.py"
    assert written.is_file()
    source = written.read_text()
    assert "async def deny_pre_tool_use(input_data, tool_use_id, context):" in source
    assert '"hookEventName": "PreToolUse"' in source
    assert '"permissionDecisionReason"' in source, "a deny without a reason is HOK010"


def test_an_existing_file_is_skipped_until_force_is_given(run_script, tmp_path):
    args = (GEN_HOOK, "--event", "PostToolUse", "--purpose", "audit")
    assert run_script(*args, cwd=tmp_path).returncode == EXIT_OK
    written = tmp_path / "hooks" / "post_tool_use_audit.py"
    written.write_text("# edited by hand\n")

    second = run_script(*args, cwd=tmp_path)
    assert second.returncode == EXIT_FINDINGS
    assert "skip" in second.stdout
    assert written.read_text() == "# edited by hand\n"

    third = run_script(*args, "--force", cwd=tmp_path)
    assert third.returncode == EXIT_OK
    assert "async def audit_post_tool_use" in written.read_text()


def test_an_event_the_python_sdk_does_not_have_is_refused(run_script, tmp_path):
    result = run_script(GEN_HOOK, "--event", "SessionStart", "--purpose", "inject",
                        cwd=tmp_path)
    assert result.returncode == EXIT_USAGE
    assert "TypeScript-only" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_an_event_that_cannot_deny_is_refused(run_script, tmp_path):
    result = run_script(GEN_HOOK, "--event", "Notification", "--purpose", "deny",
                        cwd=tmp_path)
    assert result.returncode == EXIT_USAGE
    assert "permission decision" in result.stderr


def test_a_stop_hook_gets_no_hook_specific_output(run_script, tmp_path):
    run_script(GEN_HOOK, "--event", "Stop", "--purpose", "deny", cwd=tmp_path)
    source = (tmp_path / "hooks" / "stop_deny.py").read_text()
    assert '"hookSpecificOutput"' not in source, "Stop has no such output type"
    assert '"decision": "block"' in source


def test_latency_puts_the_probability_inside_the_callback(run_script, tmp_path):
    run_script(GEN_HOOK, "--event", "PreToolUse", "--purpose", "latency",
               "--probability", "0.5", "--seed", "7", cwd=tmp_path)
    source = (tmp_path / "hooks" / "pre_tool_use_latency.py").read_text()
    assert "PROBABILITY = 0.5" in source
    assert "random.Random(7)" in source
    assert "HookMatcher` has no probability field" in source or "no probability field" in source


def test_a_probability_outside_the_range_is_refused(run_script, tmp_path):
    result = run_script(GEN_HOOK, "--event", "PreToolUse", "--purpose", "latency",
                        "--probability", "2", cwd=tmp_path)
    assert result.returncode == EXIT_USAGE


def test_generated_hooks_pass_the_linter(run_script, tmp_agent, tmp_path):
    """The generator and the checker have to agree, or one of them is wrong."""
    import ast

    run_script(GEN_HOOK, "--event", "PreToolUse", "--purpose", "deny", cwd=tmp_path)
    run_script(GEN_HOOK, "--event", "PostToolUse", "--purpose", "inject", cwd=tmp_path)
    for generated in (tmp_path / "hooks").glob("*.py"):
        ast.parse(generated.read_text())     # it is valid Python
        assert "async def" in generated.read_text()


# -- gen_mcp_config -------------------------------------------------------

def test_a_stdio_server_becomes_a_python_snippet(run_script, tmp_path):
    result = run_script(GEN_MCP, "--server", "github", "--command", "npx",
                        "--arg=-y", "--arg=@modelcontextprotocol/server-github",
                        cwd=tmp_path)
    assert result.returncode == EXIT_OK
    source = (tmp_path / "mcp_servers_github.py").read_text()
    assert '"command": "npx"' in source
    assert '"-y"' in source
    assert 'ALLOWED_TOOLS = ["mcp__github__*"]' in source
    assert "strict_mcp_config" in source


def test_a_url_server_becomes_an_mcp_json_file(run_script, tmp_path):
    result = run_script(GEN_MCP, "--server", "members", "--url",
                        "https://members.example.com/mcp", "--as", "mcp-json",
                        cwd=tmp_path)
    assert result.returncode == EXIT_OK
    document = json.loads((tmp_path / ".mcp.json").read_text())
    assert document["mcpServers"]["members"] == {
        "type": "http", "url": "https://members.example.com/mcp",
    }


def test_mcp_dry_run_writes_nothing(run_script, tmp_path):
    result = run_script(GEN_MCP, "--server", "x", "--url", "https://e.invalid/mcp",
                        "--dry-run", "--json", cwd=tmp_path)
    assert json.loads(result.stdout)["plan"]["will_write"] == ["mcp_servers_x.py"]
    assert list(tmp_path.iterdir()) == []


def test_naming_both_a_command_and_a_url_is_refused(run_script, tmp_path):
    result = run_script(GEN_MCP, "--server", "x", "--command", "y", "--url", "z",
                        cwd=tmp_path)
    assert result.returncode == EXIT_USAGE
    assert "exactly one" in result.stderr


def test_a_server_key_that_would_break_the_tool_prefix_is_refused(run_script, tmp_path):
    result = run_script(GEN_MCP, "--server", "my server", "--command", "y", cwd=tmp_path)
    assert result.returncode == EXIT_USAGE
    assert "mcp__<server>__<tool>" in result.stderr


# -- gen_subagent ---------------------------------------------------------

def test_a_subagent_snippet_carries_tools_and_a_turn_ceiling(run_script, tmp_path):
    result = run_script(GEN_SUBAGENT, "--name", "shelf-auditor",
                        "--description", "Counts copies on the shelf.",
                        "--tools", "Read", "Grep", "--max-turns", "3", cwd=tmp_path)
    assert result.returncode == EXIT_OK
    source = (tmp_path / "agents_shelf_auditor.py").read_text()
    assert "SHELF_AUDITOR = AgentDefinition(" in source
    assert "tools=['Read', 'Grep']" in source
    assert "maxTurns=3" in source
    assert '"Agent", "Task"' in source, "both spellings, or nothing delegates"


def test_omitting_tools_is_called_out_as_the_finding_it_is(run_script, tmp_path):
    result = run_script(GEN_SUBAGENT, "--name", "a", "--description", "d",
                        "--dry-run", "--json", cwd=tmp_path)
    notes = " ".join(json.loads(result.stdout)["notes"])
    assert "SUB001" in notes


def test_the_markdown_form_warns_that_setting_sources_may_hide_it(run_script, tmp_path):
    result = run_script(GEN_SUBAGENT, "--name", "spine-labeller", "--description", "d",
                        "--tools", "Read", "--as", "markdown", "--json", cwd=tmp_path)
    written = tmp_path / ".claude" / "agents" / "spine-labeller.md"
    assert written.is_file()
    assert written.read_text().startswith("---\nname: spine-labeller\n")
    assert "setting_sources" in " ".join(json.loads(result.stdout)["notes"])


def test_subagent_dry_run_writes_nothing(run_script, tmp_path):
    run_script(GEN_SUBAGENT, "--name", "a", "--description", "d", "--dry-run",
               cwd=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_retired_subagent_model_is_refused(run_script, tmp_path):
    result = run_script(GEN_SUBAGENT, "--name", "a", "--description", "d",
                        "--model", "claude-3-opus-20240229", cwd=tmp_path)
    assert result.returncode == EXIT_USAGE
    assert "retired" in result.stderr


def test_a_name_that_is_not_a_valid_subagent_name_is_refused(run_script, tmp_path):
    result = run_script(GEN_SUBAGENT, "--name", "Shelf Auditor", "--description", "d",
                        cwd=tmp_path)
    assert result.returncode == EXIT_USAGE
