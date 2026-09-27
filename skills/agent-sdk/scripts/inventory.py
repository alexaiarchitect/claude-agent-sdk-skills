#!/usr/bin/env python3
"""Inventory every Agent SDK project under a directory, one row each.

A repository often holds several agents: examples, services, experiments. This
walks the tree, groups agent modules by the nearest directory that looks like
a project root (has `evals/`, `pyproject.toml`, `requirements.txt` or `.git`),
and reports for each: entry style, case count, config, runner-copy status and
whether results exist. Read the table and the next piece of work names itself.

    inventory.py [<root>] [--json] [--max-depth N]

Exit codes: 0, 2 the target is unusable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.layout import SKIP_DIRS, detect_layout, find_agent_modules  # noqa: E402
from agent_sdk_skills.report import EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.runner_version import inspect_runner_copy  # noqa: E402

ROOT_MARKERS = ("evals", "pyproject.toml", "requirements.txt", ".git", "setup.py", "uv.lock")


def project_root_for(module: Path, stop: Path) -> Path:
    for folder in (module.parent, *module.parent.parents):
        if any((folder / marker).exists() for marker in ROOT_MARKERS):
            return folder
        if folder == stop:
            break
    return module.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-depth", type=int, default=6)
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    root = root.resolve()

    projects: dict[Path, list[str]] = {}
    for usage in find_agent_modules(root, max_depth=args.max_depth):
        module = Path(usage.path)
        if set(module.parts) & SKIP_DIRS:
            continue
        projects.setdefault(project_root_for(module, root), []).append(usage.path)

    rows = []
    for project, modules in sorted(projects.items()):
        layout = detect_layout(project)
        copy = inspect_runner_copy(project / "evals" / "runner")
        evals = layout.evals
        rows.append({
            "project": str(project.relative_to(root)) if project != root else ".",
            "style": layout.style,
            "entry": layout.entry_spec,
            "modules": len(modules),
            "legacy_sdk": bool(layout.legacy_modules),
            "cases": evals.case_count if evals else 0,
            "config": bool(evals and evals.config),
            "runner_copy": copy.status,
            "results": len(evals.result_runs) if evals else 0,
            "ci": bool(layout.workflow_files or layout.pytest_gate),
        })

    if args.json:
        print(json.dumps({"root": str(root), "projects": rows}, indent=2))
    else:
        print(f"# inventory: {root}\n")
        if not rows:
            print("no Agent SDK modules found")
        else:
            print("| project | style | entry | cases | config | runner copy | results | ci |")
            print("|---|---|---|---|---|---|---|---|")
            for r in rows:
                print(f"| {r['project']} | {r['style']}{' (legacy sdk)' if r['legacy_sdk'] else ''} | "
                      f"{r['entry'] or '-'} | {r['cases']} | {'yes' if r['config'] else 'no'} | "
                      f"{r['runner_copy']} | {r['results']} | {'yes' if r['ci'] else 'no'} |")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
