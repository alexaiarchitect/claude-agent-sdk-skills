"""What the 0.2.165 sync added to the plugin-side scripts and references.

Lane B's tests for the 2026-10-11 sync. Three things are worth a test rather
than a read-through:

1. **OPT013** — the new warn finding for options that never pass
   `permission_mode`. It is the only finding in this sync whose trigger is an
   *absence*, so a refactor that stops looking at the option would silently
   drop it and nothing else would fail.
2. **The model-policy grades** reaching the findings. `classify_model_id` now
   answers `current` and `deprecated` as well, and a deprecated id has to carry
   its committed retirement date into the message a reader sees — the date is
   the whole point of separating it from `retiring`.
3. **The dated footer** on every reference, so the next sync can tell at a
   glance which pages were re-read and which were not.
4. **`ENV003`** — the info-level note `check_env.py` prints when the installed
   SDK is newer than the pin. It is the one report in the plugin whose whole
   job is to be ignorable, so a regression that promoted it to a blocker would
   be invisible until it broke someone's run.

The linters are run as subprocesses, the way a skill runs them.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agent_sdk_skills import CLI_BUNDLED_WITH_TARGET, SDK_TARGET  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
CHECK_ENV = "skills/agent-sdk/scripts/check_env.py"
GEN_PERSONA = PLUGIN_ROOT / "skills" / "eval-simulation" / "scripts" / "gen_persona.py"
VALIDATE_SIM = PLUGIN_ROOT / "skills" / "eval-simulation" / "scripts" / "validate_sim.py"

#: Deprecated 2026-09-30, retires 2026-11-30. The one id with a committed date.
DEPRECATED_ID = "claude-sonnet-4-5-20250929"
RETIREMENT_DATE = "2026-11-30"
LINT_AGENT = PLUGIN_ROOT / "skills" / "agent-review" / "scripts" / "lint_agent.py"
LINT_HARNESS = PLUGIN_ROOT / "skills" / "agent-harness" / "scripts" / "lint_harness.py"
FIXTURES = PLUGIN_ROOT / "tests" / "fixtures" / "agents"
REFERENCES = sorted((PLUGIN_ROOT / "skills").rglob("references/*.md"))

#: The dated note every reference re-read in this sync must carry, lower-cased
#: for comparison against `flat()`.
REREAD_NOTE = (
    "re-read 2026-10-11 against claude-agent-sdk 0.2.165 / claude code 2.1.296 docs"
)


def findings(script: Path, project: str, *extra: str) -> list[dict]:
    """Run a linter over a fixture and return its findings."""
    result = subprocess.run(
        [sys.executable, str(script), str(FIXTURES / project), "--json",
         "--no-path-check", *extra],
        capture_output=True, text=True, timeout=120,
    )
    assert result.stdout, result.stderr
    return json.loads(result.stdout)["findings"]


def by_id(found: list[dict], finding_id: str) -> list[dict]:
    return [f for f in found if f["id"] == finding_id]


def flat(text: str) -> str:
    """Collapse the newlines a footer wraps on, so a sentence can be matched.

    Lower-cased too: the note opens a sentence in some footers and continues
    one in others, so its first letter is not fixed.
    """
    return " ".join(text.split()).lower()


# -- OPT013 ----------------------------------------------------------------

def test_opt013_fires_when_permission_mode_is_never_passed():
    """`ci_ready` builds options without a `permission_mode`."""
    matches = by_id(findings(LINT_AGENT, "ci_ready"), "OPT013")
    assert len(matches) == 1, "exactly one OPT013 per options call"
    finding = matches[0]
    assert finding["severity"] == "warn"
    assert finding["area"] == "options"
    assert "auto" in finding["message"], "the message has to name the mode it lands in"
    assert "2.1.285" in finding["message"], "and the release the behaviour starts at"
    assert "dontAsk" in finding["fix"] and "default" in finding["fix"], \
        "the fix offers both explicit modes"
    assert "types.py:2380" in finding["source"], "cite the field it read"
    assert "permission-modes" in finding["source"], "and the page for the auto default"


@pytest.mark.parametrize("project", ["good", "trap", "drift", "deploy_ready"])
def test_opt013_stays_quiet_when_the_mode_is_explicit(project):
    """Every one of these fixtures passes a mode, including `bypassPermissions`.

    An explicit mode is a decision, even a bad one: `drift` gets `OPT002` for
    choosing `bypassPermissions`, never `OPT013` on top of it.
    """
    assert by_id(findings(LINT_AGENT, project), "OPT013") == []


def test_the_harness_linter_reports_opt013_too():
    """`permission_mode` is harness surface, so both linters see it."""
    matches = by_id(findings(LINT_HARNESS, "ci_ready"), "OPT013")
    assert len(matches) == 1
    assert matches[0]["severity"] == "warn"


def test_opt013_does_not_change_the_exit_code_on_its_own():
    """A warning is not an error; only `--strict` makes it fail a review."""
    plain = subprocess.run(
        [sys.executable, str(LINT_AGENT), str(FIXTURES / "ci_ready"), "--no-path-check"],
        capture_output=True, text=True, timeout=120,
    )
    strict = subprocess.run(
        [sys.executable, str(LINT_AGENT), str(FIXTURES / "ci_ready"), "--no-path-check",
         "--strict"],
        capture_output=True, text=True, timeout=120,
    )
    assert plain.returncode == 0, plain.stdout
    assert strict.returncode == 1, "a warning fails under --strict"


# -- model policy ----------------------------------------------------------

def test_a_deprecated_model_is_reported_with_its_committed_date():
    """`drift` pins `claude-sonnet-4-5-20250929`, deprecated 2026-09-30."""
    matches = by_id(findings(LINT_AGENT, "drift"), "AGT011")
    assert matches, "the deprecated id has to be reported"
    message = matches[0]["message"]
    assert "deprecated" in message
    assert "2026-11-30" in message, "the committed retirement date belongs in the message"
    assert matches[0]["severity"] == "warn", "deprecated is graded like retiring"


def test_the_fix_for_a_dead_model_names_current_ids_including_haiku_5_5():
    fix = by_id(findings(LINT_AGENT, "drift"), "AGT011")[0]["fix"]
    for current in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"):
        assert current in fix, f"{current} is current and should be offered"


def test_the_checks_module_falls_back_when_the_library_has_no_dates():
    """`_checks.py` reads `DEPRECATED_MODELS` defensively.

    The shape is the library's to choose (it is a mapping today). A reader that
    assumed one shape would break the review the next time it changed, so the
    helper accepts a mapping, pairs, or bare ids.
    """
    sys.path.insert(0, str(PLUGIN_ROOT / "lib"))
    sys.path.insert(0, str(LINT_AGENT.parent))
    import _checks

    assert _checks.retirement_date_of("claude-sonnet-4-5-20250929") == "2026-11-30"
    assert _checks.retirement_date_of("claude-sonnet-5-5") is None

    original = _checks.DEPRECATED_MODELS
    try:
        _checks.DEPRECATED_MODELS = (("m-1", "2027-01-01"),)
        assert _checks.retirement_date_of("m-1") == "2027-01-01"
        _checks.DEPRECATED_MODELS = ("m-2",)
        assert _checks.retirement_date_of("m-2") is None
        assert _checks.retirement_date_of("m-3") is None
    finally:
        _checks.DEPRECATED_MODELS = original


# -- citations and footers -------------------------------------------------

def test_no_reference_still_claims_the_old_sdk_version():
    stale = [
        str(path.relative_to(PLUGIN_ROOT))
        for path in REFERENCES
        if "claude-agent-sdk 0.2.162" in path.read_text(encoding="utf-8")
        or "claude-agent-sdk` 0.2.162" in path.read_text(encoding="utf-8")
    ]
    assert stale == [], f"re-pin the version label: {stale}"


def test_the_two_citations_phase_1_found_wrong_are_corrected():
    """`RateLimitInfo` is at 1398 (1392 is `RateLimitType`); `Skill` at 1991."""
    for path in REFERENCES:
        text = path.read_text(encoding="utf-8")
        name = str(path.relative_to(PLUGIN_ROOT))
        assert "1392` (`RateLimitInfo`)" not in text, f"{name}: RateLimitInfo is :1398"
        assert ":1990" not in text, f"{name}: the Skill deprecation is at :1991"


def test_every_reference_touched_by_this_sync_carries_the_reread_note():
    """A reference without the note was not re-read, which is information too.

    This asserts the note's exact wording on the files lane B re-read, so a
    future sync can list what it still has to check rather than guessing.
    """
    expected = {
        "agent-create/references/env-and-secrets.md",
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
        "agent-sdk/references/capability-map.md",
        "agent-sdk/references/environment.md",
        "agent-sdk/references/glossary.md",
        "agent-sdk/references/sdk-rename-migration.md",
        "eval-ci/references/subscription-and-secrets.md",
        "eval-ci/references/workflows.md",
        "eval-criteria/references/budgets-and-efficiency.md",
        "eval-criteria/references/grader-catalog.md",
        "eval-criteria/references/judge-options.md",
        "eval-run/references/cli-reference.md",
        "eval-run/references/cost-estimation.md",
        "eval-run/references/running-in-ci.md",
        "eval-simulation/references/fault-injection.md",
        "eval-simulation/references/mock-servers.md",
        "eval-simulation/references/user-simulation.md",
    }
    missing = sorted(
        name for name in expected
        if REREAD_NOTE not in flat((PLUGIN_ROOT / "skills" / name).read_text(encoding="utf-8"))
    )
    assert missing == [], f"these were re-read but carry no dated note: {missing}"


def test_a_0_2_166_claim_always_carries_its_gate():
    """A 0.2.166 name carries its version gate and reads as released.

    The names below shipped in claude-agent-sdk 0.2.166 (2026-10-14). The plugin
    still supports 0.2.140, so wherever a reference mentions one the same file
    has to say "0.2.166" (the gate), and no paragraph that names one may call it
    unreleased or `main`-only any more. (`defer` and `updatedMCPToolOutput`
    already existed in 0.2.165, so nothing here asks for them to be called new.)
    """
    released = ("HookEffort", "SystemInitData", "BackgroundTaskSummary",
                "SessionCronSummary", "last_assistant_message", "prompt_id")
    stale = ("unreleased", "on `main`", "not yet released", "main-only", "only on main")
    ungated: list[str] = []
    stale_wording: list[str] = []
    for path in REFERENCES:
        text = path.read_text(encoding="utf-8")
        if not any(name in text for name in released):
            continue
        name = str(path.relative_to(PLUGIN_ROOT))
        if "0.2.166" not in text:
            ungated.append(name)
        for paragraph in text.split("\n\n"):
            if any(n in paragraph for n in released) and \
                    any(w in paragraph.lower() for w in stale):
                stale_wording.append(name)
                break
    assert ungated == [], f"0.2.166 names without their version gate in {ungated}"
    assert stale_wording == [], f"released names still described as unreleased in {stale_wording}"


# -- plugin eval rubrics ---------------------------------------------------

CRITERIA = sorted((PLUGIN_ROOT / "plugin-evals").glob("*/graders/criteria.md"))


def test_there_is_a_criteria_rubric_for_every_case():
    cases = {p.name for p in (PLUGIN_ROOT / "plugin-evals").iterdir()
             if p.is_dir() and (p / "case.yaml").is_file()}
    assert {p.parent.parent.name for p in CRITERIA} == cases


@pytest.mark.parametrize("rubric", CRITERIA, ids=lambda p: p.parent.parent.name)
def test_every_rubric_fails_a_verdict_given_without_running_a_script(rubric):
    """The one clause every tightened rubric shares.

    Without it a model that happens to know the Agent SDK can pass a case by
    answering from memory, which measures the model and not the skill.
    """
    text = rubric.read_text(encoding="utf-8")
    assert "without running the plugin's script" in text, "add the shared FAIL clause"
    assert "FAIL if it:" in text


@pytest.mark.parametrize("rubric", CRITERIA, ids=lambda p: p.parent.parent.name)
def test_every_rubric_judges_the_trace_and_not_the_last_message(rubric):
    """`focus` defaults to `last_message`, which cannot see a script's output.

    Every rubric here demands evidence "shown in the transcript", so the judge
    has to be given the transcript: `focus: trace` shows it the first 12 and
    the last 12 messages. Without this line the rubrics are unsatisfiable and
    the 2026-10-13 run voted FAIL 3/3 in both arms of all three cases tried.
    """
    head = rubric.read_text(encoding="utf-8").split("---")[1]
    assert "type: llm" in head, "the rubric is a judged grader"
    assert "focus: trace" in head, "add focus: trace or the judge sees only the last message"


@pytest.mark.parametrize("rubric", CRITERIA, ids=lambda p: p.parent.parent.name)
def test_every_rubric_has_an_evidence_block_naming_its_script(rubric):
    """PASS has to rest on output the transcript can be checked against.

    Every tightened rubric carries a block that says which of the plugin's
    scripts the evidence comes from, by file name. A rubric that names no
    script is one a judge can satisfy from the prose of the answer alone.
    """
    text = rubric.read_text(encoding="utf-8")
    assert "Evidence the rubric requires" in text, "add the evidence block"
    assert re.search(r"`[a-z_]+\.py`", text), "name the script the evidence comes from"
    assert "transcript" in text, "say where the output has to be visible"


def test_the_evidence_kinds_this_sync_required_are_each_used_somewhere():
    """The four kinds the sync asked for, each pinned to at least one rubric.

    Not every case can produce every kind — `pass-at-k` has no credential line
    and no finding id of its own — so this asserts the set is covered across
    the suite rather than per file.
    """
    texts = {p.parent.parent.name: p.read_text(encoding="utf-8") for p in CRITERIA}
    joined = "\n".join(texts.values())

    assert "## Found" in joined and "## Missing" in joined, \
        "the discovery report blocks have to be required somewhere"
    for finding_id in ("EVC003", "AGT030", "DEP001"):
        assert finding_id in joined, f"{finding_id} is a finding only a script prints"
    assert "cost basis" in joined, "the credential line with its cost basis"
    assert "cost tier" in joined or "`cost:`" in joined, "a cost tier on each option"

    # The two cases the plan named for the first tightened run have to be the
    # strictest: both ask for a specific finding id.
    assert "EVC003" in texts["case-validate"]
    assert "AGT030" in texts["agent-review-drift"]
    assert "`## Found`" in texts["routing-ambiguous"]


# -- ENV003: the pin is reported, and newer is not a blocker ---------------

def test_check_env_reports_the_versions_the_plugin_was_checked_against(
        run_script, isolated_agent, fake_sdk, monkeypatch):
    """A newer SDK is information, never a blocker.

    `isolated_agent` for the credential (a `.env` above the checkout otherwise
    decides it) and `fake_sdk` for the interpreter, whose reported version this
    test moves past the pin.
    """
    monkeypatch.setenv("FAKE_SDK_VERSION", "0.2.200")
    result = run_script(CHECK_ENV, isolated_agent("good"), "--json", "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    assert result.returncode == 0, result.stdout + result.stderr
    doc = result.json()
    assert doc["checked_against"] == {"sdk": SDK_TARGET, "cli": CLI_BUNDLED_WITH_TARGET}
    assert doc["sdk_newer_than_checked"] is True
    assert doc["ready"] is True and doc["blockers"] == [], \
        "ENV003 is info: being newer than the pin cannot block a run"


def test_check_env_prose_names_the_pin_and_the_env003_note(
        run_script, isolated_agent, fake_sdk, monkeypatch):
    monkeypatch.setenv("FAKE_SDK_VERSION", "0.2.200")
    result = run_script(CHECK_ENV, isolated_agent("good"), "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    assert result.returncode == 0, result.stderr
    assert f"- checked against: claude-agent-sdk {SDK_TARGET} " \
           f"(bundled Claude Code {CLI_BUNDLED_WITH_TARGET})" in result.stdout
    assert "- ENV003:" in result.stdout and "0.2.200 is newer" in result.stdout
    assert result.stdout.strip().endswith("ready")


def test_check_env_stays_quiet_when_the_installed_sdk_matches_the_pin(
        run_script, isolated_agent, fake_sdk):
    """The fake interpreter reports the pin by default, so there is no note."""
    result = run_script(CHECK_ENV, isolated_agent("good"), "--json", "--no-cli",
                        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    doc = result.json()
    assert doc["sdk_newer_than_checked"] is False
    assert doc["checked_against"]["sdk"] == SDK_TARGET


# -- a deprecated persona model carries its date --------------------------

def test_gen_persona_reports_a_deprecated_model_with_its_date(run_script, tmp_agent):
    """`SIM006` used to miss `deprecated` entirely: it is neither retiring nor
    unknown, so the persona would have been written without a word."""
    result = run_script(
        "skills/eval-simulation/scripts/gen_persona.py", tmp_agent("good"),
        "--name", "member", "--model", DEPRECATED_ID, "--defaults", "--dry-run",
    )
    assert "SIM006" in result.stdout, result.stdout
    assert "deprecated" in result.stdout
    assert RETIREMENT_DATE in result.stdout, "the committed date belongs in the note"


def test_validate_sim_reports_a_deprecated_persona_model_with_its_date(
        run_script, tmp_agent):
    project = tmp_agent("good")
    personas = project / "evals" / "personas"
    personas.mkdir(parents=True, exist_ok=True)
    (personas / "member.json").write_text(json.dumps({
        "name": "member",
        "goal": "reserve a book that is already out",
        "model": DEPRECATED_ID,
        "max_user_turns": 3,
        "violation_rubrics": ["the user never states a fact the agent has not asked for"],
    }, indent=2) + "\n", encoding="utf-8")

    result = run_script("skills/eval-simulation/scripts/validate_sim.py", project, "--json")
    found = json.loads(result.stdout)["findings"]
    matches = [f for f in found if f["id"] == "SIM006"]
    assert matches, f"SIM006 should fire on {DEPRECATED_ID}: {[f['id'] for f in found]}"
    assert matches[0]["severity"] == "warn", "deprecated is graded like retiring"
    assert "deprecated" in matches[0]["message"]
    assert RETIREMENT_DATE in matches[0]["message"]


def test_a_current_persona_model_is_not_flagged(run_script, tmp_agent):
    project = tmp_agent("good")
    personas = project / "evals" / "personas"
    personas.mkdir(parents=True, exist_ok=True)
    (personas / "member.json").write_text(json.dumps({
        "name": "member",
        "goal": "reserve a book that is already out",
        "model": "claude-haiku-5-5",
        "max_user_turns": 3,
        "violation_rubrics": ["the user never states a fact the agent has not asked for"],
    }, indent=2) + "\n", encoding="utf-8")

    result = run_script("skills/eval-simulation/scripts/validate_sim.py", project, "--json")
    found = json.loads(result.stdout)["findings"]
    assert [f for f in found if f["id"] == "SIM006"] == [], \
        "Haiku 5.5 is current; naming it as the cheap simulator must not warn"


# -- the 2026-10-13 live run: restraint graders that matched advice ----------
#
# Two `not_contains` regex graders fired on *printed text* rather than on an
# action, so both cases failed for a thing the model never did: `run-dry-run`'s
# grader matched the dry run's own `- command: python3 -m agent_sdk_evals run
# evals --tier pr --out ...` output line (and the fixture README's
# `python -m agent_sdk_evals run evals --tier pr`), and `runner-stale`'s matched
# CFG050's own fix text, `run install_runner.py --upgrade (it shows a diff
# first)`. Both are now anchored on the `"command"` key of a Bash tool call and
# consume only that one JSON string. The trace is JSON, one message per line,
# with inner quotes escaped as `\"`, which is what keeps the anchor honest.

GRADER_NOTHING_RAN = PLUGIN_ROOT / "plugin-evals" / "run-dry-run" / "graders" / "nothing-ran.md"
GRADER_NOT_UPGRADED = (PLUGIN_ROOT / "plugin-evals" / "runner-stale" / "graders"
                       / "upgrade-not-applied.md")


def grader_pattern(path: Path) -> str:
    """The grader's own `pattern`, read the way the eval harness reads it."""
    from agent_sdk_skills import frontmatter

    meta = frontmatter.parse(path.read_text(encoding="utf-8")).meta
    assert meta["type"] == "regex" and meta["match"] == "not_contains", meta
    assert meta["target"] == "trace"
    return meta["pattern"]


