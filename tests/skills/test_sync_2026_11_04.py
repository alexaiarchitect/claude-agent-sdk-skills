"""What the 2026-11-04 sync changed in the pins, citations, references and notices.

Tests for the sixth upstream sync (claude-agent-sdk 0.2.178 with its bundled CLI
2.1.318; docs and changelog read at Claude Code 2.1.318), the first SDK API change
since 0.2.166 (`HookMatcher.on_failure`, 0.2.177) and the two Anthropic articles
(24-25) folded in as short notes with release 0.2.2. Written from the plan
(`.claude/plans/write-detailed-plan-on-quiet-ladybug.md` §2a-§2c),
`.dev/UPSTREAM-DELTA-2026-11-04.md`, `.dev/CONTRACTS.md` §18 and the renumbering
table `.dev/measured/2026-11-04/types-citation-table.md`. Lane A wrote this file
before lanes B and C finished: every assertion marked ``# awaits lane B`` /
``# awaits lane C`` reads a file another lane owns. The needle tuples
(``REREAD``, ``PRESENT``, ``ABSENT``, ``ABSENT_EVERYWHERE``) are plain data so
the lanes' exact wording can be appended without touching the test functions.

1. **Pins and version**: 0.2.178 / 2.1.318 / docs 2.1.318, release 0.2.2 in
   every carrier, the runner-stale rubric names it.
2. **`types.py` citations**: every `types.py:N` (and the `` `:N` `` citations
   that continue it) in `skills/`, `lib/` and `runner/` is a line this file
   knows for 0.2.178, the citing paragraph names that line's symbol, and on the
   installed wheel the line reads as expected. `HookMatcher` has `on_failure`.
3. **`on_failure` is documented with its floor** wherever a skill file names it,
   and `HOK011` exists.
4. **Every reference re-read in this sync carries the dated note**; the docs and
   changelog facts land where the plan puts them.
5. **The 25 Anthropic articles** are listed in `THIRD_PARTY_NOTICES.md`, and
   each new one is cited by at least one skill file.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"

NEW_NOTE = "re-read 2026-11-04 against claude-agent-sdk 0.2.178 / claude code 2.1.318 docs"
#: A later sync may replace the note above with its own; either shows a re-read.
LATER_REREAD_NOTES = (
    "re-read 2026-11-05 against claude-agent-sdk 0.2.178 / claude code 2.1.318 docs",
    "re-read 2026-11-08 against claude-agent-sdk 0.2.179 / claude code 2.1.319 docs",
    "re-read 2026-11-14 against claude-agent-sdk 0.2.182 / claude code 2.1.325 docs",
)


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


def skill_files():
    return [p for p in SKILLS.rglob("*") if p.is_file() and p.suffix in (".md", ".py")]


def skill_docs():
    """The files that cite articles: every reference and every SKILL.md."""
    return sorted(SKILLS.rglob("references/*.md")) + sorted(SKILLS.glob("*/SKILL.md"))


def _load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGIN_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- 1. pins and version ----------------------------------------------------------

def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_the_pins_moved_to_0_2_178_and_2_1_318():
    # 0.2.178 / 2.1.318 at this sync; the pins only move forward (0.2.179 / 2.1.319
    # from 2026-11-08, checked in `test_sync_2026_11_08.py`).
    import agent_sdk_skills as plugin
    assert _version(plugin.SDK_TARGET) >= (0, 2, 178)
    assert _version(plugin.CLI_BUNDLED_WITH_TARGET) >= (2, 1, 318)
    assert _version(plugin.DOCS_READ_AT_CLI) >= (2, 1, 318)
    assert plugin.SDK_MIN_SUPPORTED == "0.2.140", "the minimum does not move with the pin"


def test_the_runner_reads_the_docs_at_the_same_version():
    # Read as text: `agent_sdk_evals` is importable only under `tests/runner/`.
    # 2.1.318 at this sync; the runner follows the library's constant from 2026-11-08.
    import agent_sdk_skills as plugin
    assert f'DOCS_READ_AT_CLI = "{plugin.DOCS_READ_AT_CLI}"' in read("runner/agent_sdk_evals/__init__.py")


def test_the_release_is_0_2_2_everywhere_lane_a_owns():
    # 0.2.2 at this sync; every carrier follows `__version__` from 0.2.3 on.
    import agent_sdk_skills as plugin
    version = plugin.__version__
    assert plugin.RUNNER_VERSION == version
    assert read("runner/agent_sdk_evals/VERSION").strip() == version
    assert json.loads(read(".claude-plugin/plugin.json"))["version"] == version
    assert f'version = "{version}"' in read("pyproject.toml")
    assert read("tests/fixtures/agents/ci_ready/evals/runner/agent_sdk_evals/VERSION").strip() == version


def test_the_fixtures_carry_the_new_runner_version_and_pins():
    """Synthetic fixtures follow the pin; the measured `init_2_1_3xx` traces are history."""
    # 0.2.2 / 0.2.178 / 2.1.318 at this sync; the fixtures follow the current constants.
    from agent_sdk_skills import CLI_BUNDLED_WITH_TARGET, RUNNER_VERSION, SDK_TARGET
    for aggregate in (PLUGIN_ROOT / "tests" / "fixtures" / "results").glob("*/aggregate.json"):
        payload = json.loads(aggregate.read_text(encoding="utf-8"))
        assert (payload["runner_version"], payload["sdk_version"], payload["cli_version"]) \
            == (RUNNER_VERSION, SDK_TARGET, CLI_BUNDLED_WITH_TARGET), aggregate
    for config in (PLUGIN_ROOT / "tests" / "fixtures").rglob("eval_config.json"):
        if "stale_runner" in config.parts:
            continue                       # stale on purpose (0.0.1)
        assert json.loads(config.read_text(encoding="utf-8"))["runner_version"] == RUNNER_VERSION, config
    assert f"claude-agent-sdk=={SDK_TARGET}" in read("tests/fixtures/agents/ci_ready/requirements.txt")


def test_the_changelog_records_the_release_and_why_the_runner_hooks_fail_open():
    text = read("runner/agent_sdk_evals/CHANGELOG.md")
    assert "## 0.2.2 — 2026-11-04" in text
    section = flat(text.split("## 0.2.2 — 2026-11-04", 1)[1].split("## 0.2.1", 1)[0])
    for needle in ("first sdk api change since 0.2.166", "hookmatcher.on_failure", "types.py:866",
                   "hook_callback_failed", "its answer was treated as empty.",
                   'failed; blocking because onfailure is "block"', "permission_denials",
                   "the runner's own hooks stay on the default", "credential_expires_at",
                   "changelog only", "turn.step", "exits 1", "saved effort level"):
        assert needle in section, needle


def test_the_runner_stale_rubric_names_the_current_runner_version():  # awaits lane B
    from agent_sdk_skills import RUNNER_VERSION
    assert RUNNER_VERSION in read("plugin-evals/runner-stale/graders/criteria.md")


def test_the_sdk_venv_and_the_live_command_name_the_pin():
    # casdk-venv-0.2.178 at this sync; the venv follows the pin (0.2.179 from 2026-11-08,
    # with 0.2.178 kept as the fallback).
    from agent_sdk_skills import SDK_TARGET
    conftest = read("tests/conftest.py")
    assert f'SDK_VENV_NAME = "casdk-venv-{SDK_TARGET}"' in conftest
    assert f"casdk-venv-{SDK_TARGET}/bin/python" in read("tests/runner/test_live.py")


# -- 2. types.py citations ----------------------------------------------------------

#: Every `types.py` line (or range) the plugin may cite, as numbered in the 0.2.182
#: wheel (shifted from the 0.2.178 numbers on 2026-11-14; `client_app` added): (what the first line of it starts with, stripped; names the citing
#: paragraph may use for it, lower-cased). From the Phase 1 table (0 symbol
#: mismatches after the shift) plus the new `on_failure` lines. A new citation
#: goes here after its line was read in the wheel.
CITED = {
    "25": ("PermissionMode = Literal[", ("permissionmode",)),
    "30": ('SdkBeta = Literal[', ("sdkbeta", "betas")),
    "33": ("SettingSource = Literal[", ("settingsource", "setting_sources")),
    "37": ("EffortLevel: TypeAlias = Literal[", ("effortlevel", "effort")),
    "261": ("class PermissionResultAllow:", ("permissionresultallow",)),
    "270": ("class PermissionResultDeny:", ("permissionresultdeny",)),
    "280": ("CanUseTool = Callable[", ("canusetool", "can_use_tool")),
    "286": ("HookEvent = (", ("hookevent",)),
    "286-299": ("HookEvent = (", ("hookevent",)),
    "301": ("class HookEffort(TypedDict):", ("hookeffort",)),
    "301-511": ("class HookEffort(TypedDict):", ("input", "hookeffort")),
    "513-727": ("class PreToolUseHookSpecificOutput(TypedDict):", ("hookspecificoutput",)),
    "616": ("class StopHookSpecificOutput(TypedDict):", ("stophookspecificoutput", "stop")),
    "627": ("class SubagentStopHookSpecificOutput(TypedDict):", ("subagentstop", "hookmatcher")),
    "730-817": ("HookSpecificOutput = (", ("hookjsonoutput", "hookspecificoutput")),
    "820": ("class HookContext(TypedDict):", ("hookcontext",)),
    "830": ("HookCallback = Callable[", ("hookcallback",)),
    "842": ("class HookMatcher:", ("hookmatcher",)),
    "857-866": ("# What happens when a callback in this matcher fails.", ("on_failure",)),
    "866": ('on_failure: Literal["continue", "block"] | None = None', ("on_failure",)),
    "2334-2335": ('if hasattr(matcher, "on_failure")', ("on_failure",)),
    "1139": ("SandboxIgnoreViolations: TypeAlias = dict[str, list[str]]", ("ignoreviolations",)),
    "1154": ("class SandboxSettings(TypedDict, total=False):", ("sandboxsettings", "sandbox")),
    "1231": ("class ToolResultBlock:", ("toolresultblock",)),
    "1456": ('FastModeState = Literal["off", "cooldown", "on"]', ("fastmodestate", "fast_mode")),
    "1460": ("FastModeDisabledReason = Literal[", ("fastmodedisabledreason", "fast_mode")),
    "1474": ("class SystemInitData(TypedDict):", ("systeminitdata",)),
    "1682": ("class ModelUsage(TypedDict):", ("modelusage", "model_usage")),
    "1708": ("class ResultMessage:", ("resultmessage",)),
    "1708-1747": ("class ResultMessage:", ("resultmessage",)),
    "1760": ("RateLimitType = Literal[", ("ratelimittype",)),
    "1766": ("class RateLimitInfo:", ("ratelimitinfo",)),
    "1834": ("class HookEventMessage(SystemMessage):", ("hookeventmessage",)),
    "2185": ("class ThinkingConfigAdaptive(TypedDict):", ("thinkingconfig", "thinking")),
    "2185-2198": ("class ThinkingConfigAdaptive(TypedDict):", ("thinkingconfig", "thinking")),
    "2203-2292": ("class CanUseToolShadowedWarning(UserWarning):", ("canusetoolshadowedwarning",)),
    "2341": ("class ClaudeAgentOptions:", ("claudeagentoptions",)),
    "2341-2813": ("class ClaudeAgentOptions:", ("claudeagentoptions", "50 fields")),
    "2341-2804": ("class ClaudeAgentOptions:", ("claudeagentoptions", "49 fields", "50 fields")),
    "2344-2363": ("tools: list[str] | ToolsPreset | None = None", ("tools",)),
    "2361": ('Passing ``"Skill"`` here is deprecated.', ("skill",)),
    "2380": ("mcp_servers: dict[str, McpServerConfig] | str | Path = field", ("mcp_servers",)),
    "2388": ("strict_mcp_config: bool = False", ("strict_mcp_config",)),
    "2395": ("permission_mode: PermissionMode | None = None", ("permission_mode",)),
    "2420": ("max_turns: int | None = None", ("max_turns",)),
    "2426": ("max_budget_usd: float | None = None", ("max_budget_usd",)),
    "2440": ("model: str | None = None", ("model",)),
    "2446": ("fallback_model: str | None = None", ("fallback_model",)),
    "2466": ("cwd: str | Path | None = None", ("cwd",)),
    "2475": ("settings: str | None = None", ("settings",)),
    "2521": ("debug_stderr: Any = sys.stderr", ("debug_stderr",)),
    "2548-2559": ("hooks: dict[HookEvent, list[HookMatcher]] | None = None", ("hooks",)),
    "2571": ("include_hook_events: bool = False", ("include_hook_events",)),
    "2571-2577": ("include_hook_events: bool = False", ("include_hook_events",)),
    "2580-2590": ("forward_subagent_text: bool = False", ("forward_subagent_text", "parent_tool_use_id")),
    "2664": ("agents: dict[str, AgentDefinition] | None = None", ("agents",)),
    "2670": ("setting_sources: list[SettingSource] | None = None", ("setting_sources",)),
    "2683": ('skills: list[str] | Literal["all"] | None = None', ("skills",)),
    "2724": ("max_thinking_tokens: int | None = None", ("max_thinking_tokens",)),
    "2746": ("effort: EffortLevel | None = None", ("effort",)),
    "2777": ("session_store: SessionStore | None = None", ("session_store",)),
    "2804": ("task_budget: TaskBudget | None = None", ("task_budget",)),
    "2813": ("client_app: str | None = None", ("client_app",)),
}

#: `x.py:N` starts a run; a backticked `` `:N` `` continues the last file named in
#: the same paragraph (a blank line or another `x.py:N` ends the run), which is the
#: rule the Phase 1 table used (114 tokens in 67 groups on the 0.2.176 tree).
TOKEN = re.compile(r"([A-Za-z_][\w./-]*\.py):(\d+(?:-\d+)?)|`:(\d+(?:-\d+)?)`")


def types_py_citations(text: str):
    """(number or range, the paragraph it sits in) for every `types.py` citation."""
    found = []
    for paragraph in re.split(r"\n\s*\n", text):
        current = None
        for match in TOKEN.finditer(paragraph):
            if match.group(1):
                current = match.group(1).rsplit("/", 1)[-1]
                if current == "types.py":
                    found.append((match.group(2), paragraph))
            elif current == "types.py":
                found.append((match.group(3), paragraph))
    return found


def citing_files():
    roots = (SKILLS, PLUGIN_ROOT / "lib", PLUGIN_ROOT / "runner")
    return sorted(p for root in roots for p in root.rglob("*")
                  if p.is_file() and p.suffix in (".md", ".py") and "__pycache__" not in p.parts)


def test_the_scanner_finds_what_the_phase_1_table_found():
    sample = ("`types.py:2341` (`ClaudeAgentOptions`), `:2393`, `__init__.py:267`, `:277`\n\n"
              "claude-agent-sdk 0.2.178 types.py:842 `HookMatcher`, `:864`")
    assert [n for n, _ in types_py_citations(sample)] == ["2341", "2393", "842", "864"]


def test_every_types_py_citation_is_a_known_0_2_182_line():  # awaits lanes B/C
    unknown = sorted({f"{p.relative_to(PLUGIN_ROOT)}: types.py:{n}"
                      for p in citing_files()
                      for n, _ in types_py_citations(p.read_text(encoding="utf-8"))
                      if n not in CITED})
    assert unknown == [], ("a citation this file does not know for 0.2.182: renumber it from "
                           ".dev/measured/2026-11-04/types-citation-table.md, or read the "
                           "wheel and add the line to CITED")


def test_every_types_py_citation_names_its_symbol_nearby():  # awaits lanes B/C
    offenders = []
    for path in citing_files():
        for number, paragraph in types_py_citations(path.read_text(encoding="utf-8")):
            if number in CITED and not any(n in paragraph.lower() for n in CITED[number][1]):
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: :{number} "
                                 f"(expected one of {CITED[number][1]})")
    assert offenders == []


#: 0.2.176 citations that moved, written in full so none can match a 0.2.178 one
#: (old `:2563-2573` ends where new `:2567-2573` ends; never guard a bare number).
STALE_0_2_176 = (
    # `types.py:2380`/`:2380` left out since 2026-11-14: 0.2.182's `mcp_servers` sits at 2380 again.
    "types.py:2326-2786", "`:2326-2786`", "types.py:2326",
    "types.py:1695", "`:1695`", "`:1695-1734`", "types.py:1126", "`:1126`",
    "types.py:1141", "`:1141`", "types.py:1218", "types.py:1461", "`:1669`",
    "types.py:1669", "`:2172-2185`", "`:2190-2279`", "`:2329-2348`", "types.py:2346",
    "`:2346`", "`:2365`", "`:2373`", "types.py:2405", "`:2411`", "types.py:2425",
    "`:2431`", "types.py:2451", "`:2451`", "`:2460`", "types.py:2504", "`:2504`",
    "`:2531-2542`", "types.py:2554", "`:2554-2560`", "`:2563-2573`", "types.py:2647",
    "types.py:2653", "`:2653`", "types.py:2665", "types.py:2706", "`:2706`", "`:2728`",
    "`:2759`", "`:1443`", "`:1447`", "`:1747`", "`:1753`", "`:1821`", "`:2172`",
)


def test_no_citation_is_left_at_its_0_2_176_line():  # awaits lanes B/C
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {old}" for p in citing_files()
                 for old in STALE_0_2_176 if old in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_no_citation_is_labelled_with_the_old_wheel():  # awaits lanes B/C
    """The table's "0.2.174 types.py" labels name the wheel the numbers were read in."""
    pattern = re.compile(r"0\.2\.17[46]`?\s+`?types\.py")
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in citing_files()
                 if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


