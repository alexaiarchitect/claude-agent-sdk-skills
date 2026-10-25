"""Conventions that hold across the whole plugin.

These are the rules that stop the plugin drifting as it grows: every skill has a
usable description, every reference cites its sources, every script supports
`--json`, every linked file exists, every script path a skill prints resolves —
including the cross-skill ones — no bare `SKILL_DIR` placeholder survives, the
plugin-side code never imports the SDK it inspects, the runner copy the plugin
ships carries the version the library expects, and nothing from a
non-redistributable source has been copied in.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted(p for p in (PLUGIN_ROOT / "skills").iterdir() if p.is_dir())
SKILL_FILES = [p / "SKILL.md" for p in SKILLS]
REFERENCES = sorted((PLUGIN_ROOT / "skills").rglob("references/*.md"))
SCRIPTS = sorted(
    p for p in (PLUGIN_ROOT / "skills").rglob("scripts/*.py") if not p.name.startswith("_")
)
LIB_MODULES = sorted((PLUGIN_ROOT / "lib" / "agent_sdk_skills").glob("*.py"))
RUNNER_ROOT = PLUGIN_ROOT / "runner" / "agent_sdk_evals"
RUNNER_MODULES = sorted(RUNNER_ROOT.rglob("*.py"))

EXPECTED_SKILLS = {
    "agent-sdk", "agent-create", "agent-review", "agent-debug", "agent-harness",
    "agent-deploy", "eval-create", "eval-criteria", "eval-review", "eval-run",
    "eval-analyze", "eval-simulation", "eval-ci", "agent-design",
}


def frontmatter(path: Path) -> dict[str, str]:
    """Parse the YAML-ish frontmatter without a YAML dependency."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: no frontmatter"
    block = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        match = re.match(r"^([a-z-]+):\s*(.*)$", line)
        if match:
            key = match.group(1)
            fields[key] = match.group(2).strip()
        elif key and line.strip():
            fields[key] = f"{fields[key]} {line.strip()}".strip()
    return fields


# -- structure -------------------------------------------------------------

def test_the_expected_skills_are_all_present():
    assert {p.name for p in SKILLS} == EXPECTED_SKILLS


def test_the_plugin_manifest_is_valid():
    manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "agent-sdk"
    assert manifest["description"]
    assert re.match(r"^\d+\.\d+\.\d+$", manifest["version"])
    assert "dependencies" not in manifest, "agent-sdk-dev is a soft reference, not a dependency"
    assert manifest["experimental"]["evals"] == "plugin-evals", "the plugin's own suite must not share the name of projects' evals/ dirs"


