"""What the 2026-11-08 sync changed in the pins, the version, the init fixture and the articles.

Tests for the eighth upstream sync: claude-agent-sdk 0.2.179, a CLI-only release
whose bundled Claude Code is 2.1.319 (`types.py` byte-identical to 0.2.178, so
every `types.py:N` citation holds), docs re-read at 2.1.319 (17 pages with
lastmod 2026-11-06/07), twelve more Anthropic articles (30-41, the first a new
agent-design reference on memory) and release 0.2.4. Written from the plan
(`.claude/plans/write-detailed-plan-on-quiet-ladybug.md` §2a),
`.dev/UPSTREAM-DELTA-2026-11-08.md` and `.dev/CONTRACTS.md` §20. Lane A wrote this
file while lanes B and C were still working: every assertion marked
``# awaits lane B`` / ``# awaits lane C`` reads a file one of them owns. The
needle tuples (``LANE_PRESENT``, ``LANE_ABSENT``) are plain data so the lanes'
exact wording can be appended without touching the test functions.

1. **Pins and version**: 0.2.179 / 2.1.319 / docs 2.1.319, minimum 0.2.140,
   release 0.2.4 in every carrier, the venv named for the pin (0.2.178 kept as
   the fallback), the runner-stale rubric names 0.2.4.
2. **The changelog** records a CLI-only release and cites the release page, not a
   changelog entry the tag does not have.
3. **The 2.1.319 init fixture**: 15 capabilities, the new one recorded, never
   required (CONTRACTS §20.2).
4. **The 41 Anthropic articles** are listed in `THIRD_PARTY_NOTICES.md`, and each
   of the twelve new ones is cited by a skill file with a dated parenthetical.
5. **`memory-design.md`** exists within the size limits and is linked.
6. **Stale wording is gone**: the Monitor rule (CONTRACTS §20.4), path rules
   (§20.5) and auto memory in SDK sessions (§20.9).
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

NEW_NOTE = "re-read 2026-11-08 against claude-agent-sdk 0.2.179 / claude code 2.1.319 docs"


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


def _paragraphs(text: str):
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


# -- 1. pins and version ----------------------------------------------------------

def test_the_pins_moved_to_0_2_179_and_2_1_319():
    # 0.2.179 / 2.1.319 at this sync; the pins only move forward (0.2.182 / 2.1.325 from 2026-11-14).
    import agent_sdk_skills as plugin
    assert (plugin.SDK_TARGET, plugin.CLI_BUNDLED_WITH_TARGET) == ("0.2.182", "2.1.325")
    assert plugin.DOCS_READ_AT_CLI == "2.1.325"
    assert plugin.SDK_MIN_SUPPORTED == "0.2.140", "the minimum does not move with the pin"
    assert 'DOCS_READ_AT_CLI = "2.1.325"' in read("runner/agent_sdk_evals/__init__.py")


def test_the_docs_re_read_is_dated_next_to_the_constant():
    note = "docs re-read 2026-11-08 (lastmod 2026-11-06/07), cli 2.1.319"
    assert note in flat(read("lib/agent_sdk_skills/__init__.py"))
    assert note in flat(read("runner/agent_sdk_evals/__init__.py"))


def test_the_library_says_types_py_did_not_change():
    text = flat(read("lib/agent_sdk_skills/__init__.py"))
    assert "0.2.179 (2026-11-06) is a cli-only release" in text
    assert "byte-identical to 0.2.178" in text


def test_the_release_is_0_2_4_everywhere_lane_a_owns():
    import agent_sdk_skills as plugin
    # 0.2.4 at this sync; the release follows the current constants (0.2.5 from 2026-11-14).
    assert plugin.__version__ == plugin.RUNNER_VERSION == "0.2.5"
    assert read("runner/agent_sdk_evals/VERSION").strip() == "0.2.5"
    assert json.loads(read(".claude-plugin/plugin.json"))["version"] == "0.2.5"
    assert 'version = "0.2.5"' in read("pyproject.toml")
    assert read("tests/fixtures/agents/ci_ready/evals/runner/agent_sdk_evals/VERSION").strip() == "0.2.5"


def test_the_fixtures_carry_0_2_4_and_the_new_pins():
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


def test_the_stubs_report_the_new_pins():
    stub = read("tests/fixtures/stubs/claude_agent_sdk/__init__.py")
    assert '__version__ = "0.2.182"' in stub and '__cli_version__ = "2.1.325"' in stub
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
    assert "Re-run 2026-11-08 against 0.2.179" in text


def test_the_runner_stale_rubric_names_0_2_4():  # awaits lane B
    assert "0.2.5" in read("plugin-evals/runner-stale/graders/criteria.md")


# -- 2. the changelog -----------------------------------------------------------------

def _section() -> str:
    text = read("runner/agent_sdk_evals/CHANGELOG.md")
    assert "## 0.2.4 — 2026-11-08" in text
    return text.split("## 0.2.4 — 2026-11-08", 1)[1].split("## 0.2.3", 1)[0]


def test_the_changelog_records_a_cli_only_release():
    section = flat(_section())
    for needle in ("cli-only release", "byte-identical", "types.py:<line>` citation holds",
                   "releases/tag/v0.2.179", "v0.2.178...v0.2.179",
                   "one runner behaviour changed", "what a 0.2.3 copy should know",
                   "the runner disables claude code auto memory in eval runs so runs stay independent",
                   "claude_code_disable_auto_memory=1",
                   "15 `capabilities`", "mcp_call_check_permissions_v1", "never requires them",
                   "exits 1", "full disk", "claude_code_disable_mcp_task_background",
                   "claude_code_drop_unavailable_deferred_tool", "identical to 2.1.318's",
                   'docs_read_at_cli = "2.1.319"'):
        assert needle in section, needle


def test_the_runner_turns_auto_memory_off_for_every_run():
    """CONTRACTS §20.9: auto memory reaches SDK sessions whatever `setting_sources` says."""
    runner = read("runner/agent_sdk_evals/__init__.py")
    assert 'RUN_ENV_DEFAULTS = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}' in runner
    assert "env=run_options_env(options)" in read("runner/agent_sdk_evals/session.py")
    assert "claude_code_disable_auto_memory=1" in flat(read("runner/agent_sdk_evals/README.md"))


def test_the_changelog_never_cites_a_0_2_179_changelog_entry():
    """The v0.2.179 tag has no CHANGELOG entry (CONTRACTS §20.1)."""
    section = flat(_section())
    assert "the 0.2.179 changelog" not in section
    assert "no changelog entry" in section


# -- 3. the 2.1.319 init fixture (CONTRACTS §20.2) -------------------------------------

def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_2_1_319_init_fixture_pair_exists_and_is_scrubbed():
    for name in ("init_2_1_319.script.jsonl", "init_2_1_319.trace.jsonl"):
        text = (TRACES / name).read_text(encoding="utf-8")
        assert "sk-ant" not in text and "/Users/" not in text, name


def test_the_2_1_319_init_has_fifteen_capabilities():
    script = _lines(TRACES / "init_2_1_319.script.jsonl")
    init = script[0]
    assert (init["__class__"], init["subtype"]) == ("SystemMessage", "init")
    capabilities = init["data"]["capabilities"]
    assert len(capabilities) == len(set(capabilities)) == 15
    assert "mcp_call_check_permissions_v1" in capabilities
    assert init["data"]["claude_code_version"] == "2.1.319"
    older = _lines(TRACES / "init_2_1_316.script.jsonl")[0]["data"]["capabilities"]
    assert set(capabilities) - set(older) == {"mcp_call_check_permissions_v1"}
    trace = _lines(TRACES / "init_2_1_319.trace.jsonl")[0]
    assert trace["type"] == "init" and trace["cli_version"] == "2.1.319"
    assert trace["capabilities"] == capabilities


def test_the_fixture_is_registered_and_the_capture_comment_counts_it():
    readme = flat(read("tests/fixtures/README.md"))
    assert "`traces/init_2_1_319.*`" in readme and "11, 13, 14, 15 and 19 `capabilities`" in readme
    assert "**`traces/init_2_1_319.script.jsonl`**" in readme
    assert "15 on 2.1.319" in flat(read("runner/agent_sdk_evals/capture.py"))
    assert "init_2_1_319" in read("tests/runner/test_runner_capture.py")
    assert "2.1.319" in read("tests/lib/test_trace.py")


# -- 4. the 41 articles -----------------------------------------------------------------

ARTICLE_30 = "https://www.anthropic.com/research/components-of-agent-memory"
CLAUDE_DEV = "https://claude.dev/blog/{}/"
ARTICLES_30_41 = (
    ARTICLE_30,
    CLAUDE_DEV.format("seeing-like-an-agent"),
    CLAUDE_DEV.format("lessons-from-building-claude-code-prompt-caching-is-everything"),
    CLAUDE_DEV.format("using-claude-code-the-unreasonable-effectiveness-of-html"),
    CLAUDE_DEV.format("a-harness-for-every-task-dynamic-workflows-in-claude-code"),
    CLAUDE_DEV.format("lessons-from-building-claude-code-how-we-use-skills"),
    CLAUDE_DEV.format("the-new-rules-of-context-engineering-for-claude-5-generation-models"),
    CLAUDE_DEV.format("getting-the-most-out-of-opus-5-5"),
    CLAUDE_DEV.format("spending-your-effort"),
    CLAUDE_DEV.format("what-a-task-costs-on-opus-5-5"),
    CLAUDE_DEV.format("building-with-claude-sonnet-5-5"),
    CLAUDE_DEV.format("getting-started-with-claude-code-mods"),
)
DATES_30_41 = dict(zip(ARTICLES_30_41, (
    "2026-11-06", "2026-04-10", "2026-04-30", "2026-05-20", "2026-06-02", "2026-06-03",
    "2026-07-24", "2026-09-22", "2026-09-25", "2026-09-25", "2026-09-28", "2026-10-01",
)))
IDS_30_41 = ("memory", "seeing-like-an-agent", "prompt-caching", "html", "dynamic-workflows",
             "skills", "context-engineering-5", "opus-5-5", "effort", "task-cost", "sonnet-5-5",
             "mods")


def _articles_1_29():
    earlier = _load("tests/skills/test_sync_2026_11_02.py", "sync_2026_11_02_for_11_08")
    later = _load("tests/skills/test_sync_2026_11_04.py", "sync_2026_11_04_for_11_08")
    latest = _load("tests/skills/test_sync_2026_11_05.py", "sync_2026_11_05_for_11_08")
    return (earlier.ARTICLES_1_14 + earlier.ARTICLES_15_23 + later.ARTICLES_24_25
            + latest.ARTICLES_26_29)


def test_there_are_forty_one_distinct_articles():
    assert len(set(_articles_1_29())) == 29
    assert len(set(_articles_1_29() + ARTICLES_30_41)) == 41


def test_the_new_urls_are_written_as_their_canonicals():
    """claude.dev canonicals keep their trailing slash; #30 has none (CONTRACTS §20.10)."""
    assert not ARTICLE_30.endswith("/")
    assert all(u.endswith("/") for u in ARTICLES_30_41[1:])


