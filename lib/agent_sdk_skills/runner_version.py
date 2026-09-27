"""Is the project's copy of the eval runner the one this plugin ships?

The runner package lives in the user's project (``evals/runner/agent_sdk_evals``)
so CI and local runs need nothing from the plugin at run time. The price is
drift: the plugin moves on, the copy does not. Two files make that visible:

* ``VERSION`` — the runner version the copy was made from.
* ``MANIFEST.sha256`` — one ``<sha256>  <relative path>`` line per shipped file,
  written by `install_runner.py`, so a hand-edited copy can be told apart from a
  stale one.

Findings: ``DEP001`` copy older than the plugin (warn), ``DEP002`` copy newer
than the plugin (error: upgrade the plugin), ``DEP003`` no copy (error: run
`/agent-sdk:agent-create --install-runner`), ``DEP004`` copy modified locally
(warn: an upgrade would overwrite the edits).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import RUNNER_VERSION
from .env import _version_tuple
from .report import Finding

PACKAGE_NAME = "agent_sdk_evals"
VERSION_FILE = "VERSION"
MANIFEST_FILE = "MANIFEST.sha256"


@dataclass
class RunnerCopy:
    """The state of one project's runner copy."""

    runner_dir: str
    package_dir: str | None = None
    present: bool = False
    version: str | None = None
    status: str = "missing"          # missing | older | same | newer | unknown
    manifest_present: bool = False
    modified: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_dir": self.runner_dir,
            "present": self.present,
            "version": self.version,
            "plugin_version": RUNNER_VERSION,
            "status": self.status,
            "manifest_present": self.manifest_present,
            "modified": self.modified,
            "missing_files": self.missing_files,
        }


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(package_dir: Path | str) -> str:
    """The manifest text for a package directory (sorted, stable)."""
    root = Path(package_dir)
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name == MANIFEST_FILE:
            continue
        lines.append(f"{sha256_of(path)}  {path.relative_to(root).as_posix()}")
    return "\n".join(lines) + "\n"


def parse_manifest(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            entries[parts[1].strip()] = parts[0].strip()
    return entries


def inspect_runner_copy(runner_dir: Path | str) -> RunnerCopy:
    root = Path(runner_dir)
    copy = RunnerCopy(runner_dir=str(root))
    package = root / PACKAGE_NAME
    if not package.is_dir():
        return copy
    copy.present = True
    copy.package_dir = str(package)

    version_file = package / VERSION_FILE
    if version_file.is_file():
        copy.version = version_file.read_text(encoding="utf-8").strip() or None
    copy.status = compare_versions(copy.version)

    manifest_file = package / MANIFEST_FILE
    if manifest_file.is_file():
        copy.manifest_present = True
        expected = parse_manifest(manifest_file.read_text(encoding="utf-8"))
        for rel, digest in expected.items():
            target = package / rel
            if not target.is_file():
                copy.missing_files.append(rel)
            elif sha256_of(target) != digest:
                copy.modified.append(rel)
    return copy


def compare_versions(copy_version: str | None, plugin_version: str = RUNNER_VERSION) -> str:
    if not copy_version:
        return "unknown"
    have, want = _version_tuple(copy_version), _version_tuple(plugin_version)
    if have == want:
        return "same"
    return "older" if have < want else "newer"


def findings_for(copy: RunnerCopy, *, path: str | None = None) -> list[Finding]:
    """Turn a copy's state into DEP findings."""
    source = "this plugin's runner_version.py"
    where = path or copy.runner_dir
    out: list[Finding] = []
    if not copy.present:
        out.append(Finding(
            "DEP003", "error", "runner", "no eval runner copy in this project",
            path=where, fix="run `/agent-sdk:agent-create` and choose 'install the runner', "
            "which copies `agent_sdk_evals` into evals/runner/ with a VERSION and MANIFEST",
            source=source,
        ))
        return out
    if copy.status == "older":
        out.append(Finding(
            "DEP001", "warn", "runner",
            f"runner copy is {copy.version}, this plugin ships {RUNNER_VERSION}",
            path=where, fix="run `install_runner.py --upgrade` (a write plan and a diff are shown first)",
            source=source,
        ))
    elif copy.status == "newer":
        out.append(Finding(
            "DEP002", "error", "runner",
            f"runner copy is {copy.version}, newer than this plugin's {RUNNER_VERSION}",
            path=where, fix="update the plugin before touching this project's evals; "
            "the copy may write result files this plugin cannot read", source=source,
        ))
    elif copy.status == "unknown":
        out.append(Finding(
            "DEP001", "warn", "runner", "runner copy has no VERSION file",
            path=where, fix="run `install_runner.py --upgrade` to replace it with a stamped copy",
            source=source,
        ))
    if copy.modified or copy.missing_files:
        detail = ", ".join(copy.modified[:5] + [f"missing {m}" for m in copy.missing_files[:5]])
        out.append(Finding(
            "DEP004", "warn", "runner", f"runner copy differs from its manifest: {detail}",
            path=where, fix="an upgrade would overwrite these edits; move project-specific "
            "graders into evals/graders_local/ (loaded by the runner) before upgrading",
            source=source,
        ))
    return out