def test_the_marketplace_manifest_names_this_plugin():
    marketplace = json.loads((PLUGIN_ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert marketplace["name"] == "alexaiarchitect-agent-sdk"
    assert [p["name"] for p in marketplace["plugins"]] == ["agent-sdk"]


def test_licensing_files_are_present():
    assert (PLUGIN_ROOT / "LICENSE").is_file()
    notices = (PLUGIN_ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for project in ("claude-agent-sdk-python", "claude-code", "claude-cookbooks"):
        assert project in notices


# -- SKILL.md --------------------------------------------------------------

@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_skill_has_a_name_matching_its_directory(skill):
    assert frontmatter(skill)["name"] == skill.parent.name


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_description_says_when_to_use_and_when_not_to(skill):
    description = frontmatter(skill)["description"]
    assert len(description) > 200, "too short to route on"
    assert "Use when" in description
    assert "Don't use" in description, "a description needs to say what it is not for"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_skill_declares_the_tools_it_needs(skill):
    tools = frontmatter(skill)["allowed-tools"]
    assert "AskUserQuestion" in tools, "the confirm step needs it"
    assert "Bash(python3 *)" in tools, "every skill runs its own scripts"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_no_skill_forks_its_context(skill):
    """A forked context cannot ask the user anything, and every skill here
    confirms before acting."""
    assert "context" not in frontmatter(skill)


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_bodies_stay_short_enough_to_load(skill):
    lines = skill.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 200, f"{len(lines)} lines; move detail into references/"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_skill_has_a_completion_checklist(skill):
    assert "## Completion checklist" in skill.read_text(encoding="utf-8")


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_linked_reference_exists(skill):
    text = skill.read_text(encoding="utf-8")
    for link in re.findall(r"\]\((references/[^)]+)\)", text):
        assert (skill.parent / link).is_file(), f"{skill.parent.name}: dead link to {link}"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_script_a_skill_names_exists(skill):
    text = skill.read_text(encoding="utf-8")
    for match in re.findall(r"(?:\$\{CLAUDE_SKILL_DIR\}/|`)(scripts/[a-z_]+\.py)", text):
        assert (skill.parent / match).is_file(), f"{skill.parent.name}: names a missing {match}"


#: `${CLAUDE_SKILL_DIR}/../<skill>/scripts/<name>.py`
CROSS_SKILL_SCRIPT = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/\.\./([a-z-]+)/(scripts/[a-z_]+\.py)")


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_cross_skill_script_a_skill_names_exists(skill):
    text = skill.read_text(encoding="utf-8")
    for other, script in CROSS_SKILL_SCRIPT.findall(text):
        target = skill.parent.parent / other / script
        assert target.is_file(), f"{skill.parent.name}: names a missing {other}/{script}"


COMMAND_BEARING = SKILL_FILES + REFERENCES
BARE_SKILL_DIR = re.compile(r"(?<!\{CLAUDE_)\bSKILL_DIR\b")


@pytest.mark.parametrize("document", COMMAND_BEARING, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_no_bare_skill_dir_placeholder_survives(document):
    text = document.read_text(encoding="utf-8")
    offenders = [line.strip() for line in text.splitlines() if BARE_SKILL_DIR.search(line)]
    assert offenders == [], f"use ${{CLAUDE_SKILL_DIR}}: {offenders}"


# -- references ------------------------------------------------------------

@pytest.mark.parametrize("reference", REFERENCES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_reference_cites_its_sources(reference):
    """A claim about SDK behaviour the reader cannot check is a claim they have
    to take on trust."""
    text = reference.read_text(encoding="utf-8")
    assert "Sources:" in text, "add a Sources: footer"
    assert text.rstrip().endswith((".", ")", "`")), "the footer looks truncated"


@pytest.mark.parametrize("reference", REFERENCES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_references_are_substantial_but_not_sprawling(reference):
    lines = reference.read_text(encoding="utf-8").splitlines()
    assert 25 <= len(lines) <= 250, f"{len(lines)} lines"


@pytest.mark.parametrize("reference", REFERENCES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_references_cite_the_current_docs_host(reference):
    """The Agent SDK docs moved to code.claude.com; the old hosts redirect today
    and will not forever."""
    text = reference.read_text(encoding="utf-8")
    assert "docs.claude.com/en/api/agent-sdk" not in text
    assert "docs.anthropic.com" not in text


#: An Anthropic article citation: `anthropic.com/research|engineering/<slug>` or
#: `claude.com/...` (never `code.claude.com`, which the scheme anchor excludes).
ARTICLE_URL = re.compile(
    r"https?://(?:www\.)?(?:anthropic\.com/(?:research|engineering)/|claude\.com/)[^\s`>)\"']+")
ANY_URL = re.compile(r"https?://")
DATED_PARENTHETICAL = re.compile(r"\(.*?20\d\d-\d\d-\d\d", re.DOTALL)


@pytest.mark.parametrize("reference", REFERENCES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_article_citations_are_dated(reference):
    """An article is a dated snapshot of someone's practice, not documentation:
    every article URL in a `Sources:` footer carries `(…, YYYY-MM-DD, …)` before
    the next URL, so a reader can tell how old the advice is."""
    text = reference.read_text(encoding="utf-8")
    undated = []
    for start in [m.start() for m in re.finditer(r"Sources:", text)]:
        footer = text[start:]
        heading = re.search(r"\n#", footer)
        footer = footer[:heading.start()] if heading else footer
        for match in ARTICLE_URL.finditer(footer):
            following = ANY_URL.search(footer, match.end())
            segment = footer[match.end():following.start() if following else len(footer)]
            if not DATED_PARENTHETICAL.search(segment):
                undated.append(match.group(0))
    assert undated == [], "cite as <URL> (\"Title\", YYYY-MM-DD, what it is cited for)"


@pytest.mark.parametrize("reference", REFERENCES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_article_citations_use_the_research_path(reference):
    """`anthropic.com/engineering/<slug>` now 308-redirects to
    `anthropic.com/research/<slug>` (measured 2026-10-29); cite the canonical one."""
    assert "anthropic.com/engineering/" not in reference.read_text(encoding="utf-8")


# -- scripts ---------------------------------------------------------------

@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_script_has_help_and_a_docstring(script):
    result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout) > 200, "the help text should explain why, not just how"


#: Scripts that hand another tool's output straight through.
PASSTHROUGH_SCRIPTS: set[str] = set()


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_script_speaks_json(script):
    if script.name in PASSTHROUGH_SCRIPTS:
        pytest.skip("passes another tool's output and exit code through unchanged")
    result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=60)
    assert "--json" in result.stdout


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_script_finds_the_shared_library_the_same_way(script):
    text = script.read_text(encoding="utf-8")
    assert 'parents[3] / "lib"' in text, "scripts locate lib relative to their own path"


def code_outside_strings(path: Path) -> str:
    """The module's source with string literals and comments blanked out.

    Several scripts carry probe source as a string, to be executed by a
    *different* interpreter that does have the SDK. That is not an import here,
    so the dependency checks look at real code only.
    """
    import ast as _ast
    import io
    import tokenize

    source = path.read_text(encoding="utf-8")
    dropped = {tokenize.STRING, tokenize.COMMENT}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, name):
            dropped.add(getattr(tokenize, name))
    kept: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in dropped:
                continue
            kept.append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    _ast.parse(source)
    return " ".join(kept)


BANNED_PLUGIN_SIDE = (
    "claude_agent_sdk", "import anthropic", "from anthropic", "import pydantic",
    "from pydantic", "import yaml", "import requests",
)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_scripts_import_no_third_party_package(script):
    """They must run on a bare interpreter, before the project's environment works."""
    code = code_outside_strings(script)
    for name in BANNED_PLUGIN_SIDE:
        assert name not in code, f"{script.name} uses {name} in real code"


# -- library ---------------------------------------------------------------

@pytest.mark.parametrize("module", LIB_MODULES, ids=lambda p: p.name)
def test_the_library_is_standard_library_only(module):
    code = code_outside_strings(module)
    for name in BANNED_PLUGIN_SIDE:
        assert name not in code, f"{module.name} uses {name} in real code"


@pytest.mark.parametrize("module", LIB_MODULES, ids=lambda p: p.name)
def test_every_library_module_explains_itself(module):
    text = module.read_text(encoding="utf-8")
    assert text.lstrip().startswith('"""'), f"{module.name} has no module docstring"


def test_the_library_never_executes_agent_code():
    """Reviews must work on a project whose imports are the problem, so the
    readers parse and never run what they read. `ast.literal_eval` is fine."""
    for name in ("layout.py", "options_ast.py"):
        path = PLUGIN_ROOT / "lib" / "agent_sdk_skills" / name
        if not path.is_file():
            continue
        code = code_outside_strings(path).replace("ast . literal_eval", "").replace("ast.literal_eval", "")
        for banned in ("exec(", "eval(", "importlib", "__import__", "subprocess"):
            assert banned not in code, f"{name} uses {banned}"


# -- runner ----------------------------------------------------------------

def test_the_runner_copy_carries_the_library_version():
    sys.path.insert(0, str(PLUGIN_ROOT / "lib"))
    from agent_sdk_skills import RUNNER_VERSION

    version_file = RUNNER_ROOT / "VERSION"
    assert version_file.is_file(), "runner/agent_sdk_evals/VERSION is missing"
    assert version_file.read_text(encoding="utf-8").strip() == RUNNER_VERSION


@pytest.mark.parametrize("module", RUNNER_MODULES, ids=lambda p: str(p.relative_to(RUNNER_ROOT)))
def test_the_runner_imports_only_the_sdk_and_stdlib(module):
    """The runner is copied into user projects; `claude_agent_sdk` is its only
    dependency, so an `anthropic` or `pydantic` import would break the copy."""
    code = code_outside_strings(module)
    for name in ("import anthropic", "from anthropic", "import pydantic", "from pydantic",
                 "import yaml", "import requests", "agent_sdk_skills"):
        assert name not in code, f"runner {module.name} uses {name}"


# -- provenance ------------------------------------------------------------

#: Text that would indicate content copied from a source that may not be
#: redistributed (the TypeScript SDK repository is under commercial terms) or
#: from a phrasing this plugin retired.
FORBIDDEN_MARKERS = (
    "all rights reserved. use is subject to anthropic's commercial terms",
)


def test_nothing_forbidden_was_copied_in():
    offenders: list[str] = []
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in (".md", ".py", ".json", ".yml", ".yaml", ".tmpl"):
            continue
        if ".git" in path.parts or ".dev" in path.parts or path.name == "test_plugin_hygiene.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {marker}")
    assert offenders == [], offenders


def test_no_shipped_asset_is_gitignored():
    """Every file under an assets directory and the runner must be publishable."""
    import shutil

    if not shutil.which("git") or not (PLUGIN_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    shipped = sorted(
        str(p.relative_to(PLUGIN_ROOT))
        for pattern in ("skills/*/assets/**/*", "runner/**/*")
        for p in PLUGIN_ROOT.glob(pattern) if p.is_file() and "__pycache__" not in p.parts
    )
    if not shipped:
        pytest.skip("no shipped assets yet")
    proc = subprocess.run(["git", "check-ignore", "--no-index", *shipped],
                          cwd=PLUGIN_ROOT, capture_output=True, text=True)
    assert proc.stdout.strip() == "", f"ignored shipped files:\n{proc.stdout}"