def test_third_party_notices_lists_all_forty_one():  # awaits lane B
    notices = read("THIRD_PARTY_NOTICES.md")
    missing = [u for u in _articles_1_29() + ARTICLES_30_41 if u not in notices]
    assert missing == []
    hygiene = _load("tests/test_plugin_hygiene.py", "plugin_hygiene_2026_11_08")
    distinct = {m.group(0).rstrip(".,;:") for m in hygiene.ARTICLE_URL.finditer(notices)}
    assert len(distinct & set(_articles_1_29() + ARTICLES_30_41)) == 41


@pytest.mark.parametrize("url", ARTICLES_30_41, ids=IDS_30_41)
def test_each_new_article_is_cited_by_at_least_one_skill_file(url):  # awaits lanes B/C
    assert any(url in p.read_text(encoding="utf-8") for p in skill_docs()), url


@pytest.mark.parametrize("url", ARTICLES_30_41, ids=IDS_30_41)
def test_each_new_article_citation_is_followed_by_a_dated_parenthetical(url):  # awaits lanes B/C
    """Cited as `<URL> ("og:title", YYYY-MM-DD, what for)` (CONTRACTS §16.8) at least
    once, and every file that names the URL carries its date."""
    following = re.compile(re.escape(url) + r">?\)?\s*\(\s*\"[^\"]+\",\s*" + DATES_30_41[url])
    citing = [p for p in skill_docs() if url in p.read_text(encoding="utf-8")]
    assert citing, url
    assert any(following.search(p.read_text(encoding="utf-8")) for p in citing), \
        f"{url} never followed by (\"title\", {DATES_30_41[url]}, ...)"
    undated = [str(p.relative_to(PLUGIN_ROOT)) for p in citing
               if DATES_30_41[url] not in p.read_text(encoding="utf-8")]
    assert undated == [], f"{url} without {DATES_30_41[url]} in {undated}"


