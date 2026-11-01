"""What the 2026-11-02 sync changed in the references, README, notices and pins.

Tests for the fifth upstream sync (claude-agent-sdk 0.2.176 with its bundled CLI
2.1.316; docs and changelog read at Claude Code 2.1.316) and the nine Anthropic
articles (15-23) folded in with release 0.2.1. Written from the plan
(`.claude/plans/write-detailed-plan-on-quiet-ladybug.md` §2a-§2c),
`.dev/UPSTREAM-DELTA-2026-11-02.md` and `.dev/CONTRACTS.md` §17, against what
lanes B and C were asked to write. Lane A wrote this file before lanes B and C
finished: every assertion marked ``# awaits lane B`` / ``# awaits lane C`` reads a
file another lane owns. The needle tuples (``PRESENT``, ``ABSENT``, ``REREAD``)
are plain data so the lanes' exact wording can be appended without touching the
test functions.

1. **Pins and version**: 0.2.176 / 2.1.316 / docs 2.1.316, release 0.2.1, the
   runner-stale rubric names it, `on_failure` stays out of shipped files.
2. **Every reference re-read in this sync carries the dated note.**
3. **2.1.314 / 2.1.316 and docs facts land where they belong**: the write block,
   "Recently blocked", `CLAUDE_CODE_SUBAGENT_EFFORT`, the 10,000-character
   `PreCompact` cut, Bash hooks on Monitor commands, the Opus 4.8 fast-mode dates,
   the Ultra plan, `claude -p` exit 1 on a startup failure.
4. **The 23 Anthropic articles** are listed in `THIRD_PARTY_NOTICES.md`, and each
   of the nine new ones is cited by at least one skill file.
5. **The mirrored-lean persona pattern** (article #16) exists in eval-simulation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"

NEW_NOTE = "re-read 2026-11-02 against claude-agent-sdk 0.2.176 / claude code 2.1.316 docs"


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


def skill_files():
    return [p for p in SKILLS.rglob("*") if p.is_file() and p.suffix in (".md", ".py")]


def skill_docs():
    """The files that cite articles: every reference and every SKILL.md."""
    return sorted(SKILLS.rglob("references/*.md")) + sorted(SKILLS.glob("*/SKILL.md"))


# -- 1. pins, version, on_failure -------------------------------------------------

def test_the_pins_moved_to_0_2_176_and_2_1_316():
    import agent_sdk_skills as plugin
    assert (plugin.SDK_TARGET, plugin.CLI_BUNDLED_WITH_TARGET) == ("0.2.176", "2.1.316")
    assert plugin.DOCS_READ_AT_CLI == "2.1.316"
    assert plugin.SDK_MIN_SUPPORTED == "0.2.140", "the minimum does not move with the pin"


def test_the_release_is_0_2_1_everywhere_lane_a_owns():
    import json

    import agent_sdk_skills as plugin
    assert plugin.__version__ == plugin.RUNNER_VERSION == "0.2.1"
    assert read("runner/agent_sdk_evals/VERSION").strip() == "0.2.1"
    assert json.loads(read(".claude-plugin/plugin.json"))["version"] == "0.2.1"
    assert 'version = "0.2.1"' in read("pyproject.toml")
    assert "## 0.2.1 — 2026-11-02" in read("runner/agent_sdk_evals/CHANGELOG.md")


def test_the_changelog_states_the_startup_failure_claim_as_a_claim():
    text = flat(read("runner/agent_sdk_evals/CHANGELOG.md").split("## 0.2.0", 1)[0])
    assert "2.1.314" in text and "not reproduced" in text
    assert "processerror" in text and "not_evaluated" in text


def test_the_runner_stale_rubric_names_0_2_1():  # awaits lane B
    assert "0.2.1" in read("plugin-evals/runner-stale/graders/criteria.md")


#: `HookMatcher.on_failure` is on upstream `main` only and 2.1.316 refuses it
#: (CONTRACTS §17.2), so no shipped skill file may document the SDK field. The
#: settings-file `onFailure` (Claude Code 2.1.295+) is a different, shipped thing.
ON_FAILURE_SDK_NEEDLES = ("on_failure=", "hookmatcher.on_failure", "hook_on_failure_supported")


def test_no_skill_file_documents_the_unreleased_sdk_on_failure():  # awaits lane B
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {n}" for p in skill_files()
                 for n in ON_FAILURE_SDK_NEEDLES if n in flat(p.read_text(encoding="utf-8"))]
    assert offenders == []


# -- 2. the dated re-read note ------------------------------------------------------

#: References lanes B and C re-read in this sync (plan §2b, §2c).
REREAD = (
    "agent-harness/references/hooks-catalog.md",
    "agent-harness/references/permission-model.md",
    "agent-harness/references/subagent-design.md",
    "agent-harness/references/context-and-settings.md",
    "agent-harness/references/mcp-patterns.md",
    "agent-review/references/model-policy.md",
    "agent-review/references/review-checklist.md",
    "agent-review/references/options-reference.md",
    "agent-deploy/references/secure-deployment.md",
    "agent-deploy/references/cost-controls.md",
    "agent-deploy/references/hosting-options.md",
    "agent-deploy/references/observability-otel.md",
    "agent-debug/references/failure-shapes.md",
    "agent-debug/references/evidence.md",
    "agent-debug/references/triage.md",
    "agent-create/references/eval-ready-architecture.md",
    "eval-create/references/case-taxonomy.md",
    "eval-criteria/references/judge-options.md",
    "eval-criteria/references/rubric-authoring.md",
    "eval-run/references/running-in-ci.md",
    "eval-run/references/cost-estimation.md",
    "eval-analyze/references/reliability.md",
    "eval-analyze/references/diagnosis.md",
    "agent-design/references/tool-design.md",
    "agent-design/references/subagent-decisions.md",
    "agent-design/references/long-running-harness.md",
    "agent-design/references/agent-loop.md",
    "agent-design/references/context-engineering.md",
    "agent-sdk/references/glossary.md",
    "agent-sdk/references/environment.md",
    "agent-sdk/references/capability-map.md",
    "eval-simulation/references/personas.md",          # lane C
    "eval-simulation/references/user-simulation.md",   # lane C
)


@pytest.mark.parametrize("name", REREAD)
def test_every_reference_re_read_in_this_sync_carries_the_new_note(name):  # awaits lanes B/C
    assert NEW_NOTE in flat((SKILLS / name).read_text(encoding="utf-8"))


# -- 3. lane B / lane C facts, checked as needles ------------------------------------
# Needles are lower-cased and matched against the whitespace-flattened file. These
# are the plan's facts in the plan's words; the orchestrator appends the lanes'
# exact phrases to these tuples once lanes B and C report.

PRESENT = (  # awaits lanes B/C
    # write block (2.1.314; settings-reference, permissions, permission-modes)
    ("skills/agent-harness/references/permission-model.md",
     ("blockwritesoutsideworkingdirectories", "recently blocked", "bypasspermissions",
      "enterworktree", "/add-dir")),
    ("skills/agent-deploy/references/secure-deployment.md",
     ("blockwritesoutsideworkingdirectories",)),
    ("skills/agent-harness/references/context-and-settings.md",
     ("claude_code_subagent_effort", "blockwritesoutsideworkingdirectories")),
    # subagent effort (2.1.316, changelog only)
    ("skills/agent-harness/references/subagent-design.md",
     ("claude_code_subagent_effort", "2.1.316")),
    # PreCompact cut and Monitor hooks (2.1.314)
    ("skills/agent-harness/references/hooks-catalog.md",
     ("10,000 characters", "precompact", "monitor", "2.1.314")),
    # fast mode for Opus 4.8 (2.1.316), Ultra plan (docs 2026-11-02)
    ("skills/agent-review/references/model-policy.md",
     ("opus 4.8", "2026-10-30", "2026-11-30", "ultra", "as of 2026-11-02")),
    ("skills/agent-deploy/references/cost-controls.md", ("ultra",)),
    # `claude -p` startup failure exits 1 (2.1.314 changelog)
    ("skills/agent-debug/references/evidence.md", ("2.1.314", "exit")),
    ("skills/eval-run/references/running-in-ci.md", ("2.1.314",)),
    ("skills/agent-sdk/references/environment.md", ("2.1.316",)),
    # article #19: harness regression shape
    ("skills/agent-debug/references/failure-shapes.md", ("harness regression",)),
    # README and notices
    ("README.md", ("documentation read at claude code 2.1.316", "fourteen skills")),
    ("THIRD_PARTY_NOTICES.md",
     ("e0da9b95223d3d112bfbccad41d2a32bad923bb5", "1a0f9a9d18e1272d3fbaa817d192b6b057bba623",
      "## cited anthropic articles")),
    # article #16: mirrored-lean persona pair (lane C)
    ("skills/eval-simulation/references/personas.md",
     ("a mirrored pair that measures deferral",)),
    ("skills/eval-simulation/scripts/gen_persona.py", ("--lean",)),
)

ABSENT = (  # awaits lanes B/C
    ("skills/agent-harness/references/hooks-catalog.md", ("0.2.174 has all of this",)),
    ("README.md", ("documentation read at claude code 2.1.312", "14 published anthropic articles")),
    ("skills/agent-review/references/model-policy.md", ("as of 2026-10-29",)),
    ("plugin-evals/runner-stale/graders/criteria.md", ("0.2.0",)),
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


#: Wording no skill file or the README may keep anywhere (docs 2026-11-02).
ABSENT_EVERYWHERE = (
    "recently denied",          # the auto-mode tab is "Recently blocked" (CONTRACTS §17.4)
    "read at 2.1.312",          # docs are read at 2.1.316 now
    "read at claude code 2.1.312",
)


def test_no_skill_file_keeps_this_syncs_stale_wording():  # awaits lanes B/C
    sources = skill_files() + [PLUGIN_ROOT / "README.md"]
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {n}" for p in sources
                 for n in ABSENT_EVERYWHERE if n in flat(p.read_text(encoding="utf-8"))]
    assert offenders == []


# -- 4. the 23 articles -----------------------------------------------------------------

#: Articles 1-14, cited since 2026-10-29 (`.dev/articles/INDEX.md`).
ARTICLES_1_14 = (
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

#: Articles 15-23, canonical URLs fetched 2026-11-02 (HTTP 200, no redirect).
ARTICLES_15_23 = (
    "https://claude.com/resources/articles/message-threads",
    "https://www.anthropic.com/research/agents-judgment-calls",
    "https://www.anthropic.com/research/investigating-unintended-model-actions",
    "https://www.anthropic.com/research/building-c-compiler",
    "https://www.anthropic.com/research/april-23-postmortem",
    "https://www.anthropic.com/research/advanced-tool-use",
    "https://www.anthropic.com/research/formal-verification",
    "https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation",
    "https://www.anthropic.com/research/redesigning-source-control",
)


def test_there_are_twenty_three_distinct_articles():
    assert len(set(ARTICLES_1_14 + ARTICLES_15_23)) == 23


@pytest.mark.parametrize("url", ARTICLES_1_14 + ARTICLES_15_23,
                         ids=lambda u: u.rsplit("/", 1)[1][:40])
def test_third_party_notices_lists_each_article(url):  # awaits lane B for 15-23
    assert url in read("THIRD_PARTY_NOTICES.md")


@pytest.mark.parametrize("url", ARTICLES_15_23, ids=lambda u: u.rsplit("/", 1)[1][:40])
def test_each_new_article_is_cited_by_at_least_one_skill_file(url):  # awaits lanes B/C
    assert any(url in p.read_text(encoding="utf-8") for p in skill_docs()), url


def test_message_threads_are_never_claimed_for_the_sdk():  # awaits lane B
    """Article #15 is a Messages API fact; the SDK neither uses nor exposes threads
    as far as any doc says (CONTRACTS §17.8), so the mechanics cite the platform page."""
    citing = [p for p in skill_docs()
              if "https://claude.com/resources/articles/message-threads" in p.read_text(encoding="utf-8")]
    assert citing, "article #15 is cited somewhere"
    assert any("platform.claude.com/docs/en/build-with-claude/message-threads"
               in p.read_text(encoding="utf-8") for p in citing)


def test_the_hygiene_article_pattern_dates_news_urls():
    """`anthropic.com/news/` joined `ARTICLE_URL` so #22's citation is date-checked."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hygiene", PLUGIN_ROOT / "tests" / "test_plugin_hygiene.py")
    hygiene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hygiene)
    assert hygiene.ARTICLE_URL.search(ARTICLES_15_23[7])
    assert not hygiene.ARTICLE_URL.search("https://platform.claude.com/docs/en/build-with-claude/message-threads")


