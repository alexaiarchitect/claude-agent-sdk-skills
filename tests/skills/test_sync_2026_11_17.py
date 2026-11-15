"""What the 2026-11-17 sync changed in the pins, the version, the runner, the init fixture and the articles.

Tests for the tenth upstream sync: claude-agent-sdk 0.2.183 (`user_message_uuid` and
`user_message_uuids` on `AssistantMessage`, `ResultMessage` and `StreamEvent`;
`types.py` +51 lines), bundled Claude Code 2.1.326, docs re-read at 2.1.326 on
2026-11-17 (47 pages changed, one new), one more Anthropic article (45) and release
0.2.6, whose runner stamps every prompt with a uuid and drains to the result that
answers it. Written from the plan (`.claude/plans/write-detailed-plan-on-quiet-ladybug.md`),
`.dev/UPSTREAM-DELTA-2026-11-17.md` and `.dev/CONTRACTS.md` §22. The needle tuples
(``LANE_PRESENT``, ``LANE_ABSENT``) are plain data, as in the earlier sync tests.

1. **Pins and version**: 0.2.183 / 2.1.326 / docs 2.1.326, minimum 0.2.140,
   release 0.2.6 in every carrier, the venv named for the pin (0.2.182 kept as the
   fallback), the runner-stale rubric names 0.2.6.
2. **The surface**: 21 `ResultMessage` fields in the surface test and the stub, and
   no pre-shift `types.py` line outside the historical tables (CONTRACTS §22.2).
3. **The runner**: `send_and_drain`, `MAX_FOREIGN_RESULTS == 3`, the schema
   unchanged, the CHANGELOG entry (CONTRACTS §22.5).
4. **The 2.1.326 init fixture**: 20 capabilities, the result echoes the uuid the
   `user` event carries (CONTRACTS §22.3, §22.6).
5. **The 45 Anthropic articles**: article 45 is listed, cited with a dated
   parenthetical and framed as the Claude Code team's practice.
6. **Lane needles**: stale wording is gone, new facts are present.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"
TRACES = PLUGIN_ROOT / "tests" / "fixtures" / "traces"

NEW_NOTE = "re-read 2026-11-17 against claude-agent-sdk 0.2.183 / claude code 2.1.326 docs"


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


def skill_docs():
    """The files that cite articles: every reference and every SKILL.md."""
    return sorted(SKILLS.rglob("references/*.md")) + sorted(SKILLS.glob("*/SKILL.md"))


def _load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGIN_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- 1. pins and version ----------------------------------------------------------

def test_the_pins_moved_to_0_2_183_and_2_1_326():
    import agent_sdk_skills as plugin
    assert (plugin.SDK_TARGET, plugin.CLI_BUNDLED_WITH_TARGET) == ("0.2.183", "2.1.326")
    assert plugin.DOCS_READ_AT_CLI == "2.1.326"
    assert plugin.SDK_MIN_SUPPORTED == "0.2.140", "the minimum does not move with the pin"
    assert 'DOCS_READ_AT_CLI = "2.1.326"' in read("runner/agent_sdk_evals/__init__.py")


def test_the_docs_re_read_is_dated_next_to_the_constant():
    note = "docs re-read 2026-11-17 (47 pages changed, 1 new), cli 2.1.326"
    assert note in flat(read("lib/agent_sdk_skills/__init__.py"))
    assert note in flat(read("runner/agent_sdk_evals/__init__.py"))


def test_the_library_records_the_0_2_183_shift_and_the_unreleased_fix():
    text = flat(read("lib/agent_sdk_skills/__init__.py"))
    assert "0.2.183 (2026-11-16, cli 2.1.326)" in text
    assert "`user_message_uuids` to `assistantmessage`" in text
    assert "1756 on +51" in text and "checked 2026-11-17" in text
    assert "`claudeagentoptions` 2392, `client_app` 2864" in text
    assert "`8ed58af`" in text and '"rulecontent": null' in text
    assert "claude-agent-sdk 0.2.183, 50 fields" in text, "the OPTION_NAMES comment"


def test_the_release_is_0_2_6_everywhere_lane_a_owns():
    import agent_sdk_skills as plugin
    assert plugin.__version__ == plugin.RUNNER_VERSION == "0.2.6"
    assert read("runner/agent_sdk_evals/VERSION").strip() == "0.2.6"
    assert json.loads(read(".claude-plugin/plugin.json"))["version"] == "0.2.6"
    assert 'version = "0.2.6"' in read("pyproject.toml")
    assert read("tests/fixtures/agents/ci_ready/evals/runner/agent_sdk_evals/VERSION").strip() == "0.2.6"
    assert 'return "0.2.6"' in read("tests/fixtures/bin/fake_sdk.py")


def test_the_fixtures_carry_0_2_6_and_the_new_pins():
    """Synthetic fixtures follow the pin; the measured `init_2_1_3xx` traces are history."""
    for aggregate in (PLUGIN_ROOT / "tests" / "fixtures" / "results").glob("*/aggregate.json"):
        payload = json.loads(aggregate.read_text(encoding="utf-8"))
        assert (payload["runner_version"], payload["sdk_version"], payload["cli_version"]) \
            == ("0.2.6", "0.2.183", "2.1.326"), aggregate
    for config in (PLUGIN_ROOT / "tests").rglob("eval_config.json"):
        if "stale_runner" in config.parts:
            continue                       # stale on purpose (0.0.1)
        assert json.loads(config.read_text(encoding="utf-8"))["runner_version"] == "0.2.6", config
    assert "claude-agent-sdk==0.2.183" in read("tests/fixtures/agents/ci_ready/requirements.txt")


def test_the_stubs_report_the_new_pins():
    stub = read("tests/fixtures/stubs/claude_agent_sdk/__init__.py")
    assert '__version__ = "0.2.183"' in stub and '__cli_version__ = "2.1.326"' in stub
    assert '__cli_version__ = "2.1.326"' in read("tests/fixtures/stubs/claude_agent_sdk/_cli_version.py")
    fake = read("tests/fixtures/bin/fake_sdk.py")
    assert '"FAKE_SDK_VERSION", "0.2.183"' in fake and '"FAKE_SDK_CLI_VERSION", "2.1.326"' in fake


def test_the_sdk_venv_and_the_live_command_name_the_pin():
    conftest = read("tests/conftest.py")
    assert 'SDK_VENV_NAME = "casdk-venv-0.2.183"' in conftest
    assert 'SDK_VENV_FALLBACK = "casdk-venv-0.2.182"' in conftest, "the previous pin stays a fallback"
    assert "casdk-venv-0.2.183/bin/python" in read("tests/runner/test_live.py")


def test_the_surface_test_measured_the_new_pin():
    text = read("tests/lib/test_sdk_surface_live.py")
    assert 'MEASURED_SDK = "0.2.183"' in text and 'MEASURED_CLI = "2.1.326"' in text
    assert "Re-run 2026-11-17 against 0.2.183" in text
    assert '"client_app": (2864, "client_app: str | None = None")' in text
    assert '"ClaudeAgentOptions": (2392, "class ClaudeAgentOptions:")' in text
    assert '"ResultMessage": (1728, "class ResultMessage:")' in text
    assert "def test_result_message_has_user_message_uuid_fields" in text


def test_the_runner_stale_rubric_names_0_2_6():  # awaits lane B
    assert "0.2.6" in read("plugin-evals/runner-stale/graders/criteria.md")


def test_the_source_labels_name_the_new_wheel():
    assert read("lib/agent_sdk_skills/evalcase.py").count(
        '_SRC_OPTIONS = "claude_agent_sdk types.py:2392 ClaudeAgentOptions (0.2.183) (50 fields)"') == 1
    for relative in ("lib/agent_sdk_skills/budget.py", "lib/agent_sdk_skills/graders.py"):
        assert "types.py:1728 ResultMessage (0.2.183)" in read(relative), relative
    for relative in ("skills/agent-review/scripts/_checks.py", "skills/agent-review/scripts/lint_agent.py",
                     "skills/agent-harness/scripts/lint_harness.py"):
        text = read(relative)
        assert "claude-agent-sdk 0.2.183 types.py" in text and "claude-agent-sdk 0.2.182" not in text, relative


# -- 2. the surface and the moved lines -------------------------------------------

RESULT_FIELDS_0_2_183 = (
    "subtype", "duration_ms", "duration_api_ms", "is_error", "num_turns", "session_id",
    "stop_reason", "total_cost_usd", "usage", "result", "structured_output", "model_usage",
    "permission_denials", "deferred_tool_use", "errors", "api_error_status", "uuid",
    "terminal_reason", "origin", "user_message_uuid", "user_message_uuids",
)


def test_the_surface_test_lists_twenty_one_result_fields():
    surface = _load("tests/lib/test_sdk_surface_live.py", "surface_live_2026_11_17")
    assert surface.RESULT_MESSAGE_FIELDS == RESULT_FIELDS_0_2_183
    assert len(RESULT_FIELDS_0_2_183) == 21


def test_the_stub_declares_the_same_twenty_one_fields_and_the_uuid_pair_elsewhere():
    import subprocess
    import sys
    probe = ("import json, claude_agent_sdk as s;"
             "print(json.dumps([list(c.__dataclass_fields__) for c in "
             "(s.ResultMessage, s.AssistantMessage, s.StreamEvent)]))")
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60,
                          cwd=PLUGIN_ROOT / "tests" / "fixtures" / "stubs")
    assert proc.returncode == 0, proc.stderr
    result, assistant, stream = json.loads(proc.stdout)
    assert tuple(result) == RESULT_FIELDS_0_2_183
    assert assistant[-2:] == stream[-2:] == ["user_message_uuid", "user_message_uuids"]
    assert len(assistant) == 11 and len(stream) == 6


#: 0.2.182 anchors 0.2.183 moved. `types.py:1391` is 0.2.182's `AssistantMessage`.
PRE_SHIFT = ("types.py:2341", "types.py:2813", "types.py:1708", "types.py:1749", "types.py:1391",
             "2341-2813", "`:2813`", "`:2341`")


def _scanned():
    """Every tracked text file a citation can live in, except the history: the runner
    CHANGELOG and the `RENUMBERED`/`STALE`/`CITED` tables of the older sync tests."""
    roots = [SKILLS, PLUGIN_ROOT / "lib", PLUGIN_ROOT / "runner", PLUGIN_ROOT / "tests"]
    files = [p for root in roots for p in root.rglob("*")
             if p.is_file() and p.suffix in (".md", ".py") and "__pycache__" not in p.parts]
    files += [PLUGIN_ROOT / "README.md", PLUGIN_ROOT / "THIRD_PARTY_NOTICES.md"]
    return [p for p in files
            if p.name != "CHANGELOG.md" and not re.match(r"test_sync_.*\.py$", p.name)]


def test_no_tracked_file_cites_a_pre_shift_types_py_line():  # partly awaits lanes B/C
    offenders = []
    for path in _scanned():
        text = path.read_text(encoding="utf-8")
        for anchor in PRE_SHIFT:
            if re.search(re.escape(anchor) + r"(?!\d)", text):
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {anchor}")
    assert offenders == []


# -- 3. the runner ----------------------------------------------------------------

def test_the_runner_stamps_a_uuid_and_drains_to_its_result():
    import sys
    if str(PLUGIN_ROOT / "runner") not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT / "runner"))
    from agent_sdk_evals import SCHEMA_TRACE
    from agent_sdk_evals import session
    assert session.MAX_FOREIGN_RESULTS == 3
    assert callable(session.send_and_drain) and callable(session.user_message)
    assert SCHEMA_TRACE == "agent-sdk-skills.trace/1", "additive keys, same schema"
    text = read("runner/agent_sdk_evals/session.py")
    assert "uuid.uuid4().hex" in text and "types.py:1767-1786" in text
    assert "2.1.326" in text and "2.1.327" in text, "the measured echo is cited"


def test_the_capture_records_the_uuid_pair():
    text = read("runner/agent_sdk_evals/capture.py")
    assert "def user_turn(self, text: str, *, uuid: str | None = None)" in text
    assert '("user_message_uuid", "user_message_uuids")' in text
    assert "20 on 2.1.326" in text


def test_the_probe_session_still_sends_a_plain_string():
    assert 'await client.query("Reply with the single word: ready")' in read("runner/agent_sdk_evals/cli.py")


def test_the_changelog_records_the_release():
    text = read("runner/agent_sdk_evals/CHANGELOG.md")
    assert "## 0.2.6 — 2026-11-15" in text
    section = flat(text.split("## 0.2.6 — 2026-11-15", 1)[1].split("## 0.2.5", 1)[0])
    for needle in ("`user_message_uuid`", "+51", "`types.py:2392`", "send_and_drain",
                   "max_foreign_results = 3", "agent-sdk-skills.trace/1", "identical to 0.2.5",
                   "2.1.326", "2.1.327", "20 `capabilities`", "silent_resend_files_v1",
                   "`bypasspermissions`", "unattended runs can refuse them", '"$defaults"',
                   "no longer silent", "parallel mcp tool calls", "`continue: false` does not block",
                   "`overloaded`", "`server_error`", "`tool_deferred_unavailable`",
                   '"rulecontent": null', "`8ed58af`", "unreleased"):
        assert needle in section, needle


# -- 4. the 2.1.326 init fixture (CONTRACTS §22.3, §22.6) --------------------------

def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_2_1_326_init_fixture_pair_exists_and_is_scrubbed():
    for name in ("init_2_1_326.script.jsonl", "init_2_1_326.trace.jsonl"):
        text = (TRACES / name).read_text(encoding="utf-8")
        assert "sk-ant" not in text and "/Users/" not in text and "/private/var" not in text, name


def test_the_2_1_326_init_has_twenty_capabilities():
    init = _lines(TRACES / "init_2_1_326.script.jsonl")[0]
    assert (init["__class__"], init["subtype"]) == ("SystemMessage", "init")
    capabilities = init["data"]["capabilities"]
    assert len(capabilities) == len(set(capabilities)) == 20
    assert init["data"]["claude_code_version"] == "2.1.326"
    older = _lines(TRACES / "init_2_1_325.script.jsonl")[0]["data"]["capabilities"]
    assert set(capabilities) - set(older) == {"silent_resend_files_v1"}
    trace_init = [e for e in _lines(TRACES / "init_2_1_326.trace.jsonl") if e["type"] == "init"][0]
    assert trace_init["cli_version"] == "2.1.326" and trace_init["capabilities"] == capabilities


def test_the_2_1_326_result_echoes_the_uuid_the_user_event_carries():
    trace = _lines(TRACES / "init_2_1_326.trace.jsonl")
    assert [e["type"] for e in trace] == ["user", "init", "assistant_text", "result"]
    user, result = trace[0], trace[-1]
    assert user["uuid"] and result["user_message_uuid"] == user["uuid"]
    assert result["user_message_uuids"] == [user["uuid"]]


def test_the_fixture_is_registered_and_the_tests_read_it():
    readme = flat(read("tests/fixtures/README.md"))
    assert "`traces/init_2_1_326.*`" in readme and "11, 13, 14, 15, 19 and 20 `capabilities`" in readme
    assert "**`traces/init_2_1_326.script.jsonl`**" in readme
    assert "init_2_1_326" in read("tests/runner/test_runner_capture.py")
    assert "2.1.326" in read("tests/lib/test_trace.py")


# -- 5. the 45 articles -----------------------------------------------------------

ARTICLE_45 = "https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/"
DATE_45 = "2026-11-16"


def _articles_1_44():
    s14 = _load("tests/skills/test_sync_2026_11_14.py", "sync_2026_11_14_for_11_17")
    return s14._articles_1_41() + s14.ARTICLES_42_44


def test_there_are_forty_five_distinct_articles():
    assert len(set(_articles_1_44())) == 44
    assert len(set(_articles_1_44() + (ARTICLE_45,))) == 45
    assert ARTICLE_45.endswith("/"), "written as its canonical"


def test_third_party_notices_lists_all_forty_five():  # awaits lane B
    notices = read("THIRD_PARTY_NOTICES.md")
    missing = [u for u in _articles_1_44() + (ARTICLE_45,) if u not in notices]
    assert missing == []
    hygiene = _load("tests/test_plugin_hygiene.py", "plugin_hygiene_2026_11_17")
    distinct = {m.group(0).rstrip(".,;:") for m in hygiene.ARTICLE_URL.finditer(notices)}
    assert len(distinct & set(_articles_1_44() + (ARTICLE_45,))) == 45
    assert DATE_45 in notices


def test_article_45_is_cited_with_a_dated_parenthetical():  # awaits lanes B/C
    following = re.compile(re.escape(ARTICLE_45) + r">?\)?\s*\(\s*\"[^\"]+\",\s*" + DATE_45)
    citing = [p for p in skill_docs() if ARTICLE_45 in p.read_text(encoding="utf-8")]
    assert citing, ARTICLE_45
    assert any(following.search(p.read_text(encoding="utf-8")) for p in citing), \
        f"{ARTICLE_45} never followed by (\"title\", {DATE_45}, ...)"
    undated = [str(p.relative_to(PLUGIN_ROOT)) for p in citing
               if DATE_45 not in p.read_text(encoding="utf-8")]
    assert undated == [], f"{ARTICLE_45} without {DATE_45} in {undated}"


def test_article_45_is_framed_as_the_claude_code_teams_practice():  # awaits lanes B/C
    """#45 never mentions the Agent SDK (CONTRACTS §22, plan article table)."""
    citing = [p for p in skill_docs() if ARTICLE_45 in p.read_text(encoding="utf-8")]
    framed = [p for p in citing if "claude code team" in flat(p.read_text(encoding="utf-8"))]
    assert citing and framed == citing, \
        [str(p.relative_to(PLUGIN_ROOT)) for p in citing if p not in framed]