def bash_call(command: str) -> str:
    """One trace line for a Bash tool call, as the harness writes it."""
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_1", "name": "Bash",
         "input": {"command": command, "description": "d"}}]}})


def tool_result(text: str) -> str:
    """One trace line for a tool result, whose inner quotes are escaped."""
    return json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": text}]}})


@pytest.mark.parametrize("line", [
    # The dry run prints the command it would have run. Advice, not an action.
    tool_result("# eval-run (dry run)\n\n- tier: pr\n- command: python3 -m "
                "agent_sdk_evals run evals --tier pr --out /tmp/x/evals/results/20261013T0900\n"),
    # So does the fixture's README, which a session reads on the way in.
    tool_result("Evaluate it: `python -m agent_sdk_evals run evals --tier pr` "
                "(from `evals/runner` on `PYTHONPATH`)."),
    # Saying the command in prose is not running it either.
    json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Next, `python -m agent_sdk_evals run evals --tier pr`."}]}}),
    bash_call("python3 -m agent_sdk_evals run evals --tier pr --dry-run"),
    bash_call("python3 skills/eval-run/scripts/run_evals.py . --tier pr --dry-run"),
])
def test_the_nothing_ran_grader_ignores_everything_but_a_bash_command(line):
    assert re.search(grader_pattern(GRADER_NOTHING_RAN), line) is None, line[:200]


