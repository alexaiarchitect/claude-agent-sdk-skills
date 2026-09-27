#!/usr/bin/env python3
"""Generate the two-tier GitHub Actions eval gate for a Claude Agent SDK project.

One workflow cannot be both cheap enough to run on every pull request and
thorough enough to trust for a release, so this writes two:

* **pr** — the free graders, one run per case, `--concurrency 1`, a cost ceiling
  and a cancel-superseded-runs concurrency group. Seconds of model time, and it
  catches the failures that matter most: a tool that stopped being called, a
  refusal that stopped happening, a schema that drifted.
* **nightly** — judge graders and `--runs N`, on a cron plus manual dispatch, so
  reliability has a number attached. It costs quota or money per case per run,
  which is exactly why it is not on the pull-request path.

Both run the runner copy committed in the project (`evals/runner/agent_sdk_evals`)
as a plain step, so the step's exit code is the verdict and no agent decides what
to run. Both treat exit 3 (inconclusive) as neutral rather than as a regression:
see `references/workflows.md`, and the comments in the generated files.

The credential is a repository secret, never a literal:
`CLAUDE_CODE_OAUTH_TOKEN` by default, with the `ANTHROPIC_API_KEY` line written
in commented out; `--auth api-key` writes the reverse. An OAuth token from
`claude setup-token` is tied to one person's Claude plan, which suits a personal
repository and not an organization-wide secret.

    gen_workflows.py <project> [--tier pr|nightly|both] [--auth oauth|api-key]
                     [--python 3.12] [--runs N] [--max-cost-usd X] [--cron EXPR]
                     [--timeout-minutes N] [--out-dir .github/workflows]
                     [--pytest-gate] [--readme] [--force] [--dry-run] [--json]

Nothing is written until the plan says so: `--dry-run` prints the write plan and
touches nothing, an existing file is skipped unless `--force` is passed.

Exit codes: 0 planned or written, 1 written with warnings the user must act on
(no runner copy, no cases, judge graders in the pr tier), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import DEFAULT_MODEL  # noqa: E402
from agent_sdk_skills.eval_config import load_config, tier_graders  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.runner_version import inspect_runner_copy  # noqa: E402
from agent_sdk_skills.templating import WritePlan, render_file  # noqa: E402

TEMPLATES = Path(__file__).resolve().parents[1] / "assets" / "templates"

#: The credential block, indented for a step's `env:` mapping. Exactly one line
#: is active; the other is written commented so switching is a two-line edit.
OAUTH_ENV = """          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          # ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}   # API billing instead of plan quota"""

API_KEY_ENV = """          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}   # a subscription plan instead of API billing"""