# -- 6. lane B and lane C needles (appended by the orchestrator, 2026-11-02) ------------
# Verbatim substrings the lanes reported after editing, lowercased and whitespace-flattened.

LANE_PRESENT = (
    ("skills/agent-harness/references/hooks-catalog.md",
     ("output is cut at 10,000 characters (2.1.314)",
      "also run on the monitor tool's shell commands (2.1.314)",
      "they can block or ask, not approve or rewrite them",
      "`monitor(tail *)`",
      "the pinned 0.2.176 (bundled cli 2.1.316) has all of this")),
    ("skills/agent-harness/references/permission-model.md",
     ("in every permission mode, including `bypasspermissions`",
      "`enterworktree`/`exitworktree` are removed",
      "a cloud session might not apply it",
      "no longer supplies auto-mode rules or saved permission consents",
      "entered by `claude -p --resume` or `--continue`")),
    ("skills/agent-harness/references/subagent-design.md",
     ("the env-vars page read 2026-11-02 does not list it yet",
      "no longer keeps each subagent's tool results until the turn ends",
      "near-perfect oracle",
      "https://www.anthropic.com/research/building-c-compiler")),
    ("skills/agent-harness/references/context-and-settings.md",
     ("message threads are a messages api fact, not an sdk option",
      "expires 5 minutes after its last request",
      "latency lever, not a cost lever",
      "https://platform.claude.com/docs/en/build-with-claude/message-threads",
      "auto-memory `.md` files stay writable")),
    ("skills/agent-harness/references/mcp-patterns.md",
     ("https://www.anthropic.com/research/advanced-tool-use",
      '"introducing advanced tool use for claude", 2025-11-24',
      "programmatic tool calling",
      "no `claudeagentoptions` field in 0.2.176",
      "headershelper")),
    ("skills/agent-review/references/model-policy.md",
     ("fast mode on opus 4.8 is deprecated",
      "removed on **2026-11-30**",
      "does **not** fall back to standard opus 4.8",
      "invalid effort level",
      "pro, max, ultra, team, enterprise")),
    ("skills/agent-review/references/review-checklist.md",
     ("https://www.anthropic.com/research/redesigning-source-control",)),
    ("skills/agent-review/references/options-reference.md",
     ("ask_user_question_unanswered_v1", "ultrathink_available", "cli 2.1.316 sent 14")),
    ("skills/agent-review/references/load-check.md",
     ("the **0.2.176** wheel bundles **2.1.316**",)),
    ("skills/agent-deploy/references/secure-deployment.md",
     ("https://www.anthropic.com/research/investigating-unintended-model-actions",
      "its own policy, not an sdk default")),
    ("skills/agent-deploy/references/cost-controls.md",
     ("message threads cut latency, not cost", "pro, max, ultra, team or enterprise")),
    ("skills/agent-deploy/references/hosting-options.md",
     ("global lock", "shell commands are no longer left running")),
    ("skills/agent-deploy/references/observability-otel.md",
     ("says why auto mode stopped a turn",)),
    ("skills/agent-debug/references/failure-shapes.md",
     ("## harness regression",
      "https://www.anthropic.com/research/april-23-postmortem",
      "submitting a real form", "url shortener")),
    ("skills/agent-debug/references/evidence.md",
     ("exit 0 with no output when startup failed and now prints the error and exits 1",
      "exited 1 with the error on stderr on both 2.1.310 and 2.1.316",
      "`exit_code=1` on 0.2.174 and 0.2.176")),
    ("skills/agent-debug/references/triage.md", ("harness regression",)),
    ("skills/eval-run/references/running-in-ci.md",
     ("now prints the error and exits 1", "on both 2.1.310 and 2.1.316",
      "https://www.anthropic.com/research/april-23-postmortem")),
    ("skills/eval-run/references/cost-estimation.md",
     ("three independent single-agent attempts at a 5m-token budget",)),
    ("skills/agent-create/references/eval-ready-architecture.md",
     ("https://www.anthropic.com/research/agents-judgment-calls",)),
    ("skills/agent-design/references/tool-design.md",
     ("tool search is **on by default**", "dsg006 stays at 30")),
    ("skills/agent-design/references/subagent-decisions.md",
     ("current_tasks/", "disposable container")),
    ("skills/agent-design/references/agent-loop.md",
     ("ask for the user's own view before recommending", "not a base rate",
      "https://www.anthropic.com/research/formal-verification")),
    ("skills/agent-design/references/context-engineering.md",
     ("https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation",)),
    ("skills/eval-create/references/case-taxonomy.md",
     ("## live-web cases are a separate suite", "scope statement")),
    ("skills/eval-criteria/references/judge-options.md",
     ("gen_persona.py --lean", "a mirrored pair that measures deferral")),
    ("skills/eval-criteria/references/rubric-authoring.md",
     ("gen_persona.py --lean", "a mirrored pair that measures deferral")),
    ("skills/agent-sdk/references/glossary.md",
     ("**message thread**", "**tool search tool**", "**mirrored lean (deferral)**",
      "**agentic ai foundation (aaif)**")),
    ("skills/agent-sdk/references/environment.md",
     ("`claude-agent-sdk` **0.2.176** with its bundled claude code **2.1.316**",
      "pro, max, ultra, team, or enterprise", "ask_user_question_unanswered_v1")),
    ("skills/agent-sdk/SKILL.md", ("0.2.176 with bundled claude code 2.1.316",)),
    ("README.md", ("23 published anthropic articles",)),
    ("THIRD_PARTY_NOTICES.md",
     ("articles 1–14 were read on 2026-10-29 and articles 15–23 on 2026-11-02",)),
    ("plugin-evals/README.md", ("the local `claude` is **2.1.316**",)),
    ("plugin-evals/runner-stale/graders/criteria.md", ("0.2.1",)),
    # lane C
    ("skills/eval-simulation/references/personas.md",
     ("## a mirrored pair that measures deferral",
      "https://www.anthropic.com/research/agents-judgment-calls", "not a base rate",
      "2026-11-02 against claude-agent-sdk 0.2.176 / claude code 2.1.316")),
    ("skills/eval-simulation/references/user-simulation.md",
     ("**reading a mirrored pair.**",
      "2026-11-02 against claude-agent-sdk 0.2.176 / claude code 2.1.316")),
    ("skills/eval-simulation/SKILL.md",
     ('--lean "<stance>"', '"a mirrored pair that measures deferral"')),
    ("skills/eval-simulation/scripts/gen_persona.py",
     ("state in your first message that you lean toward",)),
)

LANE_ABSENT = (
    ("skills/agent-sdk/references/environment.md",
     ("pins unchanged: no sdk release since 0.2.174",)),
    ("skills/agent-sdk/SKILL.md", ("0.2.174 with bundled claude code 2.1.310",)),
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


def test_the_impatient_persona_rubrics_are_statements_that_must_hold():
    """`simulate.check_rubrics` passes a rubric when the statement holds for every
    user turn, so a rubric phrased as the violation ("…is longer than two
    sentences") fails a well-behaved simulator. Both fixtures were re-phrased on
    2026-11-02; keep them that way."""
    import json
    for relative in ("tests/fixtures/personas/impatient.json",
                     "tests/fixtures/agents/good/evals/personas/impatient.json"):
        rubrics = json.loads(read(relative))["violation_rubrics"]
        assert len(rubrics) == 4
        assert not any("is longer than" in r or "adopts a polite" in r for r in rubrics), relative
        assert all(r.startswith(("Every ", "Once ")) for r in rubrics), relative
