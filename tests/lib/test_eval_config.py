"""`eval_config.json`: loading, model expansion, and every CFG finding."""

from __future__ import annotations

import json

import pytest
from agent_sdk_skills import DEFAULT_MODEL, RUNNER_VERSION
from agent_sdk_skills.eval_config import (
    SCHEMA,
    config_summary,
    default_config,
    expand_model,
    load_config,
    tier,
    tier_graders,
    validate_config,
)


@pytest.fixture
def configs(fixtures):
    return fixtures / "eval_configs"


def ids(findings):
    return sorted({f.id for f in findings})


def by_id(findings, wanted):
    return [f for f in findings if f.id == wanted]


def check(path, **kwargs):
    return validate_config(load_config(path), **kwargs)


# -- loading ---------------------------------------------------------------

def test_a_good_config_loads_every_block(configs):
    config = load_config(configs / "nightly.json")
    assert config.ok
    assert config.schema == SCHEMA
    assert config.judge_model == "claude-sonnet-5-5"
    assert sorted(config.tiers) == ["nightly", "pr"]
    assert config.isolation == {"setting_sources": [], "strict_mcp_config": True}
    assert config.concurrency == 1


def test_a_directory_is_accepted_in_place_of_the_file(fixtures):
    config = load_config(fixtures / "agents" / "good" / "evals")
    assert config.ok and config.schema == SCHEMA


def test_a_missing_config_is_an_error_not_an_exception(tmp_path):
    config = load_config(tmp_path / "eval_config.json")
    assert not config.exists
    findings = validate_config(config)
    assert ids(findings) == ["CFG001"]
    assert findings[0].severity == "error"


def test_invalid_json_reports_cfg002_with_the_line(configs):
    findings = check(configs / "invalid_json.json")
    assert ids(findings) == ["CFG002"]
    assert "line" in findings[0].message


def test_an_unknown_schema_is_an_error(configs):
    findings = by_id(check(configs / "bad.json"), "CFG003")
    assert findings and findings[0].severity == "error"
    assert "upgrade the plugin" in findings[0].fix


# -- model expansion -------------------------------------------------------

def test_the_defaulted_form_resolves_without_the_variable_set():
    assert expand_model("${CLAUDE_MODEL:-claude-sonnet-5-5}", {}) == "claude-sonnet-5-5"


def test_the_variable_wins_when_it_is_set():
    assert expand_model("${CLAUDE_MODEL:-claude-sonnet-5-5}",
                        {"CLAUDE_MODEL": "claude-opus-5-5"}) == "claude-opus-5-5"


def test_a_bare_variable_with_no_default_resolves_to_nothing():
    assert expand_model("${CLAUDE_MODEL}", {}) == ""
    assert expand_model("$CLAUDE_MODEL", {}) == ""


def test_a_literal_model_passes_through():
    assert expand_model("claude-sonnet-5-5", {}) == "claude-sonnet-5-5"
    assert expand_model(None, {}) is None


def test_a_model_that_resolves_to_nothing_warns(tmp_path):
    """With no model the run inherits the CLI's default, measured at 4x Sonnet."""
    path = tmp_path / "eval_config.json"
    path.write_text(json.dumps({"schema": SCHEMA, "model": "${CLAUDE_MODEL}",
                                "agent": "agent:build_options"}))
    findings = by_id(check(path, env={}), "CFG060")
    assert findings and findings[0].severity == "warn"
    assert "resolves to nothing" in findings[0].message