def test_the_hygiene_pattern_matches_the_new_hosts():
    hygiene = _load("tests/test_plugin_hygiene.py", "plugin_hygiene_2026_11_08_b")
    for url in ARTICLES_30_41:
        assert hygiene.ARTICLE_URL.search(url).group(0) == url, url


# -- 5. memory-design.md -------------------------------------------------------------------

MEMORY = "skills/agent-design/references/memory-design.md"


def test_the_memory_reference_exists_within_the_size_limits():  # awaits lane C
    lines = read(MEMORY).splitlines()
    assert 25 <= len(lines) <= 250, len(lines)


def test_the_memory_reference_cites_article_30():  # awaits lane C
    assert ARTICLE_30 in read(MEMORY)


def test_the_memory_reference_is_linked_from_agent_design():  # awaits lane C
    assert "references/memory-design.md" in read("skills/agent-design/SKILL.md")


def test_the_memory_reference_is_linked_from_the_router_map():  # awaits lane B
    assert "memory-design.md" in read("skills/agent-sdk/references/capability-map.md")


# -- 6. stale wording is gone ------------------------------------------------------------------

def test_no_skill_file_says_the_hooks_page_lacks_the_monitor_rule():  # awaits lane B
    """The SDK hooks page carries the Monitor rule since 2026-11-06 (CONTRACTS §20.4)."""
    pattern = re.compile(r"(?:doesn't|does not|don't|do not) (?:yet )?carry the monitor rule")
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in sorted(SKILLS.rglob("*.md"))
                 if pattern.search(flat(p.read_text(encoding="utf-8")))]
    assert offenders == []


