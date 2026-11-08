"""What the 2026-11-14 sync changed in the pins, the version, the model policy, the init fixture and the articles.

Tests for the ninth upstream sync: claude-agent-sdk 0.2.182 (0.2.180 was CLI-only;
0.2.181 and 0.2.182 add the `client_app` option and move `types.py` by 21 lines),
bundled Claude Code 2.1.325, docs re-read at 2.1.325 (52 pages with lastmod
2026-11-12 to 2026-11-14), Claude Fable 5.2 in the model policy, three more
Anthropic articles (42-44) and release 0.2.5. Written from the plan
(`.claude/plans/write-detailed-plan-on-quiet-ladybug.md`),
`.dev/UPSTREAM-DELTA-2026-11-14.md` and `.dev/CONTRACTS.md` §21. The needle
tuples (``LANE_PRESENT``, ``LANE_ABSENT``) are plain data, as in the earlier sync
tests.

1. **Pins and version**: 0.2.182 / 2.1.325 / docs 2.1.325, minimum 0.2.140,
   release 0.2.5 in every carrier, the venv named for the pin (0.2.180 kept as
   the fallback), the runner-stale rubric names 0.2.5.
2. **The option list** has 50 entries ending in `client_app`, and the cited
   `types.py` lines moved with the wheel (CONTRACTS §21.2).
3. **The model policy** lists Fable 5.2 as current and keeps Fable 5.1 current;
   the default-model sentence no longer says Claude Code defaults to Fable
   (CONTRACTS §21.5, §21.6).
4. **The 2.1.325 init fixture**: 19 capabilities, the four new ones recorded,
   never required; the result is the revoked-key shape (CONTRACTS §21.4).
5. **The 44 Anthropic articles** are listed in `THIRD_PARTY_NOTICES.md`, and each
   of the three new ones is cited by a skill file with a dated parenthetical.
6. **Stale wording is gone**: `best` resolving to Fable, `denyInsteadOfPrompting`
   as changelog-only, the `mcp_task` TS-only note, the old sandbox default
   (CONTRACTS §21.7).
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

NEW_NOTE = "re-read 2026-11-14 against claude-agent-sdk 0.2.182 / claude code 2.1.325 docs"


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

def test_the_pins_moved_to_0_2_182_and_2_1_325():
    import agent_sdk_skills as plugin
    assert (plugin.SDK_TARGET, plugin.CLI_BUNDLED_WITH_TARGET) == ("0.2.182", "2.1.325")
    assert plugin.DOCS_READ_AT_CLI == "2.1.325"
    assert plugin.SDK_MIN_SUPPORTED == "0.2.140", "the minimum does not move with the pin"
    assert 'DOCS_READ_AT_CLI = "2.1.325"' in read("runner/agent_sdk_evals/__init__.py")


def test_the_docs_re_read_is_dated_next_to_the_constant():
    note = "docs re-read 2026-11-14 (lastmod 2026-11-12/13/14), cli 2.1.325"
    assert note in flat(read("lib/agent_sdk_skills/__init__.py"))
    assert note in flat(read("runner/agent_sdk_evals/__init__.py"))


def test_the_library_records_the_types_py_shift():
    text = flat(read("lib/agent_sdk_skills/__init__.py"))
    assert "0.2.180 (2026-11-09) is cli-only" in text
    assert "`client_app` option (`types.py:2813`" in text and "50th field" in text
    assert "2808 on by 21" in text and "checked 2026-11-14" in text


def test_the_release_is_0_2_5_everywhere_lane_a_owns():
    import agent_sdk_skills as plugin
    assert plugin.__version__ == plugin.RUNNER_VERSION == "0.2.5"
    assert read("runner/agent_sdk_evals/VERSION").strip() == "0.2.5"
    assert json.loads(read(".claude-plugin/plugin.json"))["version"] == "0.2.5"
    assert 'version = "0.2.5"' in read("pyproject.toml")
    assert read("tests/fixtures/agents/ci_ready/evals/runner/agent_sdk_evals/VERSION").strip() == "0.2.5"


def test_the_fixtures_carry_0_2_5_and_the_new_pins():
    """Synthetic fixtures follow the pin; the measured `init_2_1_3xx` traces are history."""
    for aggregate in (PLUGIN_ROOT / "tests" / "fixtures" / "results").glob("*/aggregate.json"):
        payload = json.loads(aggregate.read_text(encoding="utf-8"))
        assert (payload["runner_version"], payload["sdk_version"], payload["cli_version"]) \
            == ("0.2.5", "0.2.182", "2.1.325"), aggregate
    for config in (PLUGIN_ROOT / "tests").rglob("eval_config.json"):
        if "stale_runner" in config.parts:
            continue                       # stale on purpose (0.0.1)
        assert json.loads(config.read_text(encoding="utf-8"))["runner_version"] == "0.2.5", config
    assert "claude-agent-sdk==0.2.182" in read("tests/fixtures/agents/ci_ready/requirements.txt")


def test_the_stubs_report_the_new_pins_and_the_new_option():
    stub = read("tests/fixtures/stubs/claude_agent_sdk/__init__.py")
    assert '__version__ = "0.2.182"' in stub and '__cli_version__ = "2.1.325"' in stub
    assert "client_app: str | None = None" in stub
    assert '__cli_version__ = "2.1.325"' in read("tests/fixtures/stubs/claude_agent_sdk/_cli_version.py")
    fake = read("tests/fixtures/bin/fake_sdk.py")
    assert '"FAKE_SDK_VERSION", "0.2.182"' in fake and '"FAKE_SDK_CLI_VERSION", "2.1.325"' in fake


def test_the_sdk_venv_and_the_live_command_name_the_pin():
    conftest = read("tests/conftest.py")
    assert 'SDK_VENV_NAME = "casdk-venv-0.2.182"' in conftest
    assert 'SDK_VENV_FALLBACK = "casdk-venv-0.2.180"' in conftest, "the previous pin stays a fallback"
    assert "casdk-venv-0.2.182/bin/python" in read("tests/runner/test_live.py")


def test_the_surface_test_measured_the_new_pin():
    text = read("tests/lib/test_sdk_surface_live.py")
    assert 'MEASURED_SDK = "0.2.182"' in text and 'MEASURED_CLI = "2.1.325"' in text
    assert "Re-run 2026-11-14 against 0.2.182" in text
    assert '"client_app": (2813, "client_app: str | None = None")' in text


def test_the_runner_stale_rubric_names_0_2_5():
    assert "0.2.5" in read("plugin-evals/runner-stale/graders/criteria.md")


# -- 2. the option list and the moved lines -------------------------------------------

def test_the_option_list_has_fifty_entries_ending_in_client_app():
    import agent_sdk_skills as plugin
    from agent_sdk_evals import OPTION_NAMES as runner_names
    assert len(plugin.OPTION_NAMES) == 50 and plugin.OPTION_NAMES[-1] == "client_app"
    assert tuple(runner_names) == tuple(plugin.OPTION_NAMES)
    assert "client_app" in plugin.OVERRIDABLE_OPTIONS, "a case may set its own app label"
    assert "50 fields" in read("lib/agent_sdk_skills/evalcase.py")


def test_no_tracked_file_cites_a_pre_shift_types_py_line():
    """Every cited line >= 284 moved (CONTRACTS §21.2); the old anchors must be gone."""
    stale = {"types.py:2339", "types.py:2504", "types.py:2719", "types.py:2799", "types.py:1706",
             "types.py:864", "types.py:1137", "types.py:2393", "types.py:2567", "types.py:2666"}
    offenders = []
    for path in list(SKILLS.rglob("*.md")) + list(SKILLS.rglob("*.py")) + \
            list((PLUGIN_ROOT / "lib").rglob("*.py")) + list((PLUGIN_ROOT / "runner").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for anchor in stale:
            if re.search(re.escape(anchor) + r"(?!\d)", text):
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {anchor}")
    assert offenders == []


def test_the_option_table_cites_the_new_class_line_and_client_app():  # lane B
    text = read("skills/agent-review/references/options-reference.md")
    assert "types.py:2341" in text and "types.py:2813" in text
    assert "`client_app`" in text


# -- 3. the model policy -------------------------------------------------------------------

def test_fable_5_2_is_current_and_fable_5_1_stays_current():
    import agent_sdk_skills as plugin
    from agent_sdk_evals import CURRENT_MODELS as runner_current
    from agent_sdk_skills.env import classify_model_id
    assert "claude-fable-5-2" in plugin.CURRENT_MODELS and "claude-fable-5-1" in plugin.CURRENT_MODELS
    assert tuple(runner_current) == tuple(plugin.CURRENT_MODELS)
    assert classify_model_id("claude-fable-5-2") == "current"
    assert classify_model_id("claude-fable-5-1") == "current"
    assert "claude-fable-5-2" not in plugin.DEPRECATED_MODELS
    assert "claude-fable-5-1" not in plugin.DEPRECATED_MODELS and "claude-fable-5-1" not in plugin.RETIRING_MODELS


def test_the_suggestion_strings_name_fable_5_2():
    assert "claude-haiku-5-5, claude-fable-5-2)" in read("skills/agent-review/scripts/lint_agent.py")


def test_the_default_model_sentence_no_longer_says_fable_is_the_default():
    """CONTRACTS §21.6: the 2026-10-11 Fable figure came from subscription auth."""
    for relative in ("lib/agent_sdk_skills/eval_config.py", "skills/agent-review/scripts/lint_agent.py"):
        text = flat(read(relative))
        assert "the cli default (claude-fable-5-1) cost" not in text, relative
        assert "measured at claude-fable-5-1 and cost" not in text, relative
        assert "claude-opus-5-5" in text, relative
        assert "subscription" in text, relative


def test_model_policy_reference_lists_fable_5_2_and_marks_5_1_legacy():  # lane B
    text = flat(read("skills/agent-review/references/model-policy.md"))
    assert "`claude-fable-5-2`" in text
    assert "$8 / $40" in text or "$8/$40" in text
    assert "legacy" in text
    assert "`best` → `opus`" in text or "`best` resolves to the same model as `opus`" in text
    assert "claude-opus-5-5` | $0.0667" in text or "$0.0667" in text


# -- 4. the 2.1.325 init fixture (CONTRACTS §21.4) -----------------------------------------

def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


NEW_CAPABILITIES = {"reload_plugins_refuse_if_busy_v1", "ui_pane_widget_v1",
                    "voice_call_talk_line_v1", "withdrawn_files_note_v2"}


def test_the_2_1_325_init_fixture_pair_exists_and_is_scrubbed():
    for name in ("init_2_1_325.script.jsonl", "init_2_1_325.trace.jsonl"):
        text = (TRACES / name).read_text(encoding="utf-8")
        assert "sk-ant" not in text and "/Users/" not in text and "/private/var" not in text, name


def test_the_2_1_325_init_has_nineteen_capabilities():
    script = _lines(TRACES / "init_2_1_325.script.jsonl")
    init = script[0]
    assert (init["__class__"], init["subtype"]) == ("SystemMessage", "init")
    capabilities = init["data"]["capabilities"]
    assert len(capabilities) == len(set(capabilities)) == 19
    assert init["data"]["claude_code_version"] == "2.1.325"
    older = _lines(TRACES / "init_2_1_319.script.jsonl")[0]["data"]["capabilities"]
    assert set(capabilities) - set(older) == NEW_CAPABILITIES
    assert "memory_paths" not in init["data"], "auto memory was off for the run"
    trace = _lines(TRACES / "init_2_1_325.trace.jsonl")[0]
    assert trace["type"] == "init" and trace["cli_version"] == "2.1.325"
    assert trace["capabilities"] == capabilities


def test_the_2_1_325_fixture_holds_the_revoked_key_result_shape():
    script = _lines(TRACES / "init_2_1_325.script.jsonl")
    assert [m["__class__"] for m in script] == ["SystemMessage", "AssistantMessage", "ResultMessage"]
    assistant, result = script[1], script[2]
    assert assistant["model"] == "<synthetic>" and assistant["error"] == "authentication_failed"
    assert (result["subtype"], result["is_error"], result["api_error_status"]) == ("success", True, 401)
    assert result["terminal_reason"] == "api_error" and result["total_cost_usd"] == 0
    trace_result = [e for e in _lines(TRACES / "init_2_1_325.trace.jsonl") if e["type"] == "result"][0]
    assert trace_result["is_error"] is True and trace_result["terminal_reason"] == "api_error"


def test_the_fixture_is_registered_and_the_capture_comment_counts_it():
    readme = flat(read("tests/fixtures/README.md"))
    assert "`traces/init_2_1_325.*`" in readme and "11, 13, 14, 15 and 19 `capabilities`" in readme
    assert "**`traces/init_2_1_325.script.jsonl`**" in readme
    assert "19 on 2.1.325" in flat(read("runner/agent_sdk_evals/capture.py"))
    assert "init_2_1_325" in read("tests/runner/test_runner_capture.py")


# -- 5. the 44 articles -----------------------------------------------------------------

CLAUDE_DEV = "https://claude.dev/blog/{}/"
ARTICLE_42 = CLAUDE_DEV.format("which-claude-model-should-you-build-with")
ARTICLE_43 = CLAUDE_DEV.format("safely-scaling-multi-agent-teams-with-fable-5-2")
ARTICLE_44 = "https://www.anthropic.com/research/building-strong-safety-evaluations"
ARTICLES_42_44 = (ARTICLE_42, ARTICLE_43, ARTICLE_44)
DATES_42_44 = {ARTICLE_42: "2026-11-09", ARTICLE_43: "2026-11-09", ARTICLE_44: "2026-11-13"}
IDS_42_44 = ("model-choice", "multi-agent-teams", "safety-evals")


def _articles_1_41():
    s02 = _load("tests/skills/test_sync_2026_11_02.py", "sync_2026_11_02_for_11_14")
    s04 = _load("tests/skills/test_sync_2026_11_04.py", "sync_2026_11_04_for_11_14")
    s05 = _load("tests/skills/test_sync_2026_11_05.py", "sync_2026_11_05_for_11_14")
    s08 = _load("tests/skills/test_sync_2026_11_08.py", "sync_2026_11_08_for_11_14")
    return s02.ARTICLES_1_14 + s02.ARTICLES_15_23 + s04.ARTICLES_24_25 + s05.ARTICLES_26_29 + s08.ARTICLES_30_41


def test_there_are_forty_four_distinct_articles():
    assert len(set(_articles_1_41())) == 41
    assert len(set(_articles_1_41() + ARTICLES_42_44)) == 44


def test_the_new_urls_are_written_as_their_canonicals():
    assert ARTICLE_42.endswith("/") and ARTICLE_43.endswith("/")
    assert not ARTICLE_44.endswith("/")


def test_third_party_notices_lists_all_forty_four():  # lane B
    notices = read("THIRD_PARTY_NOTICES.md")
    missing = [u for u in _articles_1_41() + ARTICLES_42_44 if u not in notices]
    assert missing == []
    hygiene = _load("tests/test_plugin_hygiene.py", "plugin_hygiene_2026_11_14")
    distinct = {m.group(0).rstrip(".,;:") for m in hygiene.ARTICLE_URL.finditer(notices)}
    assert len(distinct & set(_articles_1_41() + ARTICLES_42_44)) == 44


@pytest.mark.parametrize("url", ARTICLES_42_44, ids=IDS_42_44)
def test_each_new_article_is_cited_by_at_least_one_skill_file(url):  # lanes B/C
    assert any(url in p.read_text(encoding="utf-8") for p in skill_docs()), url


@pytest.mark.parametrize("url", ARTICLES_42_44, ids=IDS_42_44)
def test_each_new_article_citation_is_followed_by_a_dated_parenthetical(url):  # lanes B/C
    following = re.compile(re.escape(url) + r">?\)?\s*\(\s*\"[^\"]+\",\s*" + DATES_42_44[url])
    citing = [p for p in skill_docs() if url in p.read_text(encoding="utf-8")]
    assert citing, url
    assert any(following.search(p.read_text(encoding="utf-8")) for p in citing), \
        f"{url} never followed by (\"title\", {DATES_42_44[url]}, ...)"
    undated = [str(p.relative_to(PLUGIN_ROOT)) for p in citing
               if DATES_42_44[url] not in p.read_text(encoding="utf-8")]
    assert undated == [], f"{url} without {DATES_42_44[url]} in {undated}"


def test_the_articles_that_never_mention_the_sdk_are_framed():  # lanes B/C
    """#43 and #44 do not mention the Agent SDK (CONTRACTS §21.8)."""
    for url in (ARTICLE_43, ARTICLE_44):
        citing = [p for p in skill_docs() if url in p.read_text(encoding="utf-8")]
        framed = [p for p in citing if re.search(r"no (?:agent )?sdk mention|never mentions? the (?:agent )?sdk|not (?:about|an) (?:the )?(?:agent )?sdk",
                                                 flat(p.read_text(encoding="utf-8")))]
        assert framed, f"{url} cited without saying the article never mentions the SDK"


