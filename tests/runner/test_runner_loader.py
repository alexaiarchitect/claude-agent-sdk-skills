"""Config, case and grader loading, and the override refusals.

The override checks matter most: they are what makes a typo cost nothing. Every
refusal here happens before a session starts.
"""

from __future__ import annotations

import json

import claude_agent_sdk as sdk
import pytest

from agent_sdk_evals import EvalError
from agent_sdk_evals.loader import (
    Case,
    PERMISSION_MODE_DEFAULT,
    apply_overrides,
    discover_cases,
    expand_env,
    load_case,
    load_config,
    resolve_model,
    validate_overrides,
)

LIVE = sdk.ClaudeAgentOptions.__dataclass_fields__


def write_case(root, name, header="", body="do the thing", graders=None):
    case = root / name
    (case / "graders").mkdir(parents=True, exist_ok=True)
    (case / "prompt.md").write_text(f"---\nname: {name}\n{header}---\n\n{body}\n")
    for slug, text in (graders or {}).items():
        (case / "graders" / f"{slug}.md").write_text(text)
    return case


def write_config(root, **overrides):
    payload = {"schema": "agent-sdk-skills.eval-config/1", "agent": "agent:build_options",
               "model": "claude-sonnet-5-5"}
    payload.update(overrides)
    (root / "eval_config.json").write_text(json.dumps(payload))
    return root


# -- config -----------------------------------------------------------------

def test_the_mini_project_config_loads_with_the_isolation_defaults(mini_evals):
    config = load_config(mini_evals)
    assert config.isolation == {"setting_sources": [], "strict_mcp_config": True}
    assert set(config.tiers) == {"pr", "nightly"}
    assert config.tiers["nightly"].graders == ["free", "judge"]
    assert config.tiers["nightly"].pass_k == 3


def test_a_missing_config_is_a_usage_error(tmp_path):
    with pytest.raises(EvalError) as exc:
        load_config(tmp_path)
    assert exc.value.code == "CFG001"


def test_the_model_expands_from_the_environment(tmp_path, monkeypatch):
    write_config(tmp_path, model="${CLAUDE_MODEL:-claude-sonnet-5-5}")
    assert load_config(tmp_path).model == "claude-sonnet-5-5"
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5-5")
    assert load_config(tmp_path).model == "claude-opus-5-5"


def test_expand_env_handles_plain_refs_lists_and_dicts(monkeypatch):
    monkeypatch.setenv("EVAL_X", "seven")
    assert expand_env("${EVAL_X}") == "seven"
    assert expand_env("${EVAL_MISSING}") == ""
    assert expand_env(["${EVAL_X}"]) == ["seven"]
    assert expand_env({"k": "${EVAL_X}"}) == {"k": "seven"}


def test_judge_samples_below_one_is_refused(tmp_path):
    write_config(tmp_path, judge={"samples": 0})
    with pytest.raises(EvalError) as exc:
        load_config(tmp_path)
    assert exc.value.code == "CFG012"


def test_an_unknown_tier_is_refused_but_the_grader_tiers_work(tmp_path):
    config = load_config(write_config(tmp_path))
    assert config.tier("free").graders == ["free"]
    assert config.tier("judge").graders == ["judge"]
    with pytest.raises(EvalError) as exc:
        config.tier("weekly")
    assert exc.value.code == "CFG020"


# -- cases ------------------------------------------------------------------

def test_the_mini_project_cases_load_with_their_graders(mini_evals):
    cases = {case.name: case for case in discover_cases(mini_evals)}
    assert set(cases) == {"echo-ready", "lookup-first", "structured-answer"}
    assert [g.type for g in cases["echo-ready"].graders] == ["budget", "terminal", "no_tool", "regex"]
    assert cases["structured-answer"].overrides["output_format"]["type"] == "json_schema"
    assert cases["echo-ready"].timeout_seconds == 120


def test_case_filters(mini_evals):
    assert [c.name for c in discover_cases(mini_evals, case_glob="lookup*")] == ["lookup-first"]
    assert [c.name for c in discover_cases(mini_evals, tag="structured")] == ["structured-answer"]
    assert discover_cases(mini_evals, tag="nope") == []


def test_reserved_directories_are_not_cases(mini_evals):
    assert "mocks" not in [c.name for c in discover_cases(mini_evals)]


def test_a_case_with_neither_prompt_nor_turns_is_refused(tmp_path):
    case = write_case(tmp_path, "empty", body="")
    with pytest.raises(EvalError) as exc:
        load_case(case)
    assert exc.value.code == "EVC001"


def test_turns_and_simulated_user_are_mutually_exclusive(tmp_path):
    case = write_case(tmp_path, "both",
                      header='turns: ["a", "b"]\nsimulated_user: personas/x.json\n')
    with pytest.raises(EvalError) as exc:
        load_case(case)
    assert exc.value.code == "EVC001"


