#!/usr/bin/env python3
"""Report how the SDK subprocess would authenticate and which interpreter runs it.

An Agent SDK run has two prerequisites the code never mentions: a credential
the bundled `claude` binary will accept, and a Python that can import
`claude_agent_sdk`. Both fail late and cryptically ("Not logged in",
"No module named claude_agent_sdk"), so this script checks them up front and
says what each one means for cost: an API key bills the API, a stored login or
`CLAUDE_CODE_OAUTH_TOKEN` draws on the subscription's usage limits (and the
SDK's `total_cost_usd` becomes an estimate), a provider switch bills that cloud.

    check_env.py <project-dir> [--json] [--no-probe] [--no-cli]

Exit codes: 0 ready to run, 1 blocked (no credential or no interpreter),
2 the target is unusable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import DEFAULT_MODEL, MODEL_ENV_VAR  # noqa: E402
from agent_sdk_skills.env import (  # noqa: E402
    classify_model_id, detect_credential, resolve_runner, version_is_supported,
)
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.sdk_subprocess import describe_runner  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-probe", action="store_true", help="skip importing the SDK in candidates")
    parser.add_argument("--no-cli", action="store_true", help="skip `claude auth status`")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    credential = detect_credential(project, ask_cli=not args.no_cli)
    runner = resolve_runner(project, probe=not args.no_probe)
    model = credential.model_env or DEFAULT_MODEL
    grade = classify_model_id(model)
    blockers: list[str] = []
    if not credential.ready:
        blockers.append("credential: " + credential.describe())
    if not runner.available:
        blockers.append("interpreter: " + (runner.note or "none"))
    if runner.sdk_version and not version_is_supported(runner.sdk_version):
        blockers.append(f"sdk: {runner.sdk_version} is older than this plugin supports")
    if grade == "retired":
        blockers.append(f"model: {model} is retired")

    payload = {
        "project": str(project.resolve()),
        "credential": credential.to_dict(),
        "runner": runner.to_dict(),
        "runner_description": describe_runner(runner),
        "model": {"value": model, "source": MODEL_ENV_VAR if credential.model_env else "plugin default",
                  "grade": grade},
        "ready": not blockers,
        "blockers": blockers,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# check_env: {project}")
        print()
        print(f"- credential: {credential.describe()}")
        print(f"- cost basis: {credential.cost_basis}")
        print(f"- interpreter: {describe_runner(runner)}")
        print(f"- model: {model} ({payload['model']['source']}, {grade})")
        if credential.env_files:
            print(f"- .env files: {', '.join(credential.env_files)} (the SDK does not load these itself)")
        print()
        print("ready" if not blockers else "blocked:\n- " + "\n- ".join(blockers))
    return EXIT_OK if not blockers else EXIT_FINDINGS


if __name__ == "__main__":
    raise SystemExit(main())