# -- 6. stale wording is gone ------------------------------------------------------------------

def _offenders(pattern: str) -> list[str]:
    rx = re.compile(pattern)
    return [str(p.relative_to(PLUGIN_ROOT)) for p in sorted(SKILLS.rglob("*.md"))
            if rx.search(flat(p.read_text(encoding="utf-8")))]


def test_no_skill_file_says_best_resolves_to_fable():  # lane B
    assert _offenders(r"`best` (?:resolves to|uses|means|→) (?:the )?(?:`fable`|fable)") == []


def test_no_skill_file_calls_deny_instead_of_prompting_changelog_only():  # lane B
    assert _offenders(r"denyinsteadofprompting[^.]{0,80}changelog-only") == []


def test_no_skill_file_keeps_the_mcp_task_ts_only_note():  # lane B
    assert _offenders(r"`mcp_task`[^.]{0,120}(?:typescript|ts)[- ]only") == []


def test_no_skill_file_says_the_sandbox_auto_approves_by_default():  # lane B
    assert _offenders(r"autoallowbashifsandboxed[^.]{0,60}default(?:s)? (?:of |to |is )?`?true") == []


def test_no_skill_file_says_the_fable_alias_resolves_to_5_1():  # lane B
    assert _offenders(r"`fable`[^.]{0,40}resolves to fable 5\.1") == []