def test_an_unknown_frontmatter_key_is_refused(tmp_path):
    case = write_case(tmp_path, "typo", header="catgeory: happy\n")
    with pytest.raises(EvalError) as exc:
        load_case(case)
    assert exc.value.code == "EVC002" and "catgeory" in str(exc.value)


def test_env_keys_must_be_prefixed(tmp_path):
    case = write_case(tmp_path, "env", header="env:\n  PATH: /nope\n")
    with pytest.raises(EvalError) as exc:
        load_case(case)
    assert "EVAL_" in str(exc.value)


def test_a_missing_category_is_a_note_not_a_refusal(tmp_path):
    case = load_case(write_case(tmp_path, "nocat"))
    assert case.category is None
    assert any("EVC030" in note for note in case.notes)


def test_an_unknown_category_is_refused(tmp_path):
    case = write_case(tmp_path, "badcat", header="category: vibes\n")
    with pytest.raises(EvalError):
        load_case(case)


# -- graders ----------------------------------------------------------------

def test_an_unknown_grader_type_is_refused(tmp_path):
    case = write_case(tmp_path, "g", graders={"x": "---\ntype: telepathy\n---\nbody\n"})
    with pytest.raises(EvalError) as exc:
        load_case(case)
    assert exc.value.code == "EVC010"


@pytest.mark.parametrize("header,missing", [
    ("type: regex\n", "pattern"),
    ("type: tool_used\n", "tool"),
    ("type: tool_order\nbefore: a\n", "after"),
    ("type: no_tool\n", "tools"),
    ("type: final_text\n", "reference"),
    ("type: hook_event\n", "event"),
    ("type: structured_output\n", "schema or schema_file"),
    ("type: budget\n", "at least one of max_cost_usd"),
    ("type: terminal\n", "subtype or terminal_reason"),
    ("type: trajectory\n", "expected"),
])
def test_a_grader_missing_a_required_field_is_refused(tmp_path, header, missing):
    case = write_case(tmp_path, "g", graders={"x": f"---\n{header}---\nbody\n"})
    with pytest.raises(EvalError) as exc:
        load_case(case)
    assert exc.value.code == "EVC011" and missing in str(exc.value)


def test_an_llm_grader_needs_a_body(tmp_path):
    case = write_case(tmp_path, "g", graders={"x": "---\ntype: llm\n---\n"})
    with pytest.raises(EvalError) as exc:
        load_case(case)
    assert "criteria" in str(exc.value)


def test_the_grader_tier_comes_from_the_type_never_from_the_file(tmp_path):
    case = load_case(write_case(tmp_path, "g", graders={
        "free": "---\ntype: regex\npattern: x\n---\nprose\n",
        "judged": "---\ntype: llm\n---\nThe answer must refuse politely.\n",
    }))
    tiers = {g.name: g.tier for g in case.graders}
    assert tiers == {"free": "free", "judged": "judge"}
    assert [g.name for g in case.graders_for(["free"])] == ["free"]
    assert [g.name for g in case.graders_for(["free", "judge"])] == ["free", "judged"]


# -- overrides --------------------------------------------------------------

def test_a_valid_override_passes():
    check = validate_overrides({"model": "claude-sonnet-5-5", "max_turns": 3}, LIVE)
    assert check.ok and check.warnings == []


def test_a_name_that_is_not_an_option_is_evc003():
    check = validate_overrides({"modle": "claude-sonnet-5-5"}, LIVE)
    assert not check.ok
    assert check.errors[0].startswith("EVC003") and "modle" in check.errors[0]


def test_a_runner_owned_option_is_evc004():
    for name in ("cwd", "hooks", "mcp_servers", "can_use_tool", "resume", "session_id"):
        check = validate_overrides({name: "x"}, LIVE)
        assert not check.ok, name
        assert check.errors[0].startswith("EVC004"), check.errors


def test_a_deprecated_option_warns_but_is_allowed():
    check = validate_overrides({"max_thinking_tokens": 2048}, LIVE)
    assert check.ok
    assert "deprecated" in check.warnings[0] and "thinking" in check.warnings[0]


def test_debug_stderr_is_both_deprecated_and_runner_owned():
    check = validate_overrides({"debug_stderr": 1}, LIVE)
    assert not check.ok and check.errors[0].startswith("EVC004")


def test_the_skill_tool_in_allowed_tools_warns():
    check = validate_overrides({"allowed_tools": ["Read", "Skill"]}, LIVE)
    assert check.ok
    assert any("Skill" in w and "`skills`" in w for w in check.warnings)


def test_an_option_the_live_sdk_has_but_the_pinned_list_does_not_warns():
    check = validate_overrides({"brand_new_option": 1}, set(LIVE) | {"brand_new_option"})
    assert check.ok
    assert "older than the SDK" in check.warnings[0]


def test_validation_against_the_pinned_list_alone_still_works():
    assert validate_overrides({"model": "m"}, None).ok
    assert not validate_overrides({"nonsense": 1}, None).ok