PIP_CACHE_LINE = "          cache: pip"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--tier", choices=("pr", "nightly", "both"), default="both")
    parser.add_argument("--auth", choices=("oauth", "api-key"), default="oauth",
                        help="oauth: CLAUDE_CODE_OAUTH_TOKEN active (default)")
    parser.add_argument("--python", default="3.12", help="python-version for setup-python")
    parser.add_argument("--runs", type=int, default=3, help="runs per case in the nightly tier")
    parser.add_argument("--max-cost-usd", type=float, default=5.0,
                        help="pr-tier ceiling; the nightly tier gets runs x this")
    parser.add_argument("--cron", default="0 3 * * *")
    parser.add_argument("--timeout-minutes", type=int, default=30)
    parser.add_argument("--out-dir", default=".github/workflows")
    parser.add_argument("--pytest-gate", action="store_true",
                        help="also write tests/test_evals.py, for a project that runs pytest in CI")
    parser.add_argument("--readme", action="store_true",
                        help="also write docs/ci-evals.md, a README section on the secret and the gate")
    parser.add_argument("--force", action="store_true", help="replace files that already exist")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(target)
    if not layout.project_root:
        print(f"error: {target} is not a project directory", file=sys.stderr)
        return EXIT_USAGE
    project = Path(layout.project_root)

    warnings: list[str] = []
    cases = layout.evals.case_count if layout.evals else 0
    if cases == 0:
        warnings.append(
            "no eval cases under evals/: the workflow will run and find nothing to score. "
            "Write cases with /agent-sdk:eval-create before relying on the gate.")

    copy = inspect_runner_copy(project / "evals" / "runner")
    if not copy.present:
        warnings.append(
            "no runner copy under evals/runner/agent_sdk_evals: the step will fail at "
            "`import agent_sdk_evals`. Install one with /agent-sdk:agent-create.")

    config = load_config(project / "evals" / "eval_config.json")
    if config.ok and "judge" in tier_graders(config, "pr"):
        warnings.append(
            "the pr tier in evals/eval_config.json lists `judge` graders, so the "
            "per-pull-request job will pay for judge calls. Move them to the nightly tier "
            "(/agent-sdk:eval-criteria).")

    requirements = [name for name in layout.requirements if name.startswith("requirements")]
    if requirements:
        install = f"python -m pip install -r {requirements[0]}"
        pip_cache = PIP_CACHE_LINE
    elif "pyproject.toml" in layout.requirements:
        install = "python -m pip install ."
        pip_cache = ""
        warnings.append(
            "no requirements.txt: the workflow installs the project itself "
            "(`pip install .`). Check that it declares claude-agent-sdk.")
    else:
        install = "python -m pip install claude-agent-sdk"
        pip_cache = ""
        warnings.append(
            "no requirements file: the workflow installs `claude-agent-sdk` unpinned. "
            "Pin it in a requirements.txt so the gate does not change behaviour on its own.")

    mapping = {
        "PROJECT_NAME": project.name,
        "PYTHON_VERSION": args.python,
        "PIP_CACHE": pip_cache,
        "INSTALL_COMMAND": install,
        "CREDENTIAL_ENV": OAUTH_ENV if args.auth == "oauth" else API_KEY_ENV,
        "MODEL": DEFAULT_MODEL,
        "MAX_COST": _money(args.max_cost_usd),
        "NIGHTLY_MAX_COST": _money(args.max_cost_usd * max(args.runs, 1)),
        "TIMEOUT_MINUTES": str(args.timeout_minutes),
        "NIGHTLY_TIMEOUT_MINUTES": str(args.timeout_minutes * max(args.runs, 1)),
        "RUNS": str(args.runs),
        "CRON": args.cron,
        "TIER": "pr",
    }

    out_dir = project / args.out_dir
    plan = WritePlan()
    if args.tier in ("pr", "both"):
        plan.add(out_dir / "agent-evals-pr.yml",
                 render_file(TEMPLATES / "workflows" / "agent-evals-pr.yml.tmpl", mapping),
                 force=args.force)
    if args.tier in ("nightly", "both"):
        plan.add(out_dir / "agent-evals-nightly.yml",
                 render_file(TEMPLATES / "workflows" / "agent-evals-nightly.yml.tmpl", mapping),
                 force=args.force)
    if args.pytest_gate:
        plan.add(project / "tests" / "test_evals.py",
                 render_file(TEMPLATES / "test_evals.py.tmpl", mapping), force=args.force)
    if args.readme:
        plan.add(project / "docs" / "ci-evals.md",
                 render_file(TEMPLATES / "ci-readme.md.tmpl", mapping), force=args.force)

    secret = "CLAUDE_CODE_OAUTH_TOKEN" if args.auth == "oauth" else "ANTHROPIC_API_KEY"
    setup = [
        f"add the {secret} repository secret"
        + (" (mint it with `claude setup-token`; it is tied to your own Claude plan)"
           if args.auth == "oauth" else " (a key from the Claude Console; it bills the API)"),
        "commit evals/results/ to .gitignore; the workflows upload it as an artifact instead",
        f"the gate calls `python -m agent_sdk_evals` with PYTHONPATH=evals/runner:. — "
        f"the runner copy must be committed under evals/runner/",
    ]

    written = [] if args.dry_run else plan.apply()
    payload = {
        "project": str(project),
        "tier": args.tier,
        "auth": args.auth,
        "secret": secret,
        "cases": cases,
        "runner_copy": {"present": copy.present, "version": copy.version},
        "install_command": install,
        "dry_run": args.dry_run,
        "write_plan": plan.to_dict(),
        "written": written,
        "warnings": warnings,
        "setup": setup,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# eval-ci: workflows for {project.name}"
              + (" (dry run, nothing written)" if args.dry_run else ""))
        print()
        print(plan.to_md())
        print()
        print(f"- credential: `${{{{ secrets.{secret} }}}}` "
              f"({'subscription plan quota' if args.auth == 'oauth' else 'API billing'})")
        print(f"- install step: `{install}`")
        print(f"- pr ceiling: --max-cost-usd {mapping['MAX_COST']}; "
              f"nightly: --runs {args.runs} --max-cost-usd {mapping['NIGHTLY_MAX_COST']}")
        for path in written:
            print(f"- wrote {path}")
        if warnings:
            print()
            print("Before this gate means anything:")
            for warning in warnings:
                print(f"  - {warning}")
        print()
        print("Repository setup:")
        for step in setup:
            print(f"  - {step}")
        print()
        print("Then check what was written: "
              "`python3 ${CLAUDE_SKILL_DIR}/scripts/lint_workflows.py <project>`")

    return EXIT_FINDINGS if warnings else EXIT_OK


def _money(value: float) -> str:
    """A ceiling reads better as `5` than as `5.0`, and must stay a valid float."""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


if __name__ == "__main__":
    raise SystemExit(main())