def test_no_skill_file_quotes_the_old_glob_heading():  # awaits lane B
    """The permissions heading is now "`Write(path)`, `Glob(path)`, and `Grep(path)`
    rules don't match" (CONTRACTS §20.5)."""
    offenders = [str(p.relative_to(PLUGIN_ROOT)) for p in sorted(SKILLS.rglob("*.md"))
                 if "`glob(path)` rules never match" in flat(p.read_text(encoding="utf-8"))]
    assert offenders == []


AUTO_MEMORY = re.compile(r"auto[- ]memory")
NOT_SDK = re.compile(r"not an (?:agent )?sdk feature")


def test_the_auto_memory_scanner_reads_one_paragraph_at_a_time():
    sample = ("Claude Code's auto memory is not an SDK feature.\n\n"
              "The Workflow tool is not an SDK feature.\n\n"
              "Claude Code's auto memory, which an SDK session inherits unless you turn it off.")
    hits = [p for p in _paragraphs(sample) if AUTO_MEMORY.search(flat(p)) and NOT_SDK.search(flat(p))]
    assert hits == ["Claude Code's auto memory is not an SDK feature."]


def test_no_skill_file_says_auto_memory_is_not_an_sdk_feature():  # awaits lanes B/C
    """Auto memory loads in Agent SDK sessions by default (CONTRACTS §20.9)."""
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {flat(par)[:120]}"
                 for p in sorted(SKILLS.rglob("*.md"))
                 for par in _paragraphs(p.read_text(encoding="utf-8"))
                 if AUTO_MEMORY.search(flat(par)) and NOT_SDK.search(flat(par))]
    assert offenders == []