# -- applying overrides -----------------------------------------------------

def test_the_isolation_defaults_are_forced_onto_whatever_the_agent_built():
    base = sdk.ClaudeAgentOptions(model="m", setting_sources=["user", "project"],
                                 strict_mcp_config=False)
    built, applied, _ = apply_overrides(base, {}, {"setting_sources": [], "strict_mcp_config": True})
    assert built.setting_sources == [] and built.strict_mcp_config is True
    assert applied == {"setting_sources": [], "strict_mcp_config": True}
    assert base.setting_sources == ["user", "project"], "the agent's own options are not mutated"


def test_a_case_can_opt_out_of_isolation_and_it_is_recorded():
    base = sdk.ClaudeAgentOptions(model="m")
    built, applied, _ = apply_overrides(base, {"setting_sources": ["project"]},
                                        {"setting_sources": [], "strict_mcp_config": True})
    assert built.setting_sources == ["project"]
    assert applied["setting_sources"] == ["project"], "the trace records what actually applied"


def test_case_overrides_reach_the_options():
    base = sdk.ClaudeAgentOptions(model="m", max_turns=6)
    built, _, _ = apply_overrides(base, {"max_turns": 2, "effort": "low"},
                                  {"setting_sources": [], "strict_mcp_config": True})
    assert (built.max_turns, built.effort) == (2, "low")


# -- model resolution -------------------------------------------------------

def test_the_model_comes_from_the_case_then_the_config_then_the_agent(tmp_path):
    config = load_config(write_config(tmp_path, model="claude-sonnet-5-5"))
    case = Case(name="c", dir=tmp_path, prompt="x")
    assert resolve_model(case, config, "agent-model") == "claude-sonnet-5-5"
    case.overrides = {"model": "case-model"}
    assert resolve_model(case, config, "agent-model") == "case-model"
    config.model = None
    case.overrides = {}
    assert resolve_model(case, config, "agent-model") == "agent-model"


def test_a_run_never_inherits_the_cli_default_model(tmp_path):
    """Measured: the CLI's default billed ~4x Sonnet for the same trivial prompt."""
    config = load_config(write_config(tmp_path))
    config.model = None
    case = Case(name="c", dir=tmp_path, prompt="x")
    with pytest.raises(EvalError) as exc:
        resolve_model(case, config, None)
    assert "CLAUDE_MODEL" in str(exc.value)
    assert exc.value.fix == "export CLAUDE_MODEL=claude-sonnet-5-5"


# -- the agent entry --------------------------------------------------------

def test_importing_a_broken_entry_is_a_usage_error():
    from agent_sdk_evals.loader import import_entry

    with pytest.raises(EvalError) as exc:
        import_entry("no_such_module_anywhere:build_options")
    assert exc.value.code == "AGT001"


def test_an_entry_without_a_colon_is_refused():
    from agent_sdk_evals.loader import import_entry

    with pytest.raises(EvalError):
        import_entry("agent")


def test_a_module_without_the_function_is_agt002(tmp_path, monkeypatch):
    from agent_sdk_evals.loader import import_entry

    (tmp_path / "halfagent.py").write_text("VALUE = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(EvalError) as exc:
        import_entry("halfagent:build_options")
    assert exc.value.code == "AGT002"


def test_the_mini_project_agent_builds_options(mini_project, monkeypatch):
    from agent_sdk_evals.loader import import_entry

    monkeypatch.syspath_prepend(str(mini_project))
    options = import_entry("agent:build_options", mini_project)()
    assert options.permission_mode == "dontAsk"
    assert set(options.mcp_servers) == {"library"}
    assert "mcp__library__lookup_book" in options.allowed_tools


# -- the permission mode the runner resolves --------------------------------

def test_an_unset_permission_mode_becomes_dont_ask_and_says_who_decided():
    """CONTRACTS section 13.1: unset is not `default`; a headless session can start in `auto`."""
    base = sdk.ClaudeAgentOptions(model="m")
    assert base.permission_mode is None
    built, _, source = apply_overrides(base, {}, {})
    assert built.permission_mode == PERMISSION_MODE_DEFAULT == "dontAsk"
    assert source == "runner-default"
    assert base.permission_mode is None, "the agent's own options are not mutated"


def test_a_mode_the_agent_set_is_left_alone():
    base = sdk.ClaudeAgentOptions(model="m", permission_mode="plan")
    built, _, source = apply_overrides(base, {}, {})
    assert built.permission_mode == "plan" and source == "agent"


def test_a_case_override_counts_as_chosen_not_as_the_runners_default():
    base = sdk.ClaudeAgentOptions(model="m")
    built, _, source = apply_overrides(base, {"permission_mode": "acceptEdits"}, {})
    assert built.permission_mode == "acceptEdits"
    assert source == "agent", "the two sources are 'agent' and 'runner-default', nothing else"