@pytest.fixture(scope="module")
def surface(sdk_python) -> dict:
    """The probe of `tests/lib/test_sdk_surface_live.py`, run once here."""
    probe = _load("tests/lib/test_sdk_surface_live.py", "surface_live").PROBE
    proc = subprocess.run([sdk_python, "-c", probe], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        pytest.skip(f"the SDK probe did not run: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout)


def test_the_wheel_is_the_pin(surface):
    from agent_sdk_skills import CLI_BUNDLED_WITH_TARGET, SDK_TARGET
    assert (surface["version"], surface["cli_version"]) == (SDK_TARGET, CLI_BUNDLED_WITH_TARGET)


@pytest.mark.parametrize("number", sorted(CITED, key=lambda n: int(n.split("-")[0])))
def test_every_known_line_reads_as_expected_on_the_wheel(surface, number):
    lines = Path(surface["types_path"]).read_text(encoding="utf-8").splitlines()
    first, *last = (int(n) for n in number.split("-"))
    assert len(lines) == 2935, "0.2.182's types.py has 2935 lines (0.2.178-0.2.180: 2914)"
    assert lines[first - 1].strip().startswith(CITED[number][0]), (number, lines[first - 1])
    if last:
        assert first < last[0] <= len(lines)


def test_hook_matcher_on_the_pin_has_on_failure(surface):
    assert surface["hook_matcher"] == ["matcher", "hooks", "timeout", "on_failure"]
    assert len(surface["option_names"]) == 50 and "on_failure" not in surface["option_names"]
    assert len(surface["result_message"]) == 19 and len(surface["all"]) == 159


# -- 3. on_failure and HOK011 --------------------------------------------------------

def test_every_skill_file_that_names_on_failure_names_its_floor():  # awaits lanes B/C
    """`on_failure` needs claude-agent-sdk 0.2.177 (and Claude Code 2.1.317); a file
    that teaches it without the floor sends a 0.2.176 project into a TypeError."""
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in skill_files()
                 if "on_failure" in (text := flat(p.read_text(encoding="utf-8")))
                 and "0.2.177" not in text]
    assert offenders == []


def test_hok011_is_a_finding_the_checklist_documents():  # awaits lanes B/C
    assert "HOK011" in read("skills/agent-review/scripts/_checks.py")
    assert "HOK011" in read("skills/agent-review/references/review-checklist.md")
    checks = flat(read("skills/agent-review/scripts/_checks.py"))
    assert "types.py:866" in checks and "block-the-action-when-a-callback-fails" in checks


def test_gen_hook_emits_on_failure_block_for_a_guard():  # awaits lane C
    assert 'on_failure="block"' in read("skills/agent-harness/scripts/gen_hook.py")


def test_options_ast_records_on_failure():
    from agent_sdk_skills.options_ast import HookRegistration
    registration = HookRegistration(event="PreToolUse", lineno=1)
    assert registration.on_failure is None and registration.on_failure_dynamic is False
    assert {"on_failure", "on_failure_dynamic"} <= set(registration.to_dict())


# -- 4. the dated re-read note and this sync's facts ----------------------------------

#: References the plan has lanes B and C re-read in this sync (plan §2b, §2c).
REREAD = (  # awaits lanes B/C; the orchestrator appends what the lanes report
    "agent-harness/references/hooks-catalog.md",
    "agent-harness/references/permission-model.md",
    "agent-harness/references/subagent-design.md",
    "agent-harness/references/context-and-settings.md",
    "agent-harness/references/mcp-patterns.md",
    "agent-review/references/review-checklist.md",
    "agent-review/references/options-reference.md",
    "agent-review/references/model-policy.md",
    "agent-review/references/load-check.md",
    "agent-deploy/references/secure-deployment.md",
    "agent-deploy/references/cost-controls.md",
    "agent-deploy/references/observability-otel.md",
    "agent-deploy/references/hosting-options.md",
    "agent-debug/references/failure-shapes.md",
    "agent-debug/references/evidence.md",
    "agent-create/references/eval-ready-architecture.md",
    "eval-create/references/case-taxonomy.md",
    "eval-run/references/running-in-ci.md",
    "eval-simulation/references/fault-injection.md",
    "agent-design/references/agent-loop.md",
    "agent-design/references/long-running-harness.md",
    "agent-sdk/references/glossary.md",
    "agent-sdk/references/environment.md",
)


@pytest.mark.parametrize("name", REREAD)
def test_every_reference_re_read_in_this_sync_carries_the_new_note(name):  # awaits lanes B/C
    text = flat((SKILLS / name).read_text(encoding="utf-8"))
    assert any(note in text for note in (NEW_NOTE, *LATER_REREAD_NOTES))


ARTICLE_24 = "https://www.anthropic.com/research/alignment-assessment-ukaisi"
ARTICLE_25 = ("https://claude.com/resources/articles/"
              "how-to-manage-costs-and-demonstrate-roi-for-claude-code-on-google-cloud")

#: (file, needles that must appear, lower-cased, whitespace-flattened). The plan's
#: facts in the plan's words; the orchestrator appends the lanes' exact phrases.
PRESENT = (  # awaits lanes B/C
    ("skills/agent-harness/references/hooks-catalog.md",
     ("on_failure", "0.2.177", "2.1.317", "hook_callback_failed", "return {}")),
    ("skills/agent-harness/references/permission-model.md", ("on_failure", "permissionrequest")),
    ("skills/agent-harness/references/subagent-design.md", ("claude_code_subagent_effort", "2.1.317")),
    ("skills/agent-harness/references/context-and-settings.md",
     ("claude_code_disable_nested_session_id",)),
    ("skills/agent-harness/references/mcp-patterns.md",
     ("defer_loading", "tool_reference", "claude_project_dir")),
    ("skills/agent-review/references/review-checklist.md", ("hok011", "on_failure")),
    ("skills/agent-review/references/options-reference.md",
     ("on_failure", "credential_expires_at")),
    ("skills/agent-deploy/references/secure-deployment.md",
     (ARTICLE_24, "failifunavailable", "allowmachlookup")),
    ("skills/agent-deploy/references/cost-controls.md", (ARTICLE_25, "429")),
    ("skills/agent-deploy/references/observability-otel.md",
     (ARTICLE_25, "anthropic.seat_type", "otel_resource_attributes")),
    ("skills/agent-deploy/references/hosting-options.md", ("2.1.317", "~/.claude.json")),
    ("skills/agent-debug/references/failure-shapes.md", (ARTICLE_24, "on_failure")),
    ("skills/agent-debug/references/evidence.md", ("credential_expires_at", "hook_callback_failed")),
    ("skills/agent-create/references/eval-ready-architecture.md", ('on_failure="block"',)),
    ("skills/eval-create/references/case-taxonomy.md", (ARTICLE_24,)),
    ("skills/eval-run/references/running-in-ci.md", ("2.1.317",)),
    ("skills/eval-simulation/references/fault-injection.md", ("on_failure",)),
    ("skills/agent-sdk/references/environment.md", ("0.2.178", "2.1.318")),
    ("skills/agent-sdk/SKILL.md", ("0.2.182",)),  # follows the pin
    # the article count and the cookbooks head move each sync: 25 and 785d7a0 here;
    # 29 and ce8b262 from 2026-11-05, checked in `test_sync_2026_11_05.py`
    ("README.md", ("documentation read at claude code 2.1.325",)),
    ("THIRD_PARTY_NOTICES.md",
     ("3be907edb9c86269d30d1427a77937dd788d6419", "26382c08758260c9f5deb2019d8fe851f89fa9ae")),
)

ABSENT = (  # awaits lanes B/C
    ("README.md", ("documentation read at claude code 2.1.316", "23 published anthropic articles")),
    ("skills/agent-sdk/SKILL.md", ("0.2.176 with bundled claude code 2.1.316",)),
)


@pytest.mark.parametrize("relative,needles", PRESENT, ids=[r for r, _ in PRESENT])
def test_this_syncs_facts_are_present(relative, needles):
    text = flat(read(relative))
    missing = [n for n in needles if n.lower() not in text]
    assert missing == [], f"{relative}: missing {missing}"


@pytest.mark.parametrize("relative,needles", ABSENT, ids=[r for r, _ in ABSENT])
def test_stale_wording_is_gone(relative, needles):
    text = flat(read(relative))
    present = [n for n in needles if n.lower() in text]
    assert present == [], f"{relative}: still says {present}"


#: Wording no skill file or the README may keep anywhere after this sync.
ABSENT_EVERYWHERE = (  # awaits lanes B/C
    "read at 2.1.316",              # docs are read at 2.1.318 now
    "read at claude code 2.1.316",
    "byte-identical in 0.2.176",    # 0.2.177 added 13 lines to types.py
)


def test_no_skill_file_keeps_this_syncs_stale_wording():  # awaits lanes B/C
    sources = skill_files() + [PLUGIN_ROOT / "README.md"]
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {n}" for p in sources
                 for n in ABSENT_EVERYWHERE if n in flat(p.read_text(encoding="utf-8"))]
    assert offenders == []


