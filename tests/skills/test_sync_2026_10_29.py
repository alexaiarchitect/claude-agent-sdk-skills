"""What the 2026-10-29 sync changed in the plugin-side references, README and notices.

Tests for the fourth upstream sync (claude-agent-sdk 0.2.174 with its bundled CLI
2.1.310, unchanged; docs and changelog read at Claude Code 2.1.312) and the
Anthropic-article integration that came with release 0.2.0. Written from the
plan (`.claude/plans/write-detailed-plan-on-quiet-ladybug.md` §2a-§2c) and
`.dev/UPSTREAM-DELTA-2026-10-29.md`, against what lanes B and C were asked to write.

1. **Every reference re-read in this sync carries the dated note.**
2. **2.1.311 / 2.1.312 facts land where they belong**: the hook cap is 24 per
   session, `claude_code.safety_event` stopped in 2.1.312, the plan-mode rule
   names file-edit tools only, the `max_turns` "+1" sentence, `[1m]`, the new
   env vars, `CLAUDE_CONFIG_DIR` in a temp dir.
3. **The 14 Anthropic articles** are listed in `THIRD_PARTY_NOTICES.md` and each
   is cited by at least one skill file, at its canonical (`/research/` or
   `claude.com`) URL, never at the old `/engineering/` path.
4. **Release 0.2.0 and the new skill `/agent-sdk:agent-design`** show up in the
   router, the README and the runner-stale rubric; nothing still calls 0.1.4 current.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"

NEW_NOTE = "re-read 2026-10-29 against claude-agent-sdk 0.2.174 / claude code 2.1.312 docs"


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


def skill_files():
    return [p for p in SKILLS.rglob("*") if p.is_file() and p.suffix in (".md", ".py")]


def skill_docs():
    """The files that cite articles: every reference and every SKILL.md."""
    return sorted(SKILLS.rglob("references/*.md")) + sorted(SKILLS.glob("*/SKILL.md"))


# -- 1. the dated re-read note -------------------------------------------------

#: References lane B re-reads in this sync (plan §2b).
REREAD = (
    "agent-harness/references/hooks-catalog.md",
    "agent-harness/references/permission-model.md",
    "agent-harness/references/subagent-design.md",
    "agent-harness/references/context-and-settings.md",
    "agent-harness/references/mcp-patterns.md",
    "agent-review/references/options-reference.md",
    "agent-review/references/review-checklist.md",
    "agent-review/references/model-policy.md",
    "agent-review/references/load-check.md",
    "agent-deploy/references/observability-otel.md",
    "agent-deploy/references/hosting-options.md",
    "agent-deploy/references/secure-deployment.md",
    "agent-deploy/references/cost-controls.md",
    "agent-create/references/eval-ready-architecture.md",
    "agent-create/references/new-sdk-app-handoff.md",
    "agent-debug/references/failure-shapes.md",
    "agent-debug/references/evidence.md",
    "eval-create/references/case-taxonomy.md",
    "eval-create/references/golden-traces.md",
    "eval-criteria/references/judge-options.md",
    "eval-criteria/references/budgets-and-efficiency.md",
    "eval-criteria/references/grader-catalog.md",
    "eval-run/references/running-in-ci.md",
    "eval-run/references/cost-estimation.md",
    "eval-analyze/references/reliability.md",
    "eval-analyze/references/diagnosis.md",
    "agent-sdk/references/capability-map.md",
    "agent-sdk/references/glossary.md",
    "agent-sdk/references/environment.md",
)


@pytest.mark.parametrize("name", REREAD)
def test_every_reference_re_read_in_this_sync_carries_the_new_note(name):
    assert NEW_NOTE in flat((SKILLS / name).read_text(encoding="utf-8"))


# -- 2. 2.1.311 / 2.1.312 and docs facts ----------------------------------------

def test_the_hooks_reference_states_the_2_1_312_cap_of_24():
    text = read("skills/agent-harness/references/hooks-catalog.md")
    assert re.search(r"\b24\b.{0,60}at a time", flat(text)), "24 ... at a time"
    assert "2.1.312" in text


def test_no_skill_file_keeps_the_old_cap_of_12_as_the_rule():
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in skill_files()
                 if "at most 12 prompt or agent hooks" in flat(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_the_otel_reference_says_safety_event_stopped_in_2_1_312():
    text = read("skills/agent-deploy/references/observability-otel.md")
    assert "claude_code.safety_event" in text and "2.1.312" in text
    assert "no longer sent" in flat(text) or "stopped" in flat(text)


#: The "+1" sizing rule (docs agent-loop, read 2026-10-29).
PLUS_ONE = "plus one for the final text-only response"
PLUS_ONE_FILES = (
    "skills/agent-review/references/options-reference.md",
    "skills/eval-criteria/references/budgets-and-efficiency.md",
    "skills/eval-criteria/references/grader-catalog.md",
    "lib/agent_sdk_skills/budget.py",
)


@pytest.mark.parametrize("relative", PLUS_ONE_FILES, ids=lambda r: Path(r).name)
def test_the_max_turns_plus_one_rule_is_stated(relative):
    assert PLUS_ONE in flat(read(relative))


def test_the_permission_model_carries_the_2026_10_29_docs_facts():
    text = read("skills/agent-harness/references/permission-model.md")
    lowered = flat(text)
    assert "file-edit tools" in lowered
    assert "shell-write" not in lowered, "plan mode sends file-edit tools only (docs 2026-10-29)"
    assert "4,096" in text or "4096" in text
    assert "Dangerous rm operation not ruled out" in text
    assert "permission_policy" in text and "TypeScript" in text


def test_the_model_policy_names_the_1m_change_and_the_refusal_fallback_switch():
    text = read("skills/agent-review/references/model-policy.md")
    assert "[1m]" in text and "2.1.311" in text
    assert "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK" in text


def test_context_and_settings_covers_the_temp_config_dir_and_effort_env_var():
    text = read("skills/agent-harness/references/context-and-settings.md")
    assert "CLAUDE_CONFIG_DIR" in text and "temp" in text.lower()
    assert "CLAUDE_CODE_EFFORT_LEVEL" in text


def test_subagent_design_covers_taskstop_folding_and_points_to_agent_design():
    text = read("skills/agent-harness/references/subagent-design.md")
    assert "TaskStop" in text
    assert "fold" in text.lower()
    assert "/agent-sdk:agent-design" in text


#: The variables the 2.1.310 env-vars page dropped (2026-10-24 list). The
#: 2.1.312 page removed none (Phase 1 delta, 2026-10-29).
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


# -- 3. the fourteen articles ----------------------------------------------------

#: Canonical URLs from `.dev/articles/INDEX.md` (fetched 2026-10-29).
ARTICLES = (
    "https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk",
    "https://www.anthropic.com/research/building-effective-agents",
    "https://www.anthropic.com/research/effective-context-engineering-for-ai-agents",
    "https://www.anthropic.com/research/writing-tools-for-agents",
    "https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills",
    "https://www.anthropic.com/research/code-execution-with-mcp",
    "https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop",
    "https://www.anthropic.com/research/effective-harnesses-for-long-running-agents",
    "https://www.anthropic.com/research/harness-design-long-running-apps",
    "https://www.anthropic.com/research/multi-agent-research-system",
    "https://www.anthropic.com/research/managed-agents",
    "https://www.anthropic.com/research/claude-code-auto-mode",
    "https://www.anthropic.com/research/claude-code-sandboxing",
    "https://www.anthropic.com/research/infrastructure-noise",
)


def test_there_are_fourteen_distinct_articles():
    assert len(set(ARTICLES)) == 14


@pytest.mark.parametrize("url", ARTICLES, ids=lambda u: u.rsplit("/", 1)[1][:40])
def test_third_party_notices_lists_each_article(url):
    assert url in read("THIRD_PARTY_NOTICES.md")


@pytest.mark.parametrize("url", ARTICLES, ids=lambda u: u.rsplit("/", 1)[1][:40])
def test_each_article_is_cited_by_at_least_one_skill_file(url):
    assert any(url in p.read_text(encoding="utf-8") for p in skill_docs()), url


def test_no_skill_file_cites_the_old_engineering_path():
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in skill_files()
                 if "anthropic.com/engineering/" in p.read_text(encoding="utf-8")]
    assert offenders == []


# -- 4. release 0.2.0 and the new skill --------------------------------------------

def test_the_readme_states_the_docs_version_and_lists_agent_design():
    text = read("README.md")
    assert "documentation read at claude code 2.1.312" in flat(text)
    rows = [line for line in text.splitlines() if line.lstrip().startswith("|")]
    assert any("/agent-sdk:agent-design" in row for row in rows), "a skill-table row"


@pytest.mark.parametrize("relative", ("skills/agent-sdk/SKILL.md",
                                      "skills/agent-sdk/references/capability-map.md"))
def test_the_router_names_agent_design(relative):
    assert "/agent-sdk:agent-design" in read(relative)


def test_the_capability_map_counts_fourteen_skills():
    assert "fourteen skills" in flat(read("skills/agent-sdk/references/capability-map.md"))


def test_the_runner_stale_rubric_names_0_2_0():
    assert "0.2.0" in read("plugin-evals/runner-stale/graders/criteria.md")


#: Lines that may keep `0.1.4` because they record history ("from 0.1.4",
#: "(0.1.4)", "the 0.1.4 `Capture`"), not the current version.
HISTORY_014 = re.compile(r"from (runner )?0\.1\.4|\(0\.1\.4\)|the 0\.1\.4 `Capture`")
#: Files whose every `0.1.4` is history or a test of history.
HISTORY_014_FILES = {
    "runner/agent_sdk_evals/CHANGELOG.md",
    "tests/skills/test_sync_0_2_174.py",
    "tests/skills/test_sync_2026_10_29.py",
}
SKIPPED_DIRS = {".dev", ".git", "__pycache__", ".pytest_cache", ".scaffold", "results"}


def test_nothing_outside_history_still_calls_0_1_4_current():
    offenders = []
    for path in PLUGIN_ROOT.rglob("*"):
        relative = path.relative_to(PLUGIN_ROOT)
        if not path.is_file() or SKIPPED_DIRS.intersection(relative.parts[:-1]):
            continue
        if relative.as_posix() in HISTORY_014_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if "0.1.4" in line and not HISTORY_014.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()[:80]}")
    assert offenders == []


def test_the_aggregate_fixtures_still_count_as_results_dirs():
    """`results/` is skipped above only because `plugin-evals/results/` is
    gitignored output; the fixtures under `tests/fixtures/results/` are checked here."""
    for aggregate in (PLUGIN_ROOT / "tests" / "fixtures" / "results").glob("*/aggregate.json"):
        assert '"runner_version": "0.2.0"' in aggregate.read_text(encoding="utf-8"), aggregate


def test_the_new_skill_and_its_fixture_exist():
    assert (PLUGIN_ROOT / "tests" / "fixtures" / "agents" / "tool_design" / "agent.py").is_file()
    assert (SKILLS / "agent-design" / "scripts" / "design_check.py").is_file()


# --- Lane B's own list of what it wrote (2026-10-29), checked verbatim -------------
# Needles are lower-cased and matched against the whitespace-flattened file.

def _flat(text: str) -> str:
    return " ".join(text.split()).lower()


LANE_B_PRESENT = (
 ("skills/agent-harness/references/hooks-catalog.md", ("at most 24 at a time per session", "plus at most 12 that have waited longer than their event's timeout", "a `timeout` under 1 second counts as 1 second", "if more than 12 of them are prompt or agent hooks, 12 of those run at once", "subagenthandback", "up to three times", "before 2.1.210", "fires once per subagent (2.1.311)", "a `-p` session doesn't count as accepting it", "$claude_effort")),
 ("skills/agent-harness/references/permission-model.md", ("sends file-edit tools to your `canusetool` callback regardless of allow rules", "more than 4,096 `updated_permissions` items", "dangerous rm operation not ruled out", "claude_code_disable_dangerous_rm_timeout", "claude_code_even_more_dangerously_skip_permissions", "`mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`, `sed`", "typescript-only (agent sdk v0.3.301+)", "reasoning-blind by design", "17 % miss rate", "0.4 % false-positive rate", "claude code doesn't stop the run", "https://www.anthropic.com/research/claude-code-auto-mode")),
 ("skills/agent-harness/references/subagent-design.md", ("taskstop", "killshell", "`sonnet`, `opus`, `haiku`, or `fable`", "claude_code_disable_background_tasks", "never raises", "finish connecting after the subagent started", "divide by context", "90.2 %", "15×", "token usage by itself explains 80% of the variance", "/agent-sdk:agent-design")),
 ("skills/agent-harness/references/context-and-settings.md", ("new, private temp directory", "claude_code_oauth_token", "claude setup-token", "claude_code_effort_level", "claude_effort", "can also load from the repository's root", "a finite resource with diminishing marginal returns", "precompact", "about an hour", "usage credits required for 1m context")),
 ("skills/agent-harness/references/mcp-patterns.md", ("search over list", "response_format", "25,000 tokens", "max_mcp_output_tokens", "user_id", "150,000", "mcp_server_errors", "system/init", "destructivehint", "/agent-sdk:agent-design")),
 ("skills/agent-review/references/options-reference.md", ("plus one for the final text-only response", "num_turns 2", "stop_reason tool_use", "with no argument switches to claude code's default model", "af_vsock", "[1m]")),
 ("skills/agent-review/references/review-checklist.md", ("/agent-sdk:agent-design", "dsg0xx", "plus one for the final text-only response")),
 ("skills/agent-review/references/model-policy.md", ("as of 2026-10-29", "[1m]", "2.1.311", "claude_code_disable_refusal_fallback", "opus 5.5, sonnet 5.5 and haiku 5.5")),
 ("skills/agent-review/references/load-check.md", ("2.1.312",)),
 ("skills/agent-deploy/references/observability-otel.md", ("sent 2.1.307–2.1.311, no longer sent from 2.1.312", "the monitoring page read 2026-10-29 still documents it", '"config"', '"user_abort"', "the level in force", "mcp_server.name", "prometheus")),
 ("skills/agent-deploy/references/hosting-options.md", ("execute(name, input)", "rainbow deployments", "claude_code_model_catalog=off", "claude_code_simple_system_prompt=0", "lazily", "https://www.anthropic.com/research/managed-agents")),
 ("skills/agent-deploy/references/secure-deployment.md", ("requires both filesystem and network isolation", "84 %", "only a trailing `/**`", "claude_code_disable_bg_exit_handoff", "https://www.anthropic.com/research/how-we-contain-claude", "https://www.anthropic.com/research/claude-code-sandboxing")),
 ("skills/agent-deploy/references/cost-controls.md", ("plus one for the final text-only response", "5-hour limit", "large prompt-cache misses", "claude_code_effort_level", "200k")),
 ("skills/agent-create/references/eval-ready-architecture.md", ("generally not a very robust method", "visual feedback", "https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk")),
 ("skills/agent-create/references/new-sdk-app-handoff.md", ("anthropics/claude-plugins-official", "agent-sdk-dev@claude-plugins-official")),
 ("skills/agent-create/scripts/eval_scaffold.py", ("plus one for the final text-only response",)),
 ("skills/agent-debug/references/failure-shapes.md", ("declared victory early", "one feature per session", "plus one for the final text-only response")),
 ("skills/agent-debug/references/evidence.md", ("2.1.311", "out of order")),
 ("skills/eval-create/references/case-taxonomy.md", ("even a set of 10 golden examples is enough to start", "real usage")),
 ("skills/eval-create/references/golden-traces.md", ("run each task more than once", "timestamp the important events")),
 ("skills/eval-criteria/references/judge-options.md", ("0.0-1.0", "few-shot", "far more tractable", "https://www.anthropic.com/research/multi-agent-research-system", "https://www.anthropic.com/research/harness-design-long-running-apps")),
 ("skills/eval-criteria/references/budgets-and-efficiency.md", ("plus one for the final text-only response",)),
 ("skills/eval-criteria/references/grader-catalog.md", ("plus one for the final text-only response",)),
 ("skills/eval-run/references/running-in-ci.md", ("below 3 percentage points", "https://www.anthropic.com/research/infrastructure-noise")),
 ("skills/eval-run/references/cost-estimation.md", ("under 3 percentage points", "https://www.anthropic.com/research/infrastructure-noise")),
 ("skills/eval-analyze/references/reliability.md", ("below 3 percentage points", "https://www.anthropic.com/research/demystifying-evals-for-ai-agents", "2026-01-09")),
 ("skills/eval-analyze/references/diagnosis.md", ("https://www.anthropic.com/research/demystifying-evals-for-ai-agents",)),
 ("skills/agent-sdk/references/capability-map.md", ("fourteen skills", "/agent-sdk:agent-design")),
 ("skills/agent-sdk/references/glossary.md", ("**context engineering**", "**progressive disclosure**", "**fold (subagents)**", "**harness** (design sense)")),
 ("skills/agent-sdk/references/environment.md", ("2.1.312",)),
 ("skills/agent-sdk/SKILL.md", ("`/agent-sdk:agent-design` (design review",)),
 ("skills/agent-harness/SKILL.md", ("/agent-sdk:agent-design",)),
 ("skills/agent-review/SKILL.md", ("/agent-sdk:agent-design",)),
 ("README.md", ("fourteen skills", "documentation read at claude code 2.1.312", "cited anthropic articles", "14 published anthropic articles")),
 ("THIRD_PARTY_NOTICES.md", ("27858cbba9ecee26a06a90b8d39d3b5596121d11", "58d6da1e34d6cd1c6379dcbf568bd66f5f9b6102", "c43f56d0360b9b1f631bd090fd199231d4c880cc", "ca45fc496a3436251f191354091d557da31c15b5", "claude-plugins-official", "## cited anthropic articles", "https://www.anthropic.com/research/how-we-contain-claude, 2026-05-25", "https://www.anthropic.com/research/demystifying-evals-for-ai-agents, 2026-01-09")),
 ("plugin-evals/README.md", ("2.1.312 help", "thirteen cases", "design-review")),
 ("plugin-evals/runner-stale/graders/criteria.md", ("0.2.0",)),
)
LANE_B_ABSENT = (
 ("skills/agent-harness/references/permission-model.md", ("shell-write", "touch` and `rm` reach")),
 ("skills/agent-harness/references/context-and-settings.md", ("about 54 minutes",)),
 ("skills/agent-review/references/model-policy.md", ("as of 2026-10-24",)),
 ("skills/agent-deploy/references/observability-otel.md", ("is the one to alert on",)),
 ("skills/agent-create/references/new-sdk-app-handoff.md", ("has been unchanged since 2025-10-17",)),
 ("plugin-evals/runner-stale/graders/criteria.md", ("0.1.4",)),
 ("README.md", ("thirteen skills", "documentation read at 2.1.310")),
 ("skills/agent-sdk/references/capability-map.md", ("thirteen skills",)),
 ("THIRD_PARTY_NOTICES.md", ("anthropic.com/engineering/",)),
)


@pytest.mark.parametrize("relative,needles", LANE_B_PRESENT, ids=[r for r, _ in LANE_B_PRESENT])
def test_lane_b_facts_are_present(relative, needles):
    text = _flat((PLUGIN_ROOT / relative).read_text(encoding="utf-8"))
    missing = [n for n in needles if n.lower() not in text]
    assert missing == [], f"{relative}: missing {missing}"


@pytest.mark.parametrize("relative,needles", LANE_B_ABSENT, ids=[r for r, _ in LANE_B_ABSENT])
def test_lane_b_stale_wording_is_gone(relative, needles):
    text = _flat((PLUGIN_ROOT / relative).read_text(encoding="utf-8"))
    present = [n for n in needles if n.lower() in text]
    assert present == [], f"{relative}: still says {present}"


def test_the_eval_simulation_description_has_no_angle_brackets():
    text = (SKILLS / "eval-simulation" / "SKILL.md").read_text(encoding="utf-8")
    description = text.split("description:", 1)[1].split("\nallowed-tools", 1)[0]
    assert "<" not in description