def test_a_retired_model_warns_with_the_replacement(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG060")
    assert findings and "retired" in findings[0].message
    assert DEFAULT_MODEL in findings[0].fix


def test_a_hardcoded_current_model_is_only_a_note(tmp_path):
    path = tmp_path / "eval_config.json"
    path.write_text(json.dumps({"schema": SCHEMA, "model": DEFAULT_MODEL,
                                "agent": "agent:build_options"}))
    findings = by_id(check(path, env={}), "CFG060")
    assert findings and findings[0].severity == "info"


# -- judge -----------------------------------------------------------------

def test_a_retiring_judge_model_warns(configs):
    findings = by_id(check(configs / "judge_retiring.json", env={}), "CFG010")
    assert findings and findings[0].severity == "warn"
    assert "calibration" in findings[0].fix


def test_a_retired_judge_model_is_an_error(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG011")
    assert findings and findings[0].severity == "error"
    assert "NOT_EVALUATED" in findings[0].fix, "a dead judge goes quiet, it does not fail"


def test_zero_judge_samples_is_an_error(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG012")
    assert any(f.severity == "error" for f in findings)


def test_an_even_sample_count_has_no_majority(tmp_path):
    path = tmp_path / "eval_config.json"
    path.write_text(json.dumps({"schema": SCHEMA, "agent": "a:b", "model": DEFAULT_MODEL,
                                "judge": {"model": "claude-opus-5-5", "samples": 2}}))
    findings = by_id(check(path, env={}), "CFG012")
    assert findings and findings[0].severity == "info"
    assert "odd" in findings[0].fix


def test_a_judge_that_grades_its_own_model_is_a_comparability_note(configs):
    """CONTRACTS §3's own default document has them equal, so this stays `info`."""
    findings = by_id(check(configs / "pr.json", env={}), "CFG013")
    assert findings and findings[0].severity == "info"
    assert "blind spots" in findings[0].fix


# -- tiers -----------------------------------------------------------------

def test_an_unknown_tier_name_warns_but_still_works(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG020")
    assert findings and all(f.severity == "warn" for f in findings)
    assert any("weekly" in f.message for f in findings)


def test_a_grader_type_named_where_a_tier_belongs_is_an_error(configs):
    """`graders` filters on the derived tier, so naming `regex` there filters nothing."""
    findings = by_id(check(configs / "bad.json", env={}), "CFG021")
    assert findings and findings[0].severity == "error"
    assert "regex" in findings[0].message


def test_a_threshold_outside_zero_to_one_is_an_error(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG022")
    assert findings and findings[0].severity == "error"
    assert "1.4" in findings[0].message


def test_zero_runs_is_an_error(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG023")
    assert findings and any("runs" in f.message for f in findings)


def test_pass_k_above_runs_cannot_be_measured(tmp_path):
    path = tmp_path / "eval_config.json"
    path.write_text(json.dumps({
        "schema": SCHEMA, "agent": "a:b", "model": DEFAULT_MODEL,
        "tiers": {"nightly": {"graders": ["free"], "runs": 2, "pass_k": 5}}}))
    findings = by_id(check(path, env={}), "CFG023")
    assert findings and "only 2 run(s)" in findings[0].message
    assert "pass@5 cannot be measured" in findings[0].fix


def test_judge_graders_in_the_pr_tier_warn(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG030")
    assert findings and findings[0].severity == "warn"
    assert "cost nothing" in findings[0].fix


def test_the_default_pr_tier_is_free_only(configs):
    assert tier_graders(load_config(configs / "pr.json"), "pr") == ["free"]
    assert "CFG030" not in ids(check(configs / "pr.json", env={}))


# -- budget, concurrency, isolation ----------------------------------------

def test_a_missing_budget_block_is_a_note(tmp_path):
    path = tmp_path / "eval_config.json"
    path.write_text(json.dumps({"schema": SCHEMA, "agent": "a:b", "model": DEFAULT_MODEL,
                                "isolation": {"setting_sources": [],
                                              "strict_mcp_config": True}}))
    findings = by_id(check(path, env={}), "CFG040")
    assert findings and findings[0].severity == "info"


def test_concurrency_above_one_on_a_subscription_warns(configs):
    findings = by_id(check(configs / "no_isolation.json", env={},
                           credential_kind="login"), "CFG041")
    assert findings and findings[0].severity == "warn"
    assert "usage window" in findings[0].fix


def test_concurrency_above_one_with_an_api_key_is_not_flagged(configs):
    assert "CFG041" not in ids(check(configs / "no_isolation.json", env={},
                                     credential_kind="api_key"))


def test_a_missing_isolation_block_warns_with_the_measured_cost(configs):
    findings = by_id(check(configs / "no_isolation.json", env={}), "CFG042")
    assert findings and findings[0].severity == "warn"
    assert "17x" in findings[0].fix
    assert "measured" in findings[0].source


def test_loading_ambient_settings_warns_even_when_the_block_exists(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG042")
    messages = " ".join(f.message for f in findings)
    assert "setting_sources" in messages
    assert "strict_mcp_config" in messages


def test_the_isolated_default_is_not_flagged(configs):
    assert "CFG042" not in ids(check(configs / "pr.json", env={}))


# -- runner version --------------------------------------------------------

def test_a_runner_version_mismatch_warns(configs):
    findings = by_id(check(configs / "bad.json", env={}), "CFG050")
    assert findings and findings[0].severity == "warn"
    assert "0.0.1" in findings[0].message


def test_the_copys_version_is_preferred_over_the_plugins(configs):
    findings = by_id(check(configs / "pr.json", env={},
                           runner_copy_version="9.9.9"), "CFG050")
    assert findings and "9.9.9" in findings[0].message
    assert "runner copy" in findings[0].message


def test_a_matching_runner_version_is_silent(configs):
    assert "CFG050" not in ids(check(configs / "pr.json", env={}))


# -- the default document --------------------------------------------------

def test_the_default_config_matches_the_contract():
    document = default_config()
    assert document["schema"] == SCHEMA
    assert document["runner_version"] == RUNNER_VERSION
    assert document["model"] == f"${{CLAUDE_MODEL:-{DEFAULT_MODEL}}}"
    assert document["isolation"] == {"setting_sources": [], "strict_mcp_config": True}
    assert document["concurrency"] == 1
    assert document["on_usage_limit"] == "not_evaluated"
    assert document["tiers"]["pr"]["graders"] == ["free"]
    assert document["tiers"]["nightly"]["graders"] == ["free", "judge"]
    assert document["trace"]["redact_env"] == ["ANTHROPIC_API_KEY"]


def test_the_default_config_validates_cleanly_apart_from_the_judge_note(tmp_path):
    path = tmp_path / "eval_config.json"
    path.write_text(json.dumps(default_config()))
    findings = check(path, env={})
    assert [f.id for f in findings if f.severity != "info"] == []
    assert ids(findings) == ["CFG013"], "the contract's own judge equals its agent model"


def test_a_different_judge_model_removes_even_that_note(tmp_path):
    path = tmp_path / "eval_config.json"
    path.write_text(json.dumps(default_config(judge_model="claude-opus-5-5")))
    assert check(path, env={}) == []


# -- accessors -------------------------------------------------------------

def test_tier_returns_the_named_block_or_none(configs):
    config = load_config(configs / "nightly.json")
    assert tier(config, "nightly")["runs"] == 3
    assert tier(config, "weekly") is None


def test_tier_graders_defaults_to_free_only(configs):
    assert tier_graders(load_config(configs / "nightly.json"), "missing") == ["free"]


def test_the_summary_reports_the_resolved_model(configs):
    summary = config_summary(load_config(configs / "nightly.json"), env={})
    assert summary["resolved_model"] == DEFAULT_MODEL
    assert summary["tiers"]["nightly"]["runs"] == 3
    assert summary["isolation"] == {"setting_sources": [], "strict_mcp_config": True}


def test_every_finding_cites_a_source(configs):
    for name in ("bad.json", "no_isolation.json", "judge_retiring.json"):
        for finding in check(configs / name, env={}):
            assert finding.source, f"{name}: {finding.id} has no source"