# -- lane needles -----------------------------------------------------------------------------

LANE_PRESENT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("skills/agent-review/references/model-policy.md",
     ("start most work on opus 5.5 at `medium`", "raise effort one level before moving up a model",
      "nothing changes when claude code, claude managed agents or the agent sdk build the requests")),
    ("skills/agent-harness/references/subagent-design.md",
     ("the built-in explore subagent runs on the parent conversation's model",)),
    ("skills/agent-harness/references/permission-model.md",
     ("`permissions.denyinsteadofprompting`", "no approval surface in this session",
      "written **without a specifier**")),
    ("skills/agent-harness/references/hooks-catalog.md",
     ("`rulecontent`", "no verdict")),
    ("skills/agent-review/references/options-reference.md",
     ("`client_app`", "settings that cannot be loaded raise `cliconnectionerror`")),
    ("skills/agent-deploy/references/cost-controls.md",
     ("the prompt cache belongs to the model that wrote it",)),
    ("skills/agent-deploy/references/secure-deployment.md",
     ("one sandbox vm per agent",)),
    ("skills/agent-deploy/references/observability-otel.md",
     ("`claude_code.safety_event` is withdrawn",)),
    ("skills/agent-design/references/subagent-decisions.md",
     ("agents misjudge difficulty and give up early",)),
    ("skills/agent-design/references/agent-loop.md",
     ("a turn can end before the work is done",)),
    ("skills/eval-criteria/references/grader-catalog.md",
     ("validate the grader against human labels",)),
    ("skills/eval-analyze/references/reliability.md",
     ("preregister", "100 items", "1,000")),
    ("skills/agent-sdk/references/environment.md",
     ("2.1.325 sends 19 `capabilities`",)),
)

LANE_ABSENT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("skills/agent-harness/references/permission-model.md",
     ("**changelog-only**: the settings page read 2026-11-08 does not list it",)),
    ("skills/agent-review/references/model-policy.md",
     ("| `claude -p` (no `--model`) | `claude-fable-5-1` | $0.3397 |",)),
    ("skills/agent-deploy/references/cost-controls.md",
     ("`claude-fable-5-1` and cost $0.3397 for the same prompt",)),
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