# -- 5. the 25 articles -----------------------------------------------------------------

ARTICLES_24_25 = (ARTICLE_24, ARTICLE_25)


def _articles_1_23():
    earlier = _load("tests/skills/test_sync_2026_11_02.py", "sync_2026_11_02")
    return earlier.ARTICLES_1_14 + earlier.ARTICLES_15_23


def test_there_are_twenty_five_distinct_articles():
    assert len(set(_articles_1_23() + ARTICLES_24_25)) == 25


def test_third_party_notices_lists_all_twenty_five():  # awaits lane B for 24-25
    notices = read("THIRD_PARTY_NOTICES.md")
    missing = [u for u in _articles_1_23() + ARTICLES_24_25 if u not in notices]
    assert missing == []


@pytest.mark.parametrize("url", ARTICLES_24_25, ids=("ukaisi", "gcp-costs"))
def test_each_new_article_is_cited_by_at_least_one_skill_file(url):  # awaits lane B
    assert any(url in p.read_text(encoding="utf-8") for p in skill_docs()), url


def test_the_new_articles_are_dated_where_they_are_cited():  # awaits lane B
    dates = {ARTICLE_24: "2026-10-23", ARTICLE_25: "2026-10-27"}
    for path in skill_docs():
        text = path.read_text(encoding="utf-8")
        for url, date in dates.items():
            if url in text:
                assert date in text, f"{path.relative_to(PLUGIN_ROOT)}: {url} without {date}"


