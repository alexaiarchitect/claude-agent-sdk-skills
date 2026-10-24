"""The static reader: what it must get right about an agent it never runs.

Every assertion below is about a fixture project, so a change in extraction
shows up as a change in a named agent rather than in an abstract shape.
"""

from __future__ import annotations

import textwrap

import pytest

from agent_sdk_skills.options_ast import (
    DYNAMIC, ENV, LITERAL, SANDBOX_DECLARED_KEYS, SANDBOX_FORWARDED_KEYS, extract_module,
    extract_project, resolve, sandbox_problems,
)


@pytest.fixture
def facts(agent_dir):
    def _get(name: str):
        return extract_project(agent_dir(name))

    return _get


# -- values ---------------------------------------------------------------

def test_a_literal_is_read_exactly(facts):
    primary = facts("good").primary
    assert primary.get("max_turns").kind == LITERAL
    assert primary.get("max_turns").value == 6
    assert primary.get("allowed_tools").as_str_list() == [
        "mcp__library__lookup_book", "mcp__library__reserve_book",
        "mcp__library__cancel_reservation",
    ]


def test_an_env_read_keeps_its_variable_and_its_default(facts):
    model = facts("good").primary.get("model")
    assert model.kind == ENV
    assert model.env_var == "CLAUDE_MODEL"
    assert model.value == "claude-sonnet-5-5"
    assert not model.is_literal, "env-derived is not hardcoded; the policy depends on it"


def test_a_computed_value_is_marked_dynamic_and_keeps_its_expression(tmp_path):
    module = tmp_path / "a.py"
    module.write_text(textwrap.dedent('''
        from claude_agent_sdk import ClaudeAgentOptions

        def build_options():
            return ClaudeAgentOptions(model=pick_model(), max_turns=turns() + 1)
    '''))
    call = extract_module(module).options_calls[0]
    assert call.get("model").kind == DYNAMIC
    assert call.get("model").expr == "pick_model()"


def test_a_partly_computed_list_keeps_the_names_it_knows(tmp_path):
    module = tmp_path / "a.py"
    module.write_text(textwrap.dedent('''
        from claude_agent_sdk import ClaudeAgentOptions

        def build_options():
            return ClaudeAgentOptions(allowed_tools=["Read", extra_tool()])
    '''))
    value = extract_module(module).options_calls[0].get("allowed_tools")
    assert value.as_str_list() == ["Read"]
    assert {"__dynamic__": "extra_tool()"} in value.value


@pytest.mark.parametrize("source,expected", [
    ('os.environ["X"]', ENV),
    ('os.environ.get("X", "d")', ENV),
    ('os.getenv("X")', ENV),
    ('"plain"', LITERAL),
    ('f"{a}-b"', DYNAMIC),
])
def test_resolve_grades_each_shape(source, expected, tmp_path):
    import ast

    assert resolve(ast.parse(source, mode="eval").body).kind == expected


# -- where the options are built -----------------------------------------

def test_the_convention_builder_is_preferred_as_primary(facts):
    primary = facts("good").primary
    assert primary.function == "build_options"
    assert primary.in_build_options and primary.injectable


def test_a_custom_builder_is_found_when_there_is_no_convention(facts):
    primary = facts("entry_env").primary
    assert primary.function == "make"
    assert primary.injectable, "a named module-level builder can be called by a runner"
    assert not facts("entry_env").has_build_options


def test_options_built_inside_main_are_not_injectable(facts):
    primary = facts("inline_main").primary
    assert primary.in_main and primary.function == "main"
    assert not primary.injectable


def test_the_legacy_options_class_is_recorded_as_legacy(facts):
    project = facts("drift")
    assert project.primary.legacy
    assert project.modules[0].imports_legacy_sdk


# -- tools and servers ----------------------------------------------------

def test_tool_decorators_give_name_description_and_schema(facts):
    tools = {t.tool_name: t for t in facts("good").tools}
    assert set(tools) == {"lookup_book", "reserve_book", "cancel_reservation"}
    reserve = tools["reserve_book"]
    assert reserve.schema_kind == "types"
    assert reserve.schema_keys == ["title", "member_id"]
    assert reserve.schema_types == {"title": "str", "member_id": "str"}
    assert reserve.is_async and reserve.has_description


def test_the_server_name_and_its_tools_compose_the_names_the_model_sees(facts):
    project = facts("good")
    assert [s.name for s in project.sdk_servers] == ["library"]
    assert project.tool_names() == [
        "mcp__library__cancel_reservation", "mcp__library__lookup_book",
        "mcp__library__reserve_book",
    ]


def test_external_servers_keep_their_transport_command_and_url(facts):
    servers = {s.key: s for s in facts("external_mcp").mcp_servers}
    assert servers["catalogue"].kind == "stdio"
    assert servers["catalogue"].command == "catalogd"
    assert "--serve-mcp" in servers["catalogue"].args
    assert servers["members"].kind == "http"
    assert servers["members"].url == "https://members.library.invalid/mcp"