def test_the_readme_states_the_new_pins_and_read_date():  # awaits lane B
    text = flat(read("README.md"))
    assert "0.2.183" in text and "2.1.326" in text and "2026-11-17" in text
    assert "45 published anthropic articles" in text


# -- 6. lane needles --------------------------------------------------------------

def _offenders(pattern: str) -> list[str]:
    rx = re.compile(pattern)
    return [str(p.relative_to(PLUGIN_ROOT)) for p in sorted(SKILLS.rglob("*.md"))
            if rx.search(flat(p.read_text(encoding="utf-8")))]


def test_no_skill_file_lists_overloaded_as_a_stop_failure_error():  # awaits lane B
    assert _offenders(r"stopfailure[^.]{0,200}`overloaded`") == []


def test_no_skill_file_describes_max_buffer_size_in_bytes():  # awaits lane B
    assert _offenders(r"max(?:imum)? bytes when buffering") == []
    assert _offenders(r"`max_buffer_size`[^.|]{0,80}\bbytes\b") == []


def test_no_skill_file_says_an_at_mention_guarantees_the_subagent():  # awaits lanes B/C
    assert _offenders(r"(?:@-mention|mention it by name|naming (?:a|the) subagent)[^.]{0,80}guarantee") == []


def test_no_skill_file_says_the_memory_field_stores_codebase_patterns():  # awaits lane C
    assert _offenders(r"`memory`[^.]{0,120}codebase patterns") == []


