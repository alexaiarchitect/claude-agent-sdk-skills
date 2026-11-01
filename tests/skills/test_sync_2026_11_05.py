"""What the 2026-11-05 sync changed in the version, citations, references and notices.

Tests for the seventh upstream sync: a docs-only re-read. No SDK or Claude Code
release since 2026-11-04, so the pins stay claude-agent-sdk 0.2.178 with its
bundled CLI 2.1.318 and the docs are re-read at Claude Code 2.1.318 (13 pages
with lastmod 2026-11-04, among them the rewrite of "How permissions are
evaluated"); four claude.dev blog posts (articles 26-29) are folded in as dated
citations with release 0.2.3. Written from the plan
(`.claude/plans/write-detailed-plan-on-quiet-ladybug.md` §2a-§2b),
`.dev/UPSTREAM-DELTA-2026-11-05.md` and `.dev/CONTRACTS.md` §19. Lane A wrote this
file before lane B finished: every assertion marked ``# awaits lane B`` reads a
file lane B owns. The needle tuples (``REREAD``, ``PRESENT``, ``ABSENT``) are
plain data so lane B's exact wording can be appended without touching the test
functions.

1. **Pins and version**: 0.2.178 / 2.1.318 / docs 2.1.318 unchanged, minimum
   0.2.140, release 0.2.3 in every carrier, the runner-stale rubric names it.
2. **The hygiene pattern knows claude.dev**, so the dated-citation check covers
   the new host.
3. **The 29 Anthropic articles** are listed in `THIRD_PARTY_NOTICES.md`, and each
   of the four new ones is cited by a skill file with a dated parenthetical.
4. **The permission-evaluation rewrite** (CONTRACTS §19.2): no reference says
   `can_use_tool` "never fires" / "is never called" except the `dontAsk` row, and
   none says a scoped rule falls through "to the callback".
5. **Every reference re-read in this sync carries the dated note**; this sync's
   facts land where the plan puts them.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"

NEW_NOTE = "re-read 2026-11-05 against claude-agent-sdk 0.2.178 / claude code 2.1.318 docs"


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

def test_the_pins_did_not_move():
    # No SDK or Claude Code release between 2026-11-04 and 2026-11-05.
    import agent_sdk_skills as plugin
    assert (plugin.SDK_TARGET, plugin.CLI_BUNDLED_WITH_TARGET) == ("0.2.178", "2.1.318")
    assert plugin.DOCS_READ_AT_CLI == "2.1.318", "the docs moved without a CLI release"
    assert plugin.SDK_MIN_SUPPORTED == "0.2.140", "the minimum does not move with the pin"
    runner = read("runner/agent_sdk_evals/__init__.py")
    assert 'DOCS_READ_AT_CLI = "2.1.318"' in runner


def test_the_docs_re_read_is_dated_next_to_the_constant():
    note = "docs re-read 2026-11-05 (lastmod 2026-11-04), no cli release"
    assert note in flat(read("lib/agent_sdk_skills/__init__.py"))
    assert note in flat(read("runner/agent_sdk_evals/__init__.py"))


def test_the_release_is_0_2_3_everywhere_lane_a_owns():
    import agent_sdk_skills as plugin
    assert plugin.__version__ == plugin.RUNNER_VERSION == "0.2.3"
    assert read("runner/agent_sdk_evals/VERSION").strip() == "0.2.3"
    assert json.loads(read(".claude-plugin/plugin.json"))["version"] == "0.2.3"
    assert 'version = "0.2.3"' in read("pyproject.toml")
    assert read("tests/fixtures/agents/ci_ready/evals/runner/agent_sdk_evals/VERSION").strip() == "0.2.3"


def test_the_fixtures_carry_0_2_3():
    for aggregate in (PLUGIN_ROOT / "tests" / "fixtures" / "results").glob("*/aggregate.json"):
        payload = json.loads(aggregate.read_text(encoding="utf-8"))
        assert payload["runner_version"] == "0.2.3", aggregate
    for config in (PLUGIN_ROOT / "tests").rglob("eval_config.json"):
        if "stale_runner" in config.parts:
            continue                       # stale on purpose (0.0.1)
        assert json.loads(config.read_text(encoding="utf-8"))["runner_version"] == "0.2.3", config


def test_the_changelog_records_a_docs_only_release():
    text = read("runner/agent_sdk_evals/CHANGELOG.md")
    assert "## 0.2.3 — 2026-11-05" in text
    section = flat(text.split("## 0.2.3 — 2026-11-05", 1)[1].split("## 0.2.2", 1)[0])
    for needle in ("docs-only", "lastmod 2026-11-04", "types.py` is unchanged",
                   "nothing in the runner's behaviour changed", "what a 0.2.2 copy should know",
                   "permission_denials", "without calling `can_use_tool`", "`pretooluse` hook",
                   "fall through to the permission mode", "~/.claude.json", "exits 1",
                   "organization settings"):
        assert needle in section, needle


def test_the_runner_stale_rubric_names_0_2_3():  # awaits lane B
    assert "0.2.3" in read("plugin-evals/runner-stale/graders/criteria.md")


# -- 2. the hygiene pattern learns claude.dev --------------------------------------

def test_the_hygiene_article_pattern_matches_claude_dev():
    hygiene = _load("tests/test_plugin_hygiene.py", "plugin_hygiene_2026_11_05")
    pattern = hygiene.ARTICLE_URL
    assert pattern.search(ARTICLE_26).group(0) == ARTICLE_26
    for url in ("https://www.anthropic.com/research/building-effective-agents",
                "https://www.anthropic.com/news/donating-agent-skills",
                "https://claude.com/blog/x"):
        assert pattern.search(url), url
    assert not pattern.search("https://code.claude.com/docs/en/agent-sdk/permissions")


def test_the_hygiene_check_flags_an_undated_claude_dev_citation():
    """The dated-citation check runs over `Sources:` footers with `ARTICLE_URL`;
    a claude.dev URL must now be caught without a date and pass with one."""
    hygiene = _load("tests/test_plugin_hygiene.py", "plugin_hygiene_2026_11_05_b")
    undated = f"Sources: {ARTICLE_27} (\"How the Claude Code team does code review\")."
    dated = f"Sources: {ARTICLE_27} (\"How the Claude Code team does code review\", 2026-10-15, reviewers)."
    for footer, expect in ((undated, False), (dated, True)):
        match = hygiene.ARTICLE_URL.search(footer)
        assert match and match.group(0) == ARTICLE_27
        segment = footer[match.end():]
        assert bool(hygiene.DATED_PARENTHETICAL.search(segment)) is expect, footer


# -- 3. the 29 articles -------------------------------------------------------------

ARTICLE_26 = "https://claude.dev/blog/automating-eval-design-and-hillclimbing/"
ARTICLE_27 = "https://claude.dev/blog/solving-code-review-at-anthropic/"
ARTICLE_28 = "https://claude.dev/blog/building-effective-agent-automations/"
ARTICLE_29 = "https://claude.dev/blog/claude-code-in-the-cloud/"
ARTICLES_26_29 = (ARTICLE_26, ARTICLE_27, ARTICLE_28, ARTICLE_29)
DATES_26_29 = {ARTICLE_26: "2026-09-28", ARTICLE_27: "2026-10-15",
               ARTICLE_28: "2026-10-08", ARTICLE_29: "2026-10-06"}


def _articles_1_25():
    earlier = _load("tests/skills/test_sync_2026_11_02.py", "sync_2026_11_02_for_11_05")
    later = _load("tests/skills/test_sync_2026_11_04.py", "sync_2026_11_04_for_11_05")
    return earlier.ARTICLES_1_14 + earlier.ARTICLES_15_23 + later.ARTICLES_24_25


def test_there_are_twenty_nine_distinct_articles():
    assert len(set(_articles_1_25() + ARTICLES_26_29)) == 29


def test_third_party_notices_lists_all_twenty_nine():  # awaits lane B
    notices = read("THIRD_PARTY_NOTICES.md")
    missing = [u for u in _articles_1_25() + ARTICLES_26_29 if u not in notices]
    assert missing == []


@pytest.mark.parametrize("url", ARTICLES_26_29, ids=("evals-hillclimb", "code-review",
                                                     "automations", "cloud-sessions"))
def test_each_new_article_is_cited_by_at_least_one_skill_file(url):  # awaits lane B
    assert any(url in p.read_text(encoding="utf-8") for p in skill_docs()), url


@pytest.mark.parametrize("url", ARTICLES_26_29, ids=("evals-hillclimb", "code-review",
                                                     "automations", "cloud-sessions"))
def test_each_new_article_citation_is_followed_by_a_dated_parenthetical(url):  # awaits lane B
    """Cited as `<URL> ("og:title", YYYY-MM-DD, what for)` (CONTRACTS §16.8) at least
    once, and every file that names the URL carries its date."""
    following = re.compile(re.escape(url) + r">?\)?\s*\(\s*\"[^\"]+\",\s*" + DATES_26_29[url])
    citing = [p for p in skill_docs() if url in p.read_text(encoding="utf-8")]
    assert citing, url
    assert any(following.search(p.read_text(encoding="utf-8")) for p in citing), \
        f"{url} never followed by (\"title\", {DATES_26_29[url]}, ...)"
    undated = [str(p.relative_to(PLUGIN_ROOT)) for p in citing
               if DATES_26_29[url] not in p.read_text(encoding="utf-8")]
    assert undated == [], f"{url} without {DATES_26_29[url]} in {undated}"


# -- 4. the permission-evaluation rewrite (CONTRACTS §19.2) --------------------------

def _chunks(text: str):
    """Table rows one by one, everything else paragraph by paragraph."""
    for paragraph in re.split(r"\n\s*\n", text):
        prose = []
        for line in paragraph.splitlines():
            if line.lstrip().startswith("|"):
                yield line
            else:
                prose.append(line)
        if prose:
            yield "\n".join(prose)


CALLBACK = r"(?:`?can_use_tool`?|`?canusetool`?)"
NEVER = r"(?:never fires|never fire|is never called|never gets called|never invoked|never runs)"
NEVER_FIRES = re.compile(rf"{CALLBACK}[^.|]{{0,60}}{NEVER}|{NEVER}[^.|]{{0,30}}for auto-approved")
TO_THE_CALLBACK = re.compile(r"fall(?:s|ing)? through to (?:the|your) callback")


def _is_dont_ask_row(chunk: str) -> bool:
    return chunk.lstrip().startswith("|") and "`dontask`" in chunk.lower()


def test_the_scanners_tolerate_only_the_dont_ask_row():
    sample = ("| `dontAsk` | anything that would prompt is **denied**. `can_use_tool` is never called. |\n"
              "| `acceptEdits` | edits run; `can_use_tool` is never called for them |\n\n"
              "A scoped allow rule's other calls fall through to the callback.\n\n"
              "`can_use_tool` runs when the flow resolves to a prompt.")
    hits = [c for c in _chunks(sample) if NEVER_FIRES.search(c.lower()) and not _is_dont_ask_row(c)]
    assert len(hits) == 1 and "acceptEdits" in hits[0]
    assert [c for c in _chunks(sample) if TO_THE_CALLBACK.search(c.lower())] \
        == ["A scoped allow rule's other calls fall through to the callback."]


def test_no_reference_says_can_use_tool_never_fires_outside_the_dont_ask_row():  # awaits lane B
    offenders = []
    for path in sorted(SKILLS.rglob("references/*.md")):
        for chunk in _chunks(path.read_text(encoding="utf-8")):
            if NEVER_FIRES.search(flat(chunk)) and not _is_dont_ask_row(chunk):
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {flat(chunk)[:120]}")
    assert offenders == [], ("say when `can_use_tool` is skipped (allow rule or mode approval; "
                             "a PreToolUse hook still runs), CONTRACTS §19.2")


def test_no_reference_says_a_scoped_rule_falls_through_to_the_callback():  # awaits lane B
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {m.group(0)}"
                 for p in sorted(SKILLS.rglob("references/*.md"))
                 for m in TO_THE_CALLBACK.finditer(flat(p.read_text(encoding="utf-8")))]
    assert offenders == [], "a scoped rule's other calls fall through to the permission mode"


# -- 5. the dated re-read note and this sync's facts ----------------------------------

#: References the plan has lane B re-read in this sync (plan §2b).
REREAD = (  # awaits lane B; the orchestrator appends what lane B reports
    "agent-harness/references/permission-model.md",
    "agent-harness/references/hooks-catalog.md",
    "agent-review/references/options-reference.md",
    "agent-deploy/references/secure-deployment.md",
    "agent-deploy/references/hosting-options.md",
    "eval-criteria/references/judge-options.md",
    "agent-sdk/references/environment.md",
)


@pytest.mark.parametrize("name", REREAD)
def test_every_reference_re_read_in_this_sync_carries_the_new_note(name):  # awaits lane B
    assert NEW_NOTE in flat((SKILLS / name).read_text(encoding="utf-8"))


#: (file, needles that must appear, lower-cased, whitespace-flattened). The plan's
#: facts in the plan's words; the orchestrator appends lane B's exact phrases.
PRESENT = (  # awaits lane B
    ("skills/agent-harness/references/permission-model.md", ("pretooluse", "//path")),
    ("skills/agent-harness/references/hooks-catalog.md", ("--bare",)),
    ("skills/agent-deploy/references/secure-deployment.md", ("--network none",)),
    ("skills/agent-review/references/model-policy.md", ("as of 2026-11-05",)),
    ("README.md", ("29 published anthropic articles", "re-read 2026-11-05")),
    ("THIRD_PARTY_NOTICES.md",
     ("ce8b2629efe8b24048b127b4c79af1e9cbab93d4", "2c65d16c6de16f8f24117d539a712ea706b5dee7",
      "claude.dev")),
)

ABSENT = (  # awaits lane B
    ("README.md", ("25 published anthropic articles",)),
    ("THIRD_PARTY_NOTICES.md",
     ("785d7a06457b3413727f386b9c470083feb23c49", "4c34ec4863dfdc6b0ba3a473bd3408eb38660c22")),
    ("skills/agent-review/references/model-policy.md", ("as of 2026-11-04",)),
)


@pytest.mark.parametrize("relative,needles", PRESENT, ids=[r for r, _ in PRESENT])
def test_this_syncs_facts_are_present(relative, needles):  # awaits lane B
    text = flat(read(relative))
    missing = [n for n in needles if n.lower() not in text]
    assert missing == [], f"{relative}: missing {missing}"


@pytest.mark.parametrize("relative,needles", ABSENT, ids=[r for r, _ in ABSENT])
def test_stale_wording_is_gone(relative, needles):  # awaits lane B
    text = flat(read(relative))
    present = [n for n in needles if n.lower() in text]
    assert present == [], f"{relative}: still says {present}"


# -- lane B needles (appended by the orchestrator, 2026-11-05) ---------------------------
# Verbatim substrings lane B reported after editing, lowercased and whitespace-flattened.

LANE_PRESENT = (
    ("skills/agent-harness/references/permission-model.md",
     ('skips it for "a call that an `allowed_tools` entry or a settings allow rule approves"',
      "which runs for them too", "fall through to the permission mode",
      "writes to a protected path are **not** on the list", "cross-session messaging safeguards",
      "others go to its classifier instead", "`useautomodeduringplan: false`",
      "`tee` and `> file` redirection",
      "a single `/path` is a path inside the session's working directory",
      "2.1.278+ in `-p` and vs code sessions, 2.1.281+ in agent sdk and desktop sessions",
      "a permission gate, not a sandbox", '"claude explores and plans"')),
    ("skills/agent-harness/references/hooks-catalog.md",
     ("bare mode runs no hooks", "a guard that must cover them belongs in a `pretooluse` hook")),
    ("skills/agent-harness/references/subagent-design.md",
     ("then a subagent reviews the diff with fresh context",)),
    ("skills/agent-review/references/review-checklist.md", ("votes it real", "known to be clean")),
    ("skills/agent-review/references/options-reference.md",
     ("skipped for a call an `allowed_tools` entry, a settings allow rule or the mode approves",
      '(docs: "claude explores and plans")')),
    ("skills/agent-deploy/references/secure-deployment.md",
     ("mount its unix socket into the container", "send data to any allowed domain",
      "permissive credentials", "a permission gate, not a sandbox", "runs no hooks at all")),
    ("skills/agent-deploy/references/hosting-options.md",
     ("report a failed read as unreadable", "destination confirms it",
      "pick the narrowest network level that works.",
      "ends** an sdk run with `error_max_budget_usd`",
      "exits with code 1 each time until you repair the file")),
    ("skills/agent-deploy/references/cost-controls.md", ("three to five times a normal run's cost",)),
    ("skills/agent-design/references/long-running-harness.md", ("bookmark per source", "maybe posted")),
    ("skills/eval-criteria/references/judge-options.md", ("it should not be the model you are testing",)),
    ("skills/eval-criteria/references/rubric-authoring.md",
     ("a failing transcript is evidence, not prompt text",)),
    ("skills/eval-analyze/references/reliability.md",
     ("keep a change only when train and held-out both improve",)),
    ("skills/eval-analyze/references/diagnosis.md", ("sort every remaining failure by cause",)),
    ("skills/eval-create/references/case-taxonomy.md",
     ("known to be clean", "held-out (test) set", "the runner has no split field")),
    ("skills/eval-create/references/golden-traces.md", ("past reverts are a second source",)),
    ("skills/agent-sdk/references/glossary.md",
     ("**hillclimbing**", "**held-out (test) set**", "**destination-confirmed completion**")),
    ("skills/agent-sdk/references/environment.md",
     ("re-read 2026-11-05: docs lastmod 2026-11-04, no cli release",)),
    ("THIRD_PARTY_NOTICES.md", ("articles 26–29 on 2026-11-05", "re-read on **2026-11-05**")),
    ("plugin-evals/README.md", ("re-read 2026-11-05 (no cli release): nothing changed",)),
    ("plugin-evals/runner-stale/graders/criteria.md", ("0.2.3",)),
)

LANE_ABSENT = (
    ("skills/agent-harness/references/permission-model.md",
     ("`can_use_tool` is never called",
      "sends file-edit tools to your `canusetool` callback regardless of allow rules",
      "because that mode never prompts", "it fires only when the rules evaluate to",
      "without calling `can_use_tool`")),
    ("skills/agent-harness/references/hooks-catalog.md",
     ("fires **only** when the cli's rules evaluate to",)),
    ("skills/agent-review/references/options-reference.md",
     ('fires only when the rules evaluate to "ask"',)),
    ("skills/agent-harness/SKILL.md", ("where it can never fire",)),
    ("skills/agent-deploy/references/secure-deployment.md",
     ("guards fail closed more often since 2.1.299", "without terminating tls")),
    ("THIRD_PARTY_NOTICES.md", ("re-checked 2026-11-04",)),
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
