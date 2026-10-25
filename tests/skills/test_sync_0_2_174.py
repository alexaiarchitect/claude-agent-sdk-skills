"""What the 0.2.174 sync changed in the plugin-side scripts and references.

Tests for the 2026-10-24 sync (claude-agent-sdk 0.2.174, bundled CLI 2.1.310;
docs and changelog read at Claude Code 2.1.310). Seeded from the plan and
`.dev/UPSTREAM-DELTA-2026-10-24.md`; lane B's own assertions extend it.

1. **Twelve `types.py` citations moved by one** (0.2.169 added a docstring line
   at 2558): every one is renumbered and none of the old numbers is left.
2. **No reference states 0.2.168 / 2.1.302 docs as the current pin.**
3. **New facts land where they belong**: `claude_code.safety_event` (2.1.307),
   forked subagents (2.1.302), the `stop_reason`-first rule for
   `ResultMessage.is_error`, the new env vars; none of the eight env vars the
   docs removed is cited.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"

NEW_NOTE = "re-read 2026-10-24 against claude-agent-sdk 0.2.174 / claude code 2.1.310 docs"
#: A later sync may replace the note above with its own; either shows a re-read.
LATER_REREAD_NOTES = (
    "re-read 2026-10-29 against claude-agent-sdk 0.2.174 / claude code 2.1.312 docs",
)


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


def skill_files():
    return [p for p in SKILLS.rglob("*") if p.is_file() and p.suffix in (".md", ".py")]


# -- 1. the twelve renumbered citations --------------------------------------

#: (file, the 0.2.174 citation it must carry, how many times at least).
RENUMBERED = (
    ("skills/agent-deploy/references/hosting-options.md", ":2759", 1),
    ("skills/agent-deploy/references/secure-deployment.md", "types.py:2653", 1),
    ("skills/agent-harness/references/context-and-settings.md", "types.py:2653", 1),
    ("skills/agent-harness/references/subagent-design.md", "types.py:2647", 1),
    ("skills/agent-harness/references/subagent-design.md", ":2563-2573", 1),
    ("skills/agent-review/references/load-check.md", "types.py:2665", 1),
    ("skills/agent-review/references/model-policy.md", ":2728", 1),
    ("skills/agent-review/references/options-reference.md", "types.py:2326-2786", 2),
    ("skills/agent-review/references/review-checklist.md", ":2706", 1),
    ("skills/agent-review/references/review-checklist.md", ":2326-2786", 1),
    ("skills/agent-review/scripts/lint_agent.py", "types.py:2706", 1),
)


@pytest.mark.parametrize("relative, citation, times", RENUMBERED,
                         ids=[f"{Path(r).name}{c}" for r, c, _ in RENUMBERED])
def test_each_moved_citation_carries_its_0_2_174_line(relative, citation, times):
    assert read(relative).count(citation) >= times, f"{relative}: expected {citation}"


#: The 0.2.168 numbers that moved; written so they cannot match the new ones
#: (`:2326-2785` vs `:2326-2786`, `:2562-2572` vs `:2563-2573`).
STALE = ("types.py:2646", "types.py:2652", "types.py:2664", "types.py:2705",
         ":2705`", ":2727`", ":2758`", ":2562-2572", ":2326-2785")


def test_no_moved_citation_is_left_at_its_0_2_168_value():
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {old}"
                 for p in skill_files() for old in STALE
                 if old in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_every_types_py_citation_is_labelled_0_2_174_not_0_2_168():
    pattern = re.compile(r"0\.2\.168`?\s+`?types\.py")
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in skill_files()
                 if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_the_scripts_cite_the_0_2_174_wheel():
    for relative in ("skills/agent-review/scripts/_checks.py",
                     "skills/agent-review/scripts/lint_agent.py",
                     "skills/agent-harness/scripts/lint_harness.py"):
        text = read(relative)
        assert "claude-agent-sdk 0.2.168" not in text, relative
        assert "claude-agent-sdk 0.2.174" in text, relative


# -- 2. the current pin ------------------------------------------------------

#: References the plan has lane B re-read in this sync.
REREAD = (
    "agent-deploy/references/cost-controls.md",
    "agent-deploy/references/hosting-options.md",
    "agent-deploy/references/observability-otel.md",
    "agent-deploy/references/secure-deployment.md",
    "agent-harness/references/context-and-settings.md",
    "agent-harness/references/hooks-catalog.md",
    "agent-harness/references/mcp-patterns.md",
    "agent-harness/references/permission-model.md",
    "agent-harness/references/subagent-design.md",
    "agent-review/references/load-check.md",
    "agent-review/references/model-policy.md",
    "agent-review/references/options-reference.md",
    "agent-review/references/review-checklist.md",
)


@pytest.mark.parametrize("name", REREAD)
def test_every_reference_re_read_in_this_sync_carries_the_new_note(name):
    text = flat((SKILLS / name).read_text(encoding="utf-8"))
    assert any(note in text for note in (NEW_NOTE, *LATER_REREAD_NOTES))


def test_no_reference_names_2_1_302_docs_without_the_2_1_310_re_read():
    """A dated history note may stay; the latest re-read must be 2.1.310."""
    offenders = []
    for path in SKILLS.rglob("*.md"):
        text = flat(path.read_text(encoding="utf-8"))
        if ("2.1.302 docs" in text or "read at 2.1.302" in text) \
                and "2.1.310" not in text and "2.1.312" not in text:
            offenders.append(str(path.relative_to(PLUGIN_ROOT)))
    assert offenders == []


def test_the_readme_states_the_new_pin():
    text = flat(read("README.md"))
    assert "0.2.174" in text and "2.1.310" in text
    assert "checked against `claude-agent-sdk` 0.2.168" not in text
    assert "documentation read at 2.1.302" not in text


# -- 3. new facts ------------------------------------------------------------

def test_the_otel_reference_names_the_safety_event():
    assert "claude_code.safety_event" in read("skills/agent-deploy/references/observability-otel.md")


def test_the_subagent_reference_covers_forked_subagents():
    text = read("skills/agent-harness/references/subagent-design.md")
    assert "fork" in text.lower()
    assert "Agent(fork)" in text
    assert "CLAUDE_CODE_FORK_SUBAGENT" in text


def test_the_options_reference_says_read_stop_reason_before_is_error():
    text = read("skills/agent-review/references/options-reference.md")
    for needle in ("stop_reason", "refusal", "tool_deferred_unavailable", "is_error"):
        assert needle in text, needle


def test_the_hooks_reference_carries_the_0_2_169_and_new_notification_facts():
    text = read("skills/agent-harness/references/hooks-catalog.md")
    assert "plugin_notification" in text
    assert "SessionStart" in text and "Setup" in text and "include_hook_events" in text


def test_the_model_policy_names_the_api_version_that_removed_sampling_params():
    text = read("skills/agent-review/references/model-policy.md")
    assert "2026-10-21" in text and "temperature" in text


def test_allow_nested_user_namespaces_is_documented_as_a_security_boundary():
    for relative in ("skills/agent-harness/references/context-and-settings.md",
                     "skills/agent-deploy/references/secure-deployment.md"):
        assert "allowNestedUserNamespaces" in read(relative), relative


#: New env vars (docs env-vars page, 2.1.310) and the reference each belongs in.
NEW_ENV_VARS = (
    ("CLAUDE_CODE_AUTO_MODE_MODEL", "skills/agent-harness/references/permission-model.md"),
    ("CLAUDE_CODE_DISABLE_MOUNTED_DRIVE_RM_PROMPT",
     "skills/agent-harness/references/permission-model.md"),
    ("CLAUDE_CODE_DISABLE_MOUNTED_DRIVE_RM_PROMPT",
     "skills/agent-deploy/references/secure-deployment.md"),
    ("CLAUDE_CODE_WARN_DISK_FREE_GIB", "skills/agent-deploy/references/secure-deployment.md"),
    ("CLAUDE_CODE_WARN_MEMORY_FREE_GIB", "skills/agent-deploy/references/secure-deployment.md"),
    ("CLAUDE_CODE_RETRY_WATCHDOG_USAGE_LIMIT_RECHECK_MS",
     "skills/agent-deploy/references/cost-controls.md"),
)


@pytest.mark.parametrize("variable, relative", NEW_ENV_VARS,
                         ids=[f"{v}@{Path(r).name}" for v, r in NEW_ENV_VARS])
def test_each_new_env_var_is_documented_where_it_applies(variable, relative):
    assert variable in read(relative)


#: The eight variables the 2.1.310 env-vars page no longer lists.
REMOVED_ENV_VARS = (
    "CLAUDE_AFK_COUNTDOWN_MS", "CLAUDE_AFK_TIMEOUT_MS", "CLAUDE_CODE_DISABLE_ADMIN_ENV_UNION",
    "CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY", "CLAUDE_CODE_TEAM_TEARDOWN_PARK_TIMEOUT_MS",
    "CLAUDE_CODE_USE_NATIVE_FILE_SEARCH", "CLAUDE_DISABLE_ADOPT", "FALLBACK_FOR_ALL_PRIMARY_MODELS",
)


def test_no_removed_env_var_is_cited():
    sources = skill_files() + [PLUGIN_ROOT / "README.md"]
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {v}" for p in sources
                 for v in REMOVED_ENV_VARS if v in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_the_runner_stale_rubric_names_the_new_runner_version():
    # 0.1.4 at this sync; follows the current RUNNER_VERSION from 0.2.0 on.
    from agent_sdk_skills import RUNNER_VERSION
    assert RUNNER_VERSION in read("plugin-evals/runner-stale/graders/criteria.md")


# -- lane B's assertions (2026-10-24) ----------------------------------------
# Every needle is compared lower-cased against the whitespace-flattened file.

LANE_B_PRESENT = (
    ("skills/agent-review/scripts/_checks.py",
     ("#which-mode-a-non-interactive-run-starts-in", "in claude code v2.1.302")),
    ("skills/agent-review/references/review-checklist.md",
     ("read by hand", 'e.data.get("stop_reason") == "refusal"', "tool_deferred_unavailable")),
    ("skills/agent-review/references/options-reference.md",
     ('e.data.get("stop_reason") == "refusal"', "api_timeout_ms", "15 s",
      "allownestedusernamespaces")),
    ("skills/agent-harness/references/permission-model.md",
     ("in claude code v2.1.302 or later", "before v2.1.302, these runs could start in auto mode",
      "claude sonnet 5", "can miss some commands", "dangerous rm operation on mounted drive path",
      "still runs in plan mode", "denywrite", "never match")),
    ("skills/agent-harness/references/hooks-catalog.md",
     ("1,024", "16,384", "requires non-interactive mode with the `-p` flag",
      "tool_deferred_unavailable", "powershell")),
    ("skills/agent-harness/references/subagent-design.md",
     ('subagent_type: "fork"', "async_launched", "first 32 distinct names",
      "before python sdk v0.2.169")),
    ("skills/agent-harness/references/context-and-settings.md",
     ("claude_code_auto_compact_window", "200k", "sshhostcommands", "skill list")),
    ("skills/agent-harness/references/mcp-patterns.md", ("setmcpservers", "idempotent", "elicitation")),
    ("skills/agent-deploy/references/observability-otel.md",
     ("sent_back", "parent_agent_id", "otel_exporter_otlp_headers", "safety_stops")),
    ("skills/agent-deploy/references/cost-controls.md", ("/usage", "recommendations")),
    ("skills/agent-deploy/references/hosting-options.md", ("2.1.310", "less memory")),
    ("skills/agent-review/references/model-policy.md", ("between_tools",)),  # "as of" date moves each sync
    ("README.md", ("before v2.1.302, these runs could start in auto mode",)),
    ("THIRD_PARTY_NOTICES.md",
     ("0e89b298e771259378a6cd3734e00d323dff5703", "318b7e6ac4e726e88a4ad326214866a93c373b1b",
      "0.2.174 wheel", "2026-10-24")),
    ("skills/eval-criteria/references/grader-catalog.md", ("tool_deferred_unavailable",)),
    ("skills/eval-analyze/references/result-schema.md", ("tool_deferred_unavailable",)),
    ("skills/eval-simulation/references/fault-injection.md", ("tool_deferred_unavailable",)),
    ("skills/agent-sdk/references/glossary.md", ("tool_deferred_unavailable", "agent(fork)")),
    ("skills/agent-debug/references/evidence.md", ("stop_reason", "0.2.170")),
    ("skills/agent-sdk/SKILL.md", ("0.2.174 with bundled claude code 2.1.310",)),
    ("skills/agent-sdk/references/environment.md", ("0.2.174",)),
    ("skills/agent-review/SKILL.md", ("stop_reason",)),
    ("plugin-evals/README.md", ("2.1.310 help",)),
)


@pytest.mark.parametrize("relative, needles", LANE_B_PRESENT,
                         ids=[r for r, _ in LANE_B_PRESENT])
def test_lane_b_facts_are_present(relative, needles):
    text = flat(read(relative))
    missing = [n for n in needles if n.lower() not in text]
    assert missing == [], f"{relative}: missing {missing}"


LANE_B_ABSENT = (
    ("skills/agent-harness/references/context-and-settings.md", ("startdirectory", "`unshare`")),
    ("skills/agent-review/references/model-policy.md", ("as of 2026-10-17",)),
    ("skills/eval-criteria/references/grader-catalog.md",
     ("assert it with `terminal` on `stop_reason`",)),
    ("skills/eval-simulation/references/fault-injection.md",
     ("a `terminal` grader on `stop_reason`",)),
    ("skills/agent-harness/references/mcp-patterns.md", ("set_mcp_servers()",)),
)


@pytest.mark.parametrize("relative, needles", LANE_B_ABSENT,
                         ids=[r for r, _ in LANE_B_ABSENT])
def test_lane_b_retired_wording_is_gone(relative, needles):
    text = flat(read(relative))
    present = [n for n in needles if n.lower() in text]
    assert present == [], f"{relative}: still says {present}"


def test_no_reference_says_the_docs_have_not_caught_up_with_2_1_302():
    pattern = re.compile(r"(?i)starting-mode table|has not caught up with 2\.1\.302|does not show yet")
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in SKILLS.rglob("*.md")
                 if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_opt013_cites_the_docs_sentence_on_the_headless_default():
    import json
    import subprocess
    import sys
    lint = SKILLS / "agent-review" / "scripts" / "lint_agent.py"
    proc = subprocess.run([sys.executable, str(lint), str(PLUGIN_ROOT / "tests" / "fixtures" / "agents"
                                                          / "ci_ready"), "--json"],
                          capture_output=True, text=True, timeout=120)
    assert proc.stdout, proc.stderr
    opt013 = [f for f in json.loads(proc.stdout)["findings"] if f["id"] == "OPT013"]
    assert len(opt013) == 1
    source = flat(opt013[0]["source"])
    assert "manual mode" in source
    assert "permission-modes#which-mode-a-non-interactive-run-starts-in" in source