LANE_PRESENT: tuple[tuple[str, tuple[str, ...]], ...] = (
    # from .dev/lanes/2026-11-17/lane-{B,C}-needles.md; each greps exactly once (flattened, lower-cased)
    # lane B
    ('skills/agent-harness/references/hooks-catalog.md',
     ("doesn't block a `PreToolUse` call** — also return", "is how the Claude Code team puts cheap", "the overload value left its matcher list", "a `prompt`/`agent` hook over 4,000,000 characters doesn't run", "the pinned 0.2.183 (bundled cli 2.1.326) has all of this")),
    ('skills/agent-harness/references/permission-model.md',
     ("serialises as `{\"toolName\": \"WebSearch\", \"ruleContent\": null}`", "**2.1.326 asks more, and refuses where no one can answer**", "works with the permission mode you're in", "replaces every built-in entry in Agent SDK apps too")),
    ('skills/agent-harness/references/context-and-settings.md',
     ("## Streaming input and matching results", "one `receive_response()` loop per response", "the uuid comes back verbatim in `user_message_uuid`", "give each its own copy with `fork_session=True`")),
    ('skills/agent-harness/references/subagent-design.md',
     ("naming a subagent asks, it doesn't force",)),
    ('skills/agent-harness/references/mcp-patterns.md',
     ("typescript diverges, python doesn't follow (0.2.183)", "`_internal/transport/subprocess_cli.py:635-641`")),
    ('skills/agent-review/references/options-reference.md',
     ("**in characters** (the docs; the sdk's error text says bytes)", "goes out as `\"rulecontent\": null`", "except in an anthropic-hosted environment")),
    ('skills/agent-review/references/model-policy.md',
     ("as of 2026-11-17", "skips fallback entries auto mode doesn't support")),
    ('skills/agent-review/references/review-checklist.md',
     ("`continue_: false` alone does **not** block a `pretooluse` call",)),
    ('skills/agent-deploy/references/hosting-options.md',
     ("claude models on google cloud (anthropic managed)", "`allowedproviders` names it `\"anthropicgooglecloud\"`")),
    ('skills/agent-deploy/references/secure-deployment.md',
     ("is **not enforced in an anthropic-hosted environment**",)),
    ('skills/agent-deploy/references/observability-otel.md',
     ("`otel_resource_include_host`",)),
    ('skills/agent-debug/references/failure-shapes.md',
     ("## result for another prompt", "## transport stops", "prompt stream failed; closing stdin")),
    ('skills/agent-sdk/references/environment.md',
     ("**2.1.326 and 2.1.327 send 20**", "is **2.1.327** (npm `next`")),
    ('skills/agent-sdk/references/glossary.md',
     ("**injected turn**", "**user message uuid**", "**observe mode**")),
    ('skills/eval-run/references/running-in-ci.md',
     ("`--fork-session` (`fork_session=true`)",)),
    ('skills/eval-ci/references/subscription-and-secrets.md',
     ("**billed to that credential's organization**",)),
    ('plugin-evals/README.md',
     ("shell grants refused on a managed machine", "the local `claude` is **2.1.327**")),
    ('README.md',
     ("45 published anthropic articles", "documentation read at claude code 2.1.326 (2026-11-17)", "**every prompt is matched to its result.**")),
    ('THIRD_PARTY_NOTICES.md',
     ("snapshot: `8ed58af`", "snapshot: `2e33617`", "snapshot: `e4bb5d9`", "and article 45 on 2026-11-17")),
    # lane C
    ('skills/agent-design/references/agent-loop.md',
     ("**Verify before you stop.**", "codifies how to start and drive the app in a `verify` skill", "\"If a check is still failing after", "count fix rounds in your own code", "https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/")),
    ('skills/eval-criteria/references/grader-catalog.md',
     ("## Graders the agent cannot reach", "**Prefer end-to-end graders.**", "**A flaky grader trains retries.**", "never let a grader pass because it was run again")),
    ('skills/eval-analyze/references/reliability.md',
     ("## Scoring a checker: reviewers, bug finders and judges", "**size-matched control set**", "**measure recall per stage**", "keep the **tuning set apart from the fixed test set**")),
    ('skills/eval-ci/references/tiered-pipeline.md',
     ("## Start a new gate in observe mode", "not for an eval gate, and a grader or tier must never")),
    ('skills/eval-create/references/memory-and-multiturn.md',
     ("every run's `env` carries `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`",)),
)

