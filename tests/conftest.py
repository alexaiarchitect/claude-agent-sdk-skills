"""Shared test fixtures.

The plugin's library is stdlib-only, so tests import it directly. Scripts are
exercised as subprocesses, the way a skill runs them, so their argument parsing
and exit codes are covered too. Anything that would need the real Claude Agent
SDK goes through `AGENT_SDK_PYTHON`, which the tests point at the fake
interpreter in `fixtures/bin/`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LIB = PLUGIN_ROOT / "lib"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(LIB))


@dataclass
class ScriptRun:
    returncode: int
    stdout: str
    stderr: str

    def json(self) -> dict:
        return json.loads(self.stdout)

    @property
    def combined(self) -> str:
        return f"{self.stdout}\n{self.stderr}"


#: Interpreters that may have the real `claude_agent_sdk` installed, most
#: specific first. The target venv is named for the release the plugin was
#: checked against (`SDK_TARGET`, 0.2.168); the previous target's venv and the
#: unversioned path are the older conventions, kept as fallbacks. `AGENT_SDK_TEST_PYTHON` overrides both.
SDK_VENV_CANDIDATES = (
    os.environ.get("AGENT_SDK_TEST_PYTHON") or "",
    "/tmp/casdk-venv-0.2.168/bin/python",
    "/tmp/casdk-venv-0.2.165/bin/python",
    "/tmp/casdk-venv/bin/python",
)


def resolve_sdk_python() -> str | None:
    """The first candidate that can actually import the SDK, or `None`.

    Existence is not enough: `/tmp/casdk-venv` has been reaped before, leaving
    an interpreter whose site-packages no longer holds the SDK, and a test that
    trusted the path would fail where it should skip.
    """
    for candidate in SDK_VENV_CANDIDATES:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            proc = subprocess.run([candidate, "-c", "import claude_agent_sdk"],
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return candidate
    return None


@pytest.fixture(scope="session")
def sdk_python() -> str:
    """An interpreter with the real SDK, or skip.

    Most of this suite runs against the stub in `fixtures/stubs/`, which is what
    keeps it fast and offline. The handful of tests that check the plugin's
    pinned facts against the *installed* wheel need the real thing, and skip
    without it — but the sync that re-pins those facts is expected to build the
    venv and watch them run.
    """
    found = resolve_sdk_python()
    if found is None:
        pytest.skip(
            "no interpreter with claude_agent_sdk installed; tried "
            + ", ".join(c for c in SDK_VENV_CANDIDATES if c)
            + ". Build one with: python3.12 -m venv /tmp/casdk-venv-0.2.168 && "
            "/tmp/casdk-venv-0.2.168/bin/pip install 'claude-agent-sdk==0.2.168'"
        )
    return found


@pytest.fixture(scope="session")
def plugin_root() -> Path:
    return PLUGIN_ROOT


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def fake_sdk(monkeypatch, fixtures: Path) -> Path:
    """Point the runner-resolution chain at the fake SDK interpreter."""
    fake = fixtures / "bin" / "fake_sdk.py"
    monkeypatch.setenv("AGENT_SDK_PYTHON", str(fake))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    return fake


@pytest.fixture
def run_script():
    """Run a plugin script by its path relative to the plugin root."""

    def _run(relative: str, *args: str, cwd: Path | str | None = None,
             env: dict[str, str] | None = None) -> ScriptRun:
        script = PLUGIN_ROOT / relative
        assert script.is_file(), f"no such script: {script}"
        import os
        merged = {**os.environ, **(env or {})}
        proc = subprocess.run(
            [sys.executable, str(script), *[str(a) for a in args]],
            capture_output=True, text=True, cwd=str(cwd) if cwd else None,
            timeout=300, env=merged,
        )
        return ScriptRun(proc.returncode, proc.stdout, proc.stderr)

    return _run


@pytest.fixture
def agent_dir(fixtures: Path):
    """A fixture project by name, e.g. `agent_dir("good")`."""

    def _get(name: str) -> Path:
        path = fixtures / "agents" / name
        assert path.is_dir(), f"no such fixture agent: {path}"
        return path

    return _get


@pytest.fixture
def tmp_agent(tmp_path: Path, fixtures: Path):
    """A writable copy of a fixture project, for tests that generate files."""

    def _copy(name: str) -> Path:
        source = fixtures / "agents" / name
        target = tmp_path / name
        shutil.copytree(source, target)
        return target

    return _copy


#: Every variable `detect_credential` reads from the process environment. A
#: test about credentials deletes all of them and sets back only what it means
#: to test, so the developer's own shell cannot change the answer.
CREDENTIAL_ENV_KEYS = (
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "CLAUDE_MODEL", "AGENT_ENTRY",
    "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS",
)


@pytest.fixture
def isolated_agent(tmp_path: Path, fixtures: Path, monkeypatch):
    """A fixture project whose credential is exactly what the test sets.

    Two leaks have to be closed for that to be true, and the obvious one is not
    the one that bit us. `detect_credential` reads the process environment *and*
    the nearest `.env` files above the project, walking all the way up — so a
    fixture project living inside this repository picks up any `.env` a
    developer keeps beside the checkout, and a test asserting "no credential" or
    "subscription" fails on their machine and passes in CI. Measured: an
    `ANTHROPIC_API_KEY` two directories above the repo turned three tests red.

    So the project is copied under `tmp_path`, outside the repository and any
    `.env` near it, and every credential variable is deleted from the
    environment. A test then sets back only what it is about.
    """

    # Scrubbed at setup, before the test body runs, so a test is free to set a
    # credential back and have it survive the call to `_copy`.
    for key in CREDENTIAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def _copy(name: str) -> Path:
        source = fixtures / "agents" / name
        target = tmp_path / name
        shutil.copytree(source, target)
        stray = [
            str(folder / ".env")
            for folder in target.parents
            if (folder / ".env").is_file()
        ]
        assert not stray, (
            "a .env above the temporary directory would still be read as this project's "
            "credential: " + ", ".join(stray)
        )
        return target

    return _copy
