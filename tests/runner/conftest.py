"""Make the runner importable without the real SDK.

These tests run on plain `python3`. The runner package comes from
`runner/` and `claude_agent_sdk` from the stub in `tests/fixtures/stubs/`, which
mirrors the real wheel's public names and dataclass fields. Nothing here calls a
model; the stub replays scripted message lists instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
STUBS = PLUGIN_ROOT / "tests" / "fixtures" / "stubs"
RUNNER = PLUGIN_ROOT / "runner"
MINI = Path(__file__).resolve().parent / "fixtures" / "mini_project"
MEASURED = PLUGIN_ROOT / ".dev" / "measured"

for path in (str(STUBS), str(RUNNER), str(PLUGIN_ROOT / "lib")):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(scope="session")
def plugin_root() -> Path:
    return PLUGIN_ROOT


@pytest.fixture(scope="session")
def mini_project() -> Path:
    return MINI


@pytest.fixture(scope="session")
def mini_evals() -> Path:
    return MINI / "evals"


@pytest.fixture(autouse=True)
def clean_stub():
    """Every test starts with an empty script and no leaked credential env."""
    import claude_agent_sdk as sdk

    sdk.reset()
    yield
    sdk.reset()


@pytest.fixture
def measured():
    """A measured live run from `.dev/measured/`, as a stub script, or skip."""

    def _load(name: str) -> list[dict]:
        path = MEASURED / name
        if not path.is_file():
            pytest.skip(f"{path} is not present (the .dev/ audit trail is gitignored)")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    return _load


@pytest.fixture
def grader():
    """Build a `Grader` without a file on disk."""
    from agent_sdk_evals.loader import GRADER_SPEC, Grader

    def _make(type_: str, body: str = "", name: str | None = None, **fields):
        tier = GRADER_SPEC.get(type_, ("free", ()))[0]
        return Grader(name=name or type_, type=type_, fields=dict(fields), body=body,
                      path=MINI / "evals" / "synthetic" / "graders" / f"{type_}.md", tier=tier)

    return _make


@pytest.fixture
def evidence():
    """Build an `Evidence` with sensible empty defaults."""
    from agent_sdk_evals.graders import Evidence

    def _make(**kwargs):
        return Evidence(**kwargs)

    return _make


@pytest.fixture
def capture():
    from agent_sdk_evals.capture import Capture

    def _make(**kwargs):
        kwargs.setdefault("run_id", "t.1")
        kwargs.setdefault("case", "t")
        return Capture(**kwargs)

    return _make


@pytest.fixture
def project(tmp_path, mini_project):
    """A writable copy of the mini project, so a test may add cases to it."""
    import shutil

    target = tmp_path / "mini"
    shutil.copytree(mini_project, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target