LANE_ABSENT: tuple[tuple[str, tuple[str, ...]], ...] = (
    # each greps zero times; `types.py:2392-2864` (options-reference, twice) dropped from PRESENT as ambiguous
    # lane B
    ('skills/agent-harness/references/hooks-catalog.md',
     ("how a hook halts a turn on any event", "halts a turn on any event", "(2.1.299–2.1.325)", "the pinned 0.2.182 (bundled cli 2.1.325)")),
    ('skills/agent-review/references/options-reference.md',
     ("types.py:2341-2813", "| `max_buffer_size` | `int \\| none` | `none` | o | |", "maximum bytes when buffering")),
    ('skills/agent-review/references/model-policy.md',
     ("as of 2026-11-14", "the date passed 24 days ago")),
    ('skills/agent-harness/references/mcp-patterns.md',
     ("has no such call at 0.2.182",)),
    ('skills/agent-sdk/references/environment.md',
     ("`types.py:2813`", "`claude-agent-sdk` **0.2.182** with its bundled claude code **2.1.325**")),
    ('skills/agent-sdk/SKILL.md',
     ("0.2.182 with bundled claude code 2.1.325",)),
    ('README.md',
     ("44 published anthropic articles", "documentation read at claude code 2.1.325 (2026-11-14)")),
    ('THIRD_PARTY_NOTICES.md',
     ("snapshot: `4720d36`", "snapshot: `f1f87e5`")),
    ('plugin-evals/runner-stale/graders/criteria.md',
     ("`0.2.5` for the other side",)),
    # lane C
    ('skills/eval-create/references/memory-and-multiturn.md',
     ("but does not set `CLAUDE_CODE_DISABLE_AUTO_MEMORY`", "starts with an empty one (our reading of the memory docs)")),
)


@pytest.mark.parametrize("relative,needles", LANE_PRESENT, ids=[r for r, _ in LANE_PRESENT])
def test_lane_facts_are_present(relative, needles):  # awaits lanes B/C
    text = flat(read(relative))
    missing = [n for n in needles if n.lower() not in text]
    assert missing == [], f"{relative}: missing {missing}"


@pytest.mark.parametrize("relative,needles", LANE_ABSENT, ids=[r for r, _ in LANE_ABSENT])
def test_lane_stale_wording_is_gone(relative, needles):  # awaits lanes B/C
    text = flat(read(relative))
    present = [n for n in needles if n.lower() in text]
    assert present == [], f"{relative}: still says {present}"
