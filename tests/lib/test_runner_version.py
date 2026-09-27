"""Stale, newer, missing and modified runner copies each get their own finding."""

from agent_sdk_skills import RUNNER_VERSION
from agent_sdk_skills.runner_version import build_manifest, findings_for, inspect_runner_copy


def make_copy(root, version, *, manifest=True, tamper=False):
    package = root / "agent_sdk_evals"
    package.mkdir(parents=True)
    (package / "VERSION").write_text(version + "\n")
    (package / "__init__.py").write_text("x = 1\n")
    if manifest:
        (package / "MANIFEST.sha256").write_text(build_manifest(package))
    if tamper:
        (package / "__init__.py").write_text("x = 2\n")
    return root


def test_missing_copy_is_dep003(tmp_path):
    ids = [f.id for f in findings_for(inspect_runner_copy(tmp_path / "runner"))]
    assert ids == ["DEP003"]


def test_same_version_is_clean(tmp_path):
    copy = inspect_runner_copy(make_copy(tmp_path / "runner", RUNNER_VERSION))
    assert copy.status == "same" and findings_for(copy) == []


def test_older_copy_warns_and_newer_copy_errors(tmp_path):
    older = inspect_runner_copy(make_copy(tmp_path / "a", "0.0.1"))
    newer = inspect_runner_copy(make_copy(tmp_path / "b", "9.9.9"))
    assert [f.id for f in findings_for(older)] == ["DEP001"]
    assert [(f.id, f.severity) for f in findings_for(newer)] == [("DEP002", "error")]


def test_modified_copy_is_reported(tmp_path):
    copy = inspect_runner_copy(make_copy(tmp_path / "runner", RUNNER_VERSION, tamper=True))
    assert copy.modified == ["__init__.py"]
    assert [f.id for f in findings_for(copy)] == ["DEP004"]
