"""What the 0.2.168 sync changed in the plugin-side scripts and references.

Lane B's tests for the 2026-10-17 sync (claude-agent-sdk 0.2.168, bundled CLI
2.1.301; docs and changelog read at Claude Code 2.1.302):

1. **Stop / SubagentStop got output types** in 0.2.166. Only `PreCompact` is
   left without a `hookSpecificOutput`, so `gen_hook.py` must emit
   `hookSpecificOutput.additionalContext` for an injecting `Stop` hook while a
   denying one still blocks with the top-level `decision`, and the HOK rules
   must accept both.
2. **OPT013** became version-ranged and conditional: the `auto` default holds
   only on CLI 2.1.285–2.1.301 and only for sessions that fetch no feature
   flags; 2.1.302 starts those in `default` too.
3. **MCP rule scoping** (2.1.299): MCP001 matches the normalised server name.
4. The references carry the same version range, the dated re-read note, and
   no plugin-eval case gained the untested `disallowed_tools` field.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"
GEN_HOOK = SKILLS / "agent-harness" / "scripts" / "gen_hook.py"
LINT_AGENT = SKILLS / "agent-review" / "scripts" / "lint_agent.py"
LINT_HARNESS = SKILLS / "agent-harness" / "scripts" / "lint_harness.py"
FIXTURES = PLUGIN_ROOT / "tests" / "fixtures" / "agents"

REREAD_NOTE = (
    "re-read 2026-10-17 against claude-agent-sdk 0.2.168 / claude code 2.1.302 docs"
)
#: The 0.2.174 sync (2026-10-24) may replace the note above with its own, so
#: either one shows the file was re-read in this sync or a later one.
LATER_REREAD_NOTES = (
    "re-read 2026-10-24 against claude-agent-sdk 0.2.174 / claude code 2.1.310 docs",
    "re-read 2026-10-29 against claude-agent-sdk 0.2.174 / claude code 2.1.312 docs",
)


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True,
                          text=True, timeout=120, cwd=str(cwd) if cwd else None)


def lint(script: Path, project: Path) -> list[dict]:
    result = run(script, project, "--json", "--no-path-check")
    assert result.stdout, result.stderr
    return json.loads(result.stdout)["findings"]


def by_id(found: list[dict], finding_id: str) -> list[dict]:
    return [f for f in found if f["id"] == finding_id]


# -- gen_hook ---------------------------------------------------------------

def snippet(event: str, purpose: str, tmp_path: Path) -> str:
    result = run(GEN_HOOK, "--event", event, "--purpose", purpose, "--dry-run",
                 cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
def test_an_injecting_stop_hook_uses_hook_specific_output(event, tmp_path):
    source = snippet(event, "inject", tmp_path)
    assert '"hookSpecificOutput"' in source
    assert f'"hookEventName": "{event}"' in source
    assert '"additionalContext"' in source
    assert '"decision": "block"' not in source, "injecting is not blocking"


@pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
def test_a_denying_stop_hook_still_blocks_with_the_top_level_decision(event, tmp_path):
    source = snippet(event, "deny", tmp_path)
    assert '"decision": "block"' in source and '"reason"' in source
    assert '"hookSpecificOutput"' not in source
    assert "permissionDecision" not in source


def test_precompact_is_the_one_event_left_without_an_output_type(tmp_path):
    source = snippet("PreCompact", "inject", tmp_path)
    assert '"hookSpecificOutput"' not in source


def test_an_event_that_cannot_deny_is_still_refused(tmp_path):
    result = run(GEN_HOOK, "--event", "PostToolUse", "--purpose", "deny", "--dry-run",
                 cwd=tmp_path)
    assert result.returncode == 2
    assert "Stop" in result.stderr and "PreCompact" in result.stderr


# -- HOK rules on Stop hooks -----------------------------------------------

STOP_AGENT = '''"""Stop hooks written the 0.2.166 way."""
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher


async def remind(input_data, tool_use_id, context):
    return {"hookSpecificOutput": {"hookEventName": "Stop",
                                   "additionalContext": "Cite the record id."}}


async def keep_going(input_data, tool_use_id, context):
    return {"decision": "block", "reason": "The day book is not updated yet."}


async def invented(input_data, tool_use_id, context):
    return {"note": "nothing reads this"}


OPTIONS = ClaudeAgentOptions(
    model="claude-sonnet-5-5",
    permission_mode="dontAsk",
    setting_sources=[],
    hooks={
        "Stop": [HookMatcher(hooks=[remind])],
        "SubagentStop": [HookMatcher(hooks=[keep_going])],
        "PreCompact": [HookMatcher(hooks=[invented])],
    },
)
'''


@pytest.fixture
def stop_project(tmp_path: Path) -> Path:
    project = tmp_path / "stop_hooks"
    project.mkdir()
    (project / "agent.py").write_text(STOP_AGENT, encoding="utf-8")
    return project


@pytest.mark.parametrize("script", [LINT_AGENT, LINT_HARNESS], ids=["review", "harness"])
def test_stop_hooks_with_specific_output_or_a_decision_are_valid(script, stop_project):
    hok002 = by_id(lint(script, stop_project), "HOK002")
    flagged = " ".join(f["message"] for f in hok002)
    assert "remind()" not in flagged, "Stop takes hookSpecificOutput since 0.2.166"
    assert "keep_going()" not in flagged, "a top-level decision is a common field"
    assert "invented()" not in flagged, "PreCompact has no output type to check against"


def test_an_invented_stop_return_is_now_caught(stop_project):
    agent = stop_project / "agent.py"
    agent.write_text(agent.read_text().replace(
        '"Stop": [HookMatcher(hooks=[remind])]', '"Stop": [HookMatcher(hooks=[invented])]'))
    hok002 = by_id(lint(LINT_AGENT, stop_project), "HOK002")
    assert any("invented()" in f["message"] for f in hok002)
    assert all("Only PreCompact" in f["fix"] for f in hok002 if "invented()" in f["message"])


# -- OPT013 -----------------------------------------------------------------

def test_opt013_is_version_ranged_and_conditional():
    matches = by_id(lint(LINT_AGENT, FIXTURES / "ci_ready"), "OPT013")
    assert len(matches) == 1
    finding = matches[0]
    assert finding["severity"] == "warn"
    message = finding["message"]
    assert "2.1.285–2.1.301" in message and "2.1.302" in message
    assert "feature flags" in message, "the auto default needs its condition"
    assert "`default`" in message and "`auto`" in message
    assert "types.py:2380" in finding["source"]
    assert "permission-modes" in finding["source"] and "CHANGELOG" in finding["source"]


# -- MCP001 -----------------------------------------------------------------

MCP_AGENT = '''from claude_agent_sdk import ClaudeAgentOptions

OPTIONS = ClaudeAgentOptions(
    model="claude-sonnet-5-5",
    permission_mode="dontAsk",
    setting_sources=[],
    mcp_servers={"loans.desk": {"type": "http", "url": "https://example.test/mcp"}},
    allowed_tools=["mcp__loans_desk__*", "mcp__catalog__*"],
    disallowed_tools=["Bash"],
)
'''


def test_mcp001_matches_the_normalised_server_name(tmp_path):
    project = tmp_path / "mcp_names"
    project.mkdir()
    (project / "agent.py").write_text(MCP_AGENT, encoding="utf-8")
    flagged = [f["locator"] for f in by_id(lint(LINT_AGENT, project), "MCP001")]
    assert not any("loans_desk" in loc for loc in flagged), "`.` becomes `_`"
    assert any("catalog" in loc for loc in flagged), "an unknown server is still caught"


# -- references -------------------------------------------------------------

#: Files that state the unset-mode default; each must carry the whole range.
DEFAULT_MODE_FILES = (
    "README.md",
    "skills/agent-harness/references/permission-model.md",
    "skills/agent-review/references/review-checklist.md",
    "skills/agent-review/SKILL.md",
    "skills/eval-run/references/cli-reference.md",
    "skills/agent-deploy/references/observability-otel.md",
)


@pytest.mark.parametrize("name", DEFAULT_MODE_FILES)
def test_the_unset_mode_default_is_stated_with_its_range(name):
    text = flat((PLUGIN_ROOT / name).read_text(encoding="utf-8"))
    assert "2.1.302" in text, f"{name}: say 2.1.302 starts those sessions in `default`"
    assert "2.1.285" in text and "2.1.301" in text, f"{name}: keep the 2.1.285–2.1.301 range"
    assert "feature flag" in text, f"{name}: keep the feature-flag condition"


TOUCHED = (
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
    "eval-run/references/cli-reference.md",
)


@pytest.mark.parametrize("name", TOUCHED)
def test_every_reference_re_read_in_this_sync_carries_the_note(name):
    text = flat((SKILLS / name).read_text(encoding="utf-8"))
    assert any(note in text for note in (REREAD_NOTE, *LATER_REREAD_NOTES))


def test_no_cited_line_number_is_left_at_its_0_2_165_value():
    """Every `types.py` line after 297 moved in 0.2.166; spot the old ones."""
    stale = ("types.py:2025", "types.py:1340", "types.py:1971", "types.py:594 ",
             "types.py:1991", "types.py:2199", "__init__.py:241")
    offenders = [
        f"{path.relative_to(PLUGIN_ROOT)}: {old}"
        for path in SKILLS.rglob("*") if path.suffix in (".md", ".py")
        for old in stale if old in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_hook_reference_says_stop_has_no_output_type():
    for path in SKILLS.rglob("*.md"):
        text = flat(path.read_text(encoding="utf-8"))
        assert "stop, subagentstop and precompact have no" not in text, path
        assert "only stop, subagentstop and precompact" not in text, path


def test_no_plugin_eval_case_uses_the_untested_disallowed_tools_field():
    prompts = sorted((PLUGIN_ROOT / "plugin-evals").rglob("prompt.md"))
    assert prompts, "the plugin-eval cases moved"
    offenders = [str(p) for p in prompts if "disallowed_tools" in p.read_text(encoding="utf-8")]
    assert offenders == [], "no local CLI >= 2.1.299 has accepted the field yet"