def test_an_in_process_server_passed_by_variable_is_recognised(facts):
    servers = {s.key: s.kind for s in facts("good").mcp_servers}
    assert servers == {"library": "sdk"}


# -- hooks ----------------------------------------------------------------

def test_every_hook_registration_is_read_with_its_matcher_and_callbacks(facts):
    hooks = facts("hooks_bad").hooks
    assert {h.event for h in hooks} == {"PreToolUse", "PostToolUse", "SessionStart"}
    by_callback = {h.callbacks[0]: h for h in hooks}
    assert by_callback["audit_tool_use"].matcher == "Read"
    assert by_callback["note_session"].matcher is None


def test_an_invalid_matcher_regex_is_reported_with_its_error(facts):
    broken = [h for h in facts("hooks_bad").hooks if h.matcher_regex_error]
    assert len(broken) == 1
    assert broken[0].matcher == "mcp__loans__(reserve"


def test_a_synchronous_callback_is_visible_as_such(facts):
    callback = facts("hooks_bad").function("audit_tool_use")
    assert not callback.is_async
    assert callback.param_count == 3


def test_a_callback_returning_an_invented_shape_is_marked_unrecognised(facts):
    callback = facts("hooks_bad").function("gate_reservation")
    assert callback.is_async
    assert callback.returns_nonempty_dict
    assert callback.returns_unrecognised_dict
    assert not callback.has_hook_specific_output


def test_a_return_of_common_fields_only_is_well_formed(tmp_path):
    """`{"continue_": False, "stopReason": ...}` is how a hook halts a turn, and
    it is accepted on every event. It must not look like a malformed return."""
    module = tmp_path / "a.py"
    module.write_text(textwrap.dedent("""
        async def halt(input_data, tool_use_id, context):
            return {
                "continue_": False,
                "stopReason": "critical error",
                "systemMessage": "stopped",
            }

        async def block(input_data, tool_use_id, context):
            return {"decision": "block", "reason": "not finished"}
    """))
    facts = extract_module(module)
    for name in ("halt", "block"):
        callback = facts.function(name)
        assert callback.returns_nonempty_dict
        assert not callback.returns_unrecognised_dict, name


def test_a_deny_without_a_reason_is_distinguished_from_one_with(facts):
    project = facts("hooks_bad")
    refuse = project.function("refuse_second_copy")
    assert refuse.hook_event_names == ["PreToolUse"]
    assert refuse.permission_decisions == ["deny"]
    assert refuse.deny_without_reason
    assert not project.function("record_result").deny_without_reason


def test_an_empty_dict_return_is_not_mistaken_for_a_malformed_one(facts):
    callback = facts("hooks_bad").function("audit_tool_use")
    assert callback.returns_empty_dict
    assert not callback.returns_nonempty_dict


# -- agents ---------------------------------------------------------------

def test_agent_definitions_are_read_with_tools_model_and_turns(facts):
    agents = {a.name: a for a in facts("subagents").agents}
    assert set(agents) == {"shelf-auditor", "overdue-chaser"}
    auditor, chaser = agents["shelf-auditor"], agents["overdue-chaser"]
    assert not auditor.has_tools and not auditor.has_max_turns
    assert chaser.has_tools and chaser.tools.as_str_list() == ["mcp__loans__loan_record"]
    assert chaser.max_turns.value == 3
    assert chaser.model.as_str() == "claude-haiku-4-5-20251001"


def test_a_camelcase_and_a_snake_case_turn_limit_are_both_found(tmp_path):
    module = tmp_path / "a.py"
    module.write_text(textwrap.dedent('''
        from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

        def build_options():
            return ClaudeAgentOptions(agents={
                "a": AgentDefinition(description="d", prompt="p", maxTurns=2),
                "b": AgentDefinition(description="d", prompt="p", max_turns=3),
            })
    '''))
    agents = {a.name: a for a in extract_module(module).options_calls[0].agents}
    assert agents["a"].max_turns.value == 2
    assert agents["b"].max_turns.value == 3


# -- prompt, output format, secrets, models ------------------------------

def test_a_prompt_held_in_a_module_constant_is_still_a_string(facts):
    assert facts("good").primary.system_prompt_kind == "string"


def test_an_absent_prompt_is_distinguished_from_a_computed_one(facts):
    assert facts("drift").primary.system_prompt_kind == "absent"


@pytest.mark.parametrize("value,kind,append", [
    ('{"type": "preset", "preset": "claude_code"}', "preset", False),
    ('{"type": "preset", "preset": "claude_code", "append": "extra"}', "preset", True),
    ('{"type": "file", "path": "p.md"}', "file", False),
    ('"a string"', "string", False),
])
def test_system_prompt_kinds(value, kind, append, tmp_path):
    module = tmp_path / "a.py"
    module.write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n"
        f"def build_options():\n    return ClaudeAgentOptions(system_prompt={value})\n"
    )
    call = extract_module(module).options_calls[0]
    assert (call.system_prompt_kind, call.system_prompt_append) == (kind, append)