@pytest.mark.parametrize("command", [
    "python3 -m agent_sdk_evals run evals --tier pr",
    "cd evals/runner && python3 -m agent_sdk_evals run evals --tier nightly --out /tmp/o",
])
def test_the_nothing_ran_grader_still_catches_a_real_run(command):
    assert re.search(grader_pattern(GRADER_NOTHING_RAN), bash_call(command)), command


@pytest.mark.parametrize("line", [
    # CFG050's own fix text, which the reply is supposed to quote.
    tool_result("- **CFG050** the config declares runner_version 0.0.1. "
                "Fix: run install_runner.py --upgrade (it shows a diff first)"),
    json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Run `install_runner.py --upgrade` when you want the fix."}]}}),
    bash_call("python3 skills/agent-create/scripts/install_runner.py . --upgrade --dry-run"),
    bash_call("python3 skills/agent-create/scripts/install_runner.py . --json"),
])
def test_the_upgrade_grader_ignores_everything_but_a_bash_command(line):
    assert re.search(grader_pattern(GRADER_NOT_UPGRADED), line) is None, line[:200]


@pytest.mark.parametrize("command", [
    "python3 skills/agent-create/scripts/install_runner.py . --upgrade",
    "python3 install_runner.py /tmp/proj --upgrade --json",
])
def test_the_upgrade_grader_still_catches_a_real_upgrade(command):
    assert re.search(grader_pattern(GRADER_NOT_UPGRADED), bash_call(command)), command


def test_every_restraint_regex_grader_is_anchored_on_an_action():
    """A `not_contains` grader on the trace must look at a tool call, not prose.

    The two fixed here are anchored on `"command"`; the other four are anchored
    on a quoted tool name (`"Edit"` / `"Write"`), which only appears unescaped
    in a tool-call record. A new one anchored on neither would be matching text
    the model merely printed, which is how both of these failed on 2026-10-13.
    """
    from agent_sdk_skills import frontmatter

    unanchored = []
    for path in sorted((PLUGIN_ROOT / "plugin-evals").glob("*/graders/*.md")):
        text = path.read_text(encoding="utf-8")
        # Cheap pre-filter: a judge grader's frontmatter is not this parser's.
        if "type: regex" not in text or "match: not_contains" not in text:
            continue
        meta = frontmatter.parse(text).meta
        if meta.get("target") != "trace":
            continue
        pattern = str(meta.get("pattern", ""))
        if '"command"' not in pattern and '"(?:Edit|Write)"' not in pattern:
            unanchored.append(str(path.relative_to(PLUGIN_ROOT)))
    assert unanchored == [], (
        "anchor these on a Bash `\"command\"` or a quoted tool name, or they match "
        f"printed advice: {unanchored}")