# -- lane B and lane C needles (appended by the orchestrator, 2026-11-04) --------------
# Verbatim substrings the lanes reported after editing, lowercased and whitespace-flattened.

LANE_PRESENT = (
    ("skills/agent-harness/references/hooks-catalog.md",
     ("## when a callback fails: `on_failure` (sdk 0.2.177+, cli 2.1.317+)",
      "a crashing `pretooluse` guard fails open",
      'onfailure is "block", so this failure counts as a block.',
      "the docs describe it only for the default path",
      "let the error propagate from a guard",
      'fails open** unless `onfailure: "block"`',
      "a hook changed this call's input after auto mode reviewed it",
      # "the hooks page read 2026-11-04 still says" until the 2026-11-05 re-read
      'still says "if more than 12 of them are prompt or agent hooks, 12 of those run at once"',
      "the pinned 0.2.182 (bundled cli 2.1.325) has all of this")),
    ("skills/agent-harness/references/permission-model.md",
     ("can stop the turn after ten responses in a row with no verdict",
      "on `permissionrequest` that block counts only if the failure lands before `can_use_tool` answers")),
    ("skills/agent-harness/references/subagent-design.md",
     ("effort level of subagents and teammates",
      "the env-vars page read 2026-11-04 still does not list it",
      "the subagent **stops** instead", "after 3 minutes on all providers")),
    ("skills/agent-harness/references/context-and-settings.md",
     ("claude_code_disable_nested_session_id=1",
      "ignored in a project or local settings file's `env` block")),
    ("skills/agent-harness/references/mcp-patterns.md",
     ("forward `defer_loading` tool fields and `tool_reference` blocks",
      "connects once without the token", "`claude_project_dir` substituted",
      "returns an error carrying its input schema (2.1.318)", "field in 0.2.182")),
    ("skills/agent-review/references/review-checklist.md",
     ("| `hok011` | warn |",
      "not reported when the project pins claude-agent-sdk below 0.2.177",
      "an sdk `hookmatcher` can block on failure too")),
    ("skills/agent-review/references/options-reference.md",
     ("from 0.2.177 `on_failure`", "it is **not** a `resultmessage` field",
      "no `permission_mode` key", "`ultrathink_typed_raises`", "types.py:2341-2813")),
    # model-policy's "as of 2026-11-04" moves each sync ("as of 2026-11-05" from 2026-11-05)
    ("skills/agent-review/references/load-check.md",
     ("the **0.2.178** wheel bundles **2.1.318**",)),
    ("skills/agent-deploy/references/secure-deployment.md",
     ("**the uk aisi cybertesting incident** (2026-10-23)",
      "both keys are documented, not new",
      "an sdk guard callback still fails open by default")),
    ("skills/agent-deploy/references/cost-controls.md",
     ("## caps at a gateway, in front of the agent", "past 75 % and again past 95 %",
      "`modelpricing`")),
    ("skills/agent-deploy/references/observability-otel.md",
     ("`anthropic.plan`, `anthropic.seat_type`, `anthropic.provider` and `anthropic.custom_base_url`",
      "only for debugging, not in production", "cost_center=eng-123")),
    ("skills/agent-deploy/references/hosting-options.md",
     ("**a full disk is now a failed run.**", "no longer replaces one that is not valid json")),
    ("skills/agent-debug/references/failure-shapes.md", ("## guard failed open",)),
    ("skills/agent-debug/references/evidence.md",
     ("its answer was treated as empty.",
      "no longer report `success` when an api error cut off a reply")),
    ("skills/eval-run/references/running-in-ci.md",
     ("from **2.1.317** `claude -p` also exits 1",)),
    ("skills/eval-ci/references/subscription-and-secrets.md", ("`loginexpiresat`",)),
    ("skills/eval-simulation/references/fault-injection.md",
     ("**the runner's own matchers leave `on_failure` unset**",)),
    ("skills/agent-sdk/references/glossary.md", ("**fail open / fail closed (hooks)**",)),
    ("skills/agent-sdk/references/environment.md",
     ("0.2.177 is the first sdk api change since 0.2.166",)),
    ("THIRD_PARTY_NOTICES.md",
     ("and articles 24–25 on 2026-11-04", "on **2026-11-04** at claude code **2.1.318**")),
    ("plugin-evals/README.md", ("the local `claude` is **2.1.318**",)),
    ("plugin-evals/harness-hooks/graders/criteria.md",
     ("`agent.py line 44`, `agent.py line 50` and `agent.py hooks[sessionstart] line 109`",)),
    # lane C
    # The scripts' "claude-agent-sdk 0.2.178" label follows the pin (0.2.179 from
    # 2026-11-08, same line numbers; `test_sync_0_2_174.py` checks the label), so
    # the needles name the line and symbol only.
    ("skills/agent-review/scripts/_checks.py",
     ('id="hok011"', " types.py:866 (hookmatcher.on_failure)",
      "hooks#block-the-action-when-a-callback-fails", 'on_failure_since_sdk = "0.2.177"',
      " types.py:2395 (permission_mode)", " types.py:2361")),
    ("skills/agent-review/scripts/lint_agent.py",
     (" types.py:2724", " types.py:2521", "0.2.177+")),
    ("skills/agent-harness/scripts/lint_harness.py",
     (" types.py:2571 (include_hook_events)",)),
    ("skills/agent-harness/scripts/gen_hook.py",
     ('on_failure="block"', "# a guard fails closed: a callback that crashes refuses the call",
      '"behavior": "deny"')),
)