# -- lane needles (appended by the orchestrator from lanes B and C) ----------------------------
# Verbatim substrings the lanes report after editing, lowercased and whitespace-flattened.
# (file, needles that must appear) / (file, needles that must be gone).

LANE_PRESENT: tuple[tuple[str, tuple[str, ...]], ...] = (  # awaits lane B
    # lane C (reported 2026-11-08)
    ("skills/agent-design/references/memory-design.md",
     ("an agent sdk session inherits claude code's auto memory by default, regardless of "
      "`setting_sources`, until `claude_code_disable_auto_memory=1` is set in `env`",
      "memory note is a prediction about what a future session will need")),
    ("skills/agent-design/references/long-running-harness.md", ("a progress file is not a memory note.",)),
    ("skills/agent-design/references/context-engineering.md",
     ("the description is a trigger, not a summary",
      "that is claude code's prompt, not a change to the sdk's `claude_code` preset")),
    ("skills/agent-design/references/tool-design.md",
     ("design from the model's seat.", "argues that html gets read where long markdown does not")),
    ("skills/agent-design/references/subagent-decisions.md",
     ("so treat it as claude code's, not an sdk api",)),
    ("skills/agent-design/references/agent-loop.md",
     ("keep the task list in a file, which survives compaction",)),
    ("skills/eval-analyze/references/reliability.md", ("hold `effort` fixed.",)),
    ("skills/eval-analyze/references/efficiency.md",
     ("cache-read share = cache_read_input_tokens / (input_tokens + cache_creation_input_tokens "
      "+ cache_read_input_tokens)",)),
    ("skills/eval-create/references/memory-and-multiturn.md",
     ("keep the memory folder inside the run's working directory.",)),
    ("skills/agent-design/SKILL.md", ("memory across sessions.", "references/memory-design.md")),
    # lane B (reported 2026-11-08)
    ("skills/agent-harness/references/hooks-catalog.md",
     ("a `bash` matcher also runs for monitor commands, and the sdk hooks page now says so (2026-11-06)",
      "to allow or rewrite a monitor call, use a matcher that includes monitor (`bash|monitor`, `.*`, or none)",
      "## mods: hooks shipped inside a plugin", "it's a safety net, not a permission system")),
    ("skills/agent-harness/references/permission-model.md",
     ("\"`write(path)`, `glob(path)`, and `grep(path)` rules don't match\"",
      # the settings page documented the key on 2026-11-10; the needle follows the current wording
      "`permissions.denyinsteadofprompting` (claude code 2.1.319+; on the settings page since 2026-11-10")),
    ("skills/agent-harness/references/context-and-settings.md",
     ("the python sdk doesn't expose an equivalent method; send `/reload-plugins` as a prompt in the session instead",
      "write the description for when to trigger the skill, and grow a gotchas section from observed failures")),
    ("skills/agent-harness/references/subagent-design.md",
     ("a harness written per task.", "the workflow tool is claude code's, not an sdk api")),
    ("skills/agent-sdk/references/environment.md",
     ("2.1.319 sends 15 `capabilities`, adding `mcp_call_check_permissions_v1` (undocumented; recorded, never required)",)),
    ("skills/agent-deploy/references/cost-controls.md",
     ("keep the cache prefix stable.", "higher effort mostly buys verification and edge-case testing",
      "price the task, not the token.")),
    ("skills/agent-review/references/model-policy.md",
     ("check a subagent's evidence before accepting its report", "sonnet 5.5 or opus 5.5.")),
)

LANE_ABSENT: tuple[tuple[str, tuple[str, ...]], ...] = (  # lanes B/C, reported 2026-11-08
    ("skills/agent-harness/references/hooks-catalog.md",
     ("the hooks page read 2026-11-04 doesn't carry the monitor rule",)),
    ("skills/agent-harness/references/permission-model.md",
     ("`write(path)`, `notebookedit(path)`, and `glob(path)` rules never match",)),
    ("skills/agent-harness/references/context-and-settings.md",
     ("memory files (`claude.md`, auto memory) loaded through `setting_sources`",)),
    ("skills/agent-review/references/options-reference.md",
     ("the python docs page still shows the old `{file, network}` shape",)),
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
