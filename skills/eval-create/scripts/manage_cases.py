#!/usr/bin/env python3
"""List, rename, delete and de-duplicate the cases in a suite.

A suite is a directory of directories, so the maintenance operations are all
file moves — which is exactly why they go through a script rather than through
`mv`. Three things are easy to get wrong by hand:

* **A case's identity is its `name`, not its directory.** Result files are keyed
  by name, so renaming the directory and leaving `name:` in the frontmatter
  produces two cases that look different and overwrite each other's results.
  `rename` changes both.
* **Deleting a case deletes evidence.** A case is the record that someone once
  decided this behaviour mattered. `delete` and `rename` refuse without
  `--yes`, and print what they would do instead.
* **Duplicates hide behind different names.** Two cases with the same prompt
  body cost twice as much per run and prove one thing. `dedupe` finds them by
  comparing normalized prompt bodies — not names, not graders.

`dedupe` reports by default and removes only with `--yes`, keeping the first
case of each group in directory order. It never merges graders: if the
duplicates assert different things, the answer is one case with both graders,
and that is an edit a person should make.

    manage_cases.py <project> list|rename|delete|dedupe
                    [--from A] [--to B] [--yes] [--dry-run] [--json]

Exit codes: 0 done or nothing to do, 1 refused (no `--yes`) or duplicates
found, 2 usage error (unknown case, missing flag).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.evalcase import case_summary, iter_cases, load_case  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402

#: Case-directory names are lowercase and hyphenated, so a `-k` selection in
#: pytest and a `--case` flag on the runner behave the same on every shell.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _normalized_body(text: str) -> str:
    """Whitespace-insensitive, case-insensitive prompt body.

    Two cases whose prompts differ only in line wrapping are the same case; two
    that differ in one word are not, and this deliberately does not try to
    decide which. Fuzzy matching here would delete cases people meant to keep.
    """
    return " ".join((text or "").split()).strip().lower()


def _find(evals: Path, name: str) -> Path | None:
    direct = evals / name
    if (direct / "prompt.md").is_file():
        return direct
    for case in iter_cases(evals):
        if case.name == name:
            return Path(case.dir)
    return None


def cmd_list(evals: Path) -> tuple[dict, int]:
    rows = [case_summary(case) for case in iter_cases(evals)]
    by_category: dict[str, int] = {}
    for row in rows:
        by_category[row["category"] or "(none)"] = by_category.get(row["category"] or "(none)", 0) + 1
    return {"cases": rows, "count": len(rows), "by_category": dict(sorted(by_category.items()))}, EXIT_OK


def cmd_rename(evals: Path, old: str, new: str, *, yes: bool, dry_run: bool) -> tuple[dict, int]:
    source = _find(evals, old)
    if source is None:
        return {"error": f"no case {old!r} under {evals}"}, EXIT_USAGE
    if not NAME_RE.match(new):
        return {"error": f"{new!r} is not a usable directory name: lowercase letters, digits, "
                         "'.', '-' and '_', starting with a letter or digit"}, EXIT_USAGE
    target = evals / new
    if target.exists():
        return {"error": f"{target} already exists"}, EXIT_USAGE

    prompt = source / "prompt.md"
    text = prompt.read_text(encoding="utf-8")
    updated = re.sub(r"(?m)^name:\s*.*$", f"name: {new}", text, count=1)
    if updated == text and "name:" not in text.split("---")[1 if text.startswith("---") else 0]:
        updated = text            # no `name:` key: the directory name is the identity

    plan = {"move": [str(source), str(target)],
            "frontmatter_name": new,
            "note": "result files are keyed by `name`, so the frontmatter moves with the directory"}
    if not yes:
        return {"refused": "pass --yes to rename; a case is a record someone made deliberately",
                "plan": plan}, EXIT_FINDINGS
    if not dry_run:
        prompt.write_text(updated, encoding="utf-8")
        source.rename(target)
    return {"renamed": plan, "dry_run": dry_run}, EXIT_OK


def cmd_delete(evals: Path, name: str, *, yes: bool, dry_run: bool) -> tuple[dict, int]:
    source = _find(evals, name)
    if source is None:
        return {"error": f"no case {name!r} under {evals}"}, EXIT_USAGE
    case = load_case(source)
    plan = {"remove": str(source),
            "graders": [Path(g.path).name for g in case.graders],
            "note": "deleting a case deletes the only record that this behaviour was ever "
                    "checked; prefer moving it to a `regression` category over removing it"}
    if not yes:
        return {"refused": "pass --yes to delete", "plan": plan}, EXIT_FINDINGS
    if not dry_run:
        shutil.rmtree(source)
    return {"deleted": plan, "dry_run": dry_run}, EXIT_OK


def cmd_dedupe(evals: Path, *, yes: bool, dry_run: bool) -> tuple[dict, int]:
    groups: dict[str, list[dict]] = {}
    for case in iter_cases(evals):
        body = _normalized_body(case.body) or _normalized_body(" ".join(case.turns))
        if not body:
            continue
        groups.setdefault(body, []).append(
            {"name": case.name, "dir": case.dir,
             "graders": sorted({g.type for g in case.graders if g.type})})
    duplicates = [members for members in groups.values() if len(members) > 1]
    if not duplicates:
        return {"duplicates": [], "note": "no two cases share a prompt body"}, EXIT_OK

    removals: list[str] = []
    for members in duplicates:
        removals.extend(m["dir"] for m in members[1:])
    payload = {
        "duplicates": [{"keep": members[0], "remove": members[1:]} for members in duplicates],
        "would_remove": removals,
        "note": "graders are NOT merged. If the duplicates assert different things, keep one "
                "case and move the other's graders into it by hand before removing anything.",
    }
    if not yes:
        payload["refused"] = "pass --yes to remove the duplicates (the first of each group is kept)"
        return payload, EXIT_FINDINGS
    if not dry_run:
        for path in removals:
            shutil.rmtree(path)
    payload["removed"] = removals
    payload["dry_run"] = dry_run
    return payload, EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("command", choices=("list", "rename", "delete", "dedupe"))
    parser.add_argument("--from", dest="source", help="the case to rename or delete")
    parser.add_argument("--to", dest="target", help="the new name, for rename")
    parser.add_argument("--yes", action="store_true", help="confirm a destructive operation")
    parser.add_argument("--dry-run", action="store_true", help="say what would happen, change nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    evals = project / "evals"
    if not evals.is_dir():
        print(f"error: no evals/ directory under {project}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "list":
        payload, code = cmd_list(evals)
    elif args.command == "rename":
        if not args.source or not args.target:
            print("error: rename needs --from and --to", file=sys.stderr)
            return EXIT_USAGE
        payload, code = cmd_rename(evals, args.source, args.target,
                                   yes=args.yes, dry_run=args.dry_run)
    elif args.command == "delete":
        if not args.source:
            print("error: delete needs --from", file=sys.stderr)
            return EXIT_USAGE
        payload, code = cmd_delete(evals, args.source, yes=args.yes, dry_run=args.dry_run)
    else:
        payload, code = cmd_dedupe(evals, yes=args.yes, dry_run=args.dry_run)

    payload = {"project": str(project), "command": args.command, **payload}
    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.command == "list":
        print(f"# cases in {evals} ({payload['count']})\n")
        print("| case | category | graders | tier | runs | ok |")
        print("|---|---|---|---|---|---|")
        for row in payload["cases"]:
            print(f"| `{row['name']}` | {row['category'] or '—'} | "
                  f"{', '.join(row['grader_types']) or '—'} | {row['tier']} | "
                  f"{row['runs'] or '—'} | {'yes' if row['ok'] else 'NO'} |")
        print()
        print("by category: " + ", ".join(f"{k}={v}" for k, v in payload["by_category"].items()))
    else:
        print(f"# manage_cases {args.command}: {project}\n")
        print(json.dumps({k: v for k, v in payload.items()
                          if k not in ("project", "command")}, indent=2))
    if "error" in payload:
        print(f"error: {payload['error']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