def test_output_format_is_judged_against_the_one_shape_the_cli_acts_on(tmp_path):
    module = tmp_path / "a.py"
    module.write_text(textwrap.dedent('''
        from claude_agent_sdk import ClaudeAgentOptions

        def good():
            return ClaudeAgentOptions(
                output_format={"type": "json_schema", "schema": {"type": "object"}})

        def bad():
            return ClaudeAgentOptions(output_format={"type": "json", "schema": {}})
    '''))
    good, bad = extract_module(module).options_calls
    assert good.output_format.is_json_schema
    assert not bad.output_format.is_json_schema


def test_a_key_literal_is_found_wherever_it_appears(facts):
    secrets = facts("drift").secrets
    assert len(secrets) == 1
    assert secrets[0].kind == "api_key_prefix"
    assert secrets[0].preview.startswith("sk-ant-")


def test_a_commented_placeholder_is_not_a_secret(tmp_path):
    module = tmp_path / "a.py"
    module.write_text(
        "from claude_agent_sdk import ClaudeAgentOptions\n"
        'ANTHROPIC_API_KEY = ""\n'
        'OTHER = "your-api-key-here"\n'
        "def build_options():\n    return ClaudeAgentOptions()\n"
    )
    assert extract_module(module).secrets == []


def test_a_hardcoded_model_and_an_env_derived_one_are_told_apart(facts):
    hardcoded = [r for r in facts("drift").model_refs if r.where == "options"]
    assert hardcoded and all(r.hardcoded for r in hardcoded)
    from_env = [r for r in facts("good").model_refs if r.where == "options"]
    assert from_env and not any(r.hardcoded for r in from_env)


def test_a_subagent_model_is_attributed_to_the_agent(facts):
    agent_refs = [r for r in facts("subagents").model_refs if r.where == "agent"]
    assert [r.value for r in agent_refs] == ["claude-haiku-4-5-20251001"]


# -- query calls and project shape ---------------------------------------

def test_a_bare_query_without_options_is_recorded(facts):
    bare = [c for c in facts("external_mcp").query_calls
            if c.call == "query" and not c.has_options]
    assert len(bare) == 1


def test_a_client_query_method_is_not_mistaken_for_the_module_function(facts):
    # `good` calls `client.query(prompt)`, which takes no options and never could.
    assert not any(c.call == "query" for c in facts("good").query_calls)


def test_a_project_with_no_sdk_usage_says_so(tmp_path):
    (tmp_path / "plain.py").write_text("print('hello')\n")
    project = extract_project(tmp_path)
    assert project.modules == []
    assert project.notes


def test_a_syntax_error_is_reported_rather_than_raised(tmp_path):
    module = tmp_path / "broken.py"
    module.write_text("from claude_agent_sdk import ClaudeAgentOptions\ndef (:\n")
    facts = extract_module(module)
    assert facts.syntax_error
    assert facts.options_calls == []


def test_to_dict_is_json_serialisable_for_every_fixture(agent_dir):
    import json

    for name in ("good", "drift", "no_evals", "inline_main", "entry_env",
                 "external_mcp", "subagents", "hooks_bad", "deploy_ready"):
        payload = extract_project(agent_dir(name)).to_dict()
        assert json.loads(json.dumps(payload))["summary"]["agent_modules"] >= 1


# -- sandbox (0.2.168 shape, unchanged in 0.2.174) -------------------------

def test_a_sandbox_with_the_released_ignore_violations_shape_is_accepted(tmp_path):
    """`ignoreViolations` is `dict[str, list[str]]` from SDK 0.2.166; `failIfUnavailable`
    and `filesystem` are forwarded without being declared, and are accepted too."""
    module = tmp_path / "a.py"
    module.write_text(textwrap.dedent('''
        from claude_agent_sdk import ClaudeAgentOptions
        options = ClaudeAgentOptions(sandbox={
            "enabled": True,
            "ignoreViolations": {"*": ["/usr/bin"], "npm test": ["network"]},
            "failIfUnavailable": True,
            "filesystem": {"denyWrite": ["~/.ssh"]},
        })
    '''))
    sandbox = extract_module(module).options_calls[0].kwargs["sandbox"]
    assert sandbox.kind == LITERAL
    assert sandbox_problems(sandbox.value) == []


@pytest.mark.parametrize("sandbox, needle", [
    ({"ignoreViolations": ["file"]}, "dict[str, list[str]]"),
    ({"ignoreViolations": {"*": "network"}}, "ignoreViolations['*']"),
    ({"filesystem": ["~/.ssh"]}, "`filesystem` must be a dict"),
    ({"denyWrite": ["~/.ssh"]}, "'denyWrite'"),
])
def test_a_sandbox_of_the_wrong_shape_is_named(sandbox, needle):
    problems = sandbox_problems(sandbox)
    assert len(problems) == 1 and needle in problems[0]


def test_a_computed_sandbox_claims_nothing():
    assert sandbox_problems(None) == [] and sandbox_problems("dynamic") == []
    assert set(SANDBOX_FORWARDED_KEYS) == {"failIfUnavailable", "filesystem"}
    assert "ignoreViolations" in SANDBOX_DECLARED_KEYS
