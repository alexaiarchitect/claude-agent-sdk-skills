#!/usr/bin/env python3
"""Copy the eval runner into the project, or upgrade the copy that is there.

The runner is a package, not a service: `agent_sdk_evals` is copied verbatim
into `<project>/evals/runner/` and committed. CI then needs nothing from this
plugin — a workflow step runs `python -m agent_sdk_evals` with the project's
own interpreter, and a result produced six months from now is reproducible
because the code that produced it is in the repository.

The price of a copy is drift, so every install writes `MANIFEST.sha256` beside
the package's `VERSION`. That is what lets `check_runner.py` tell "older than
the plugin" (DEP001) from "someone edited it here" (DEP004) — and DEP004 is the
one that matters, because an upgrade would silently throw those edits away.
So an upgrade prints the diff first: files added, changed, removed, and locally
modified files that would be overwritten.

    install_runner.py <project> [--upgrade] [--dry-run] [--json]

Without `--upgrade`, an existing copy is refused rather than replaced.

Exit codes: 0 installed, upgraded or planned; 1 refused (a copy exists and
--upgrade was not passed, or local edits would be lost); 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import RUNNER_VERSION  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.runner_version import (  # noqa: E402
    MANIFEST_FILE, PACKAGE_NAME, build_manifest, inspect_runner_copy, sha256_of,
)
from agent_sdk_skills.templating import WriteItem, WritePlan  # noqa: E402

#: The package this plugin ships, one directory above `skills/`.
SOURCE = Path(__file__).resolve().parents[3] / "runner" / PACKAGE_NAME


def _source_files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.name != MANIFEST_FILE
    }


def _destination_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.name != MANIFEST_FILE
    }


def build_plan(source: Path, package: Path, *, upgrade: bool) -> tuple[WritePlan, dict]:
    """The write plan plus the diff summary an upgrade has to show first."""
    wanted = _source_files(source)
    present = _destination_files(package)

    added = sorted(set(wanted) - set(present))
    removed = sorted(set(present) - set(wanted))
    changed = sorted(
        rel for rel in set(wanted) & set(present)
        if sha256_of(wanted[rel]) != sha256_of(present[rel])
    )
    copy = inspect_runner_copy(package.parent)
    #: Files the manifest says were edited in place *and* that this install
    #: would write over. Anything else the user changed stays changed.
    clobbered = sorted(set(copy.modified) & set(changed))

    plan = WritePlan()
    for rel in sorted(wanted):
        target = package / rel
        content = wanted[rel].read_text(encoding="utf-8")
        if rel in changed:
            plan.items.append(WriteItem(
                str(target), content, action="overwrite" if upgrade else "skip",
                reason=("locally modified — this upgrade replaces your edits"
                        if rel in clobbered else "changed in this runner version")
                if upgrade else "a copy exists; pass --upgrade"))
        elif rel in added:
            plan.items.append(WriteItem(str(target), content, action="create",
                                        reason="new in this runner version" if present else None))
        # An identical file needs no write and does not belong in the plan.
    for rel in removed:
        plan.block(str(package / rel),
                   "removed from this runner version; delete it by hand after the upgrade, "
                   "or keep it if it is yours")

    summary = {
        "source": str(source),
        "package": str(package),
        "plugin_version": RUNNER_VERSION,
        "copy_version": copy.version,
        "copy_status": copy.status,
        "files": {"total": len(wanted), "added": added, "changed": changed, "removed": removed},
        "locally_modified": copy.modified,
        "would_overwrite_local_edits": clobbered,
    }
    return plan, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--upgrade", action="store_true",
                        help="replace an existing copy, after showing the diff")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    if not SOURCE.is_dir():                  # pragma: no cover - ships with the plugin
        print(f"error: this plugin has no runner package at {SOURCE}", file=sys.stderr)
        return EXIT_USAGE

    runner_dir = project / "evals" / "runner"
    package = runner_dir / PACKAGE_NAME
    existed = package.is_dir()
    if existed and not args.upgrade:
        copy = inspect_runner_copy(runner_dir)
        relation = {"same": "the same version as", "older": "older than",
                    "newer": "newer than"}.get(copy.status, "an unknown version beside")
        message = (f"a runner copy is already installed ({copy.version or 'no VERSION file'}, "
                   f"{relation} the plugin's {RUNNER_VERSION})")
        payload = {"refused": True, "reason": message, "copy": copy.to_dict(),
                   "fix": "pass --upgrade to replace it; the diff is printed before anything "
                          "is written"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"# install_runner: {project}\n\n- refused: {message}")
            if copy.modified:
                print(f"- locally modified: {', '.join(copy.modified)}")
            print(f"- {payload['fix']}")
        return EXIT_FINDINGS

    plan, summary = build_plan(SOURCE, package, upgrade=args.upgrade or not existed)
    manifest_path = package / MANIFEST_FILE

    written: list[str] = []
    if not args.dry_run:
        written = plan.apply()
        manifest_path.write_text(build_manifest(package), encoding="utf-8")
        written.append(str(manifest_path))
    summary.update({
        "installed": bool(written),
        "upgraded": existed,
        "dry_run": args.dry_run,
        "plan": plan.to_dict(),
        "written": len(written),
        "manifest": str(manifest_path),
    })

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        verb = "upgrade" if existed else "install"
        print(f"# install_runner ({verb}): {project}\n")
        print(f"- from: `{SOURCE}` (version {RUNNER_VERSION})")
        print(f"- to:   `{package}`")
        if existed:
            print(f"- copy version: {summary['copy_version']} ({summary['copy_status']})")
        files = summary["files"]
        print(f"- files: {len(files['added'])} added, {len(files['changed'])} changed, "
              f"{len(files['removed'])} removed, {files['total']} total")
        for rel in files["removed"]:
            print(f"  - removed upstream: `{rel}`")
        if summary["would_overwrite_local_edits"]:
            print("- **local edits that this upgrade replaces (DEP004):** "
                  + ", ".join(f"`{r}`" for r in summary["would_overwrite_local_edits"]))
        print()
        print(plan.to_md())
        if args.dry_run:
            print("\n_Dry run: nothing was written._")
        else:
            print(f"\n_Wrote {len(written)} file(s), including {MANIFEST_FILE}._")
            print("\nNext: `../eval-run/scripts/check_runner.py <project>` should report `same`.")

    if summary["would_overwrite_local_edits"] and not args.dry_run:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