LANE_ABSENT = (
    ("skills/eval-simulation/references/fault-injection.md", ("has exactly three fields",)),
    ("skills/agent-harness/references/hooks-catalog.md", ("a dataclass with three fields",)),
    ("skills/agent-review/references/model-policy.md", ("as of 2026-11-02",)),
    ("skills/agent-review/references/options-reference.md", ("types.py:2326-2786",)),
    ("plugin-evals/README.md", ("the local `claude` is **2.1.316**",)),
    ("plugin-evals/runner-stale/graders/criteria.md", ("`0.2.1` for the other side",)),
    ("plugin-evals/harness-hooks/graders/criteria.md", ("`agent.py line 41`",)),
)


@pytest.mark.parametrize("relative,needles", LANE_PRESENT, ids=[r for r, _ in LANE_PRESENT])
def test_lane_facts_are_present(relative, needles):
    text = flat(read(relative))
    missing = [n for n in needles if n.lower() not in text]
    assert missing == [], f"{relative}: missing {missing}"


@pytest.mark.parametrize("relative,needles", LANE_ABSENT, ids=[r for r, _ in LANE_ABSENT])
def test_lane_stale_wording_is_gone(relative, needles):
    text = flat(read(relative))
    present = [n for n in needles if n.lower() in text]
    assert present == [], f"{relative}: still says {present}"


def test_no_script_keeps_the_old_wheel_label():
    offenders = [str(p) for p in SKILLS.glob("*/scripts/*.py")
                 if "0.2.174 types.py" in p.read_text(encoding="utf-8")]
    assert offenders == []
