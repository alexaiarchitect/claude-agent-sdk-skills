#!/usr/bin/env python3
"""Write a Dockerfile for an Agent SDK agent that will not leak or surprise you.

The image is the easiest place to get hosting wrong, because everything wrong
about it is invisible once it is built: a key in a layer stays in the layer, a
copied `.env` stays in the history, a root user stays root.

What this generates, and why each line is there:

* `python:3.12-slim` — the SDK needs Python 3.10+, and both SDKs bundle a
  native Claude Code binary, so the container needs no separate Node.js;
* a **non-root user** with a writable `/work` volume, because the subprocess
  owns a shell and a working directory;
* `pip install claude-agent-sdk` from `requirements.txt` — the bundled CLI is
  pinned to the package version, so updating the SDK is how you update the CLI;
* **no credential of any kind**, and `.env` never copied. An
  `ANTHROPIC_BASE_URL` line points at a gateway that injects the key outside
  the container;
* `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and a per-tenant `CLAUDE_CONFIG_DIR`,
  because auto memory loads into the system prompt regardless of
  `setting_sources`;
* the OpenTelemetry variables, **commented**, so turning telemetry on is one
  uncomment and not a research project;
* a healthcheck hint — the CLI subprocess does not listen on the network, so
  the check has to be your application's, not the agent's.

    gen_dockerfile.py [--python 3.12] [--entry agent.py] [--out path]
                      [--dry-run] [--force] [--json]

Exit codes: 0 written (or planned, under --dry-run), 1 nothing to write,
2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import SDK_MIN_SUPPORTED  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan  # noqa: E402

SUPPORTED_PYTHON = ("3.10", "3.11", "3.12", "3.13")

DOCKERFILE = """# Claude Agent SDK agent.
#
# No credential is baked in. The subprocess reads ANTHROPIC_API_KEY from its
# environment at run time; supply it from your secret manager, or point
# ANTHROPIC_BASE_URL at a gateway that injects the key after the request leaves
# this container. Hosted and multi-tenant agents must not use a claude.ai
# subscription credential.
FROM python:{python}-slim

# The subprocess owns a shell and a working directory, so it does not run as root.
RUN useradd --create-home --uid 10001 agent
WORKDIR /app

# Dependencies first, so a code change does not reinstall the SDK. The bundled
# Claude Code binary is pinned to the package version: updating the SDK updates
# the CLI.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Only what the image needs. Never copy the whole build context while a
# .env file exists: a layer that held it still holds it.
COPY {entry} ./

# Isolation. setting_sources=[] belongs in the options object; these two cover
# what that option does not: auto memory loads into the system prompt whatever
# setting_sources says, and ~/.claude.json is read regardless.
ENV CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \\
    CLAUDE_CONFIG_DIR=/work/.claude \\
    AGENT_WORK_ROOT=/work \\
    PYTHONUNBUFFERED=1

# Pin the model: with none set, a session starts on Claude Code's default,
# which can change under you and is not the cheapest one.
ENV CLAUDE_MODEL=claude-sonnet-5-5

# Credentials arrive at run time, never in a layer. Uncomment the gateway line
# if a proxy injects the key outside this container.
# ENV ANTHROPIC_BASE_URL=http://claude-gateway.internal:8080

# Telemetry. Off until CLAUDE_CODE_ENABLE_TELEMETRY=1; the exporters alone do
# nothing. Traces additionally need the beta flag.
# ENV CLAUDE_CODE_ENABLE_TELEMETRY=1 \\
#     CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1 \\
#     OTEL_TRACES_EXPORTER=otlp \\
#     OTEL_METRICS_EXPORTER=otlp \\
#     OTEL_LOGS_EXPORTER=otlp \\
#     OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \\
#     OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.internal:4318
# Leave OTEL_LOG_USER_PROMPTS, OTEL_LOG_TOOL_DETAILS, OTEL_LOG_TOOL_CONTENT and
# OTEL_LOG_RAW_API_BODIES unset unless your pipeline is approved to store the
# data this agent handles.

# One session is one subprocess with its own working directory. Size the host
# for concurrency: about 1 GiB RAM, 5 GiB disk and 1 CPU per agent is a floor,
# not a ceiling, and memory grows with session length.
RUN mkdir -p /work && chown -R agent:agent /work /app
USER agent
VOLUME ["/work"]

# The CLI subprocess does not listen on the network, so a healthcheck has to
# exercise your application. Replace this import check with a real endpoint
# once the container serves one.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \\
  CMD python3 -c "import {module}; print('ok')" || exit 1

CMD ["python3", "{entry}"]
"""

DOCKERIGNORE = """.env
.env.*
!.env.example
.git
.venv
venv
__pycache__
*.pyc
.pytest_cache
evals/results
"""

REQUIREMENTS = """claude-agent-sdk>={minimum}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="where to write")
    parser.add_argument("--python", default="3.12", choices=SUPPORTED_PYTHON,
                        help="base image tag (the SDK needs 3.10+)")
    parser.add_argument("--entry", default="agent.py", help="the module the image runs")
    parser.add_argument("--out", help="Dockerfile path (default: <project>/Dockerfile)")
    parser.add_argument("--no-dockerignore", action="store_true",
                        help="do not also write .dockerignore (which is what keeps .env out)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the write plan and the file; write nothing")
    parser.add_argument("--force", action="store_true", help="replace existing files")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args(argv)

    root = Path(args.project).expanduser()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    if not args.entry.endswith(".py"):
        print(f"error: --entry should be a Python file, got {args.entry!r}", file=sys.stderr)
        return EXIT_USAGE

    content = DOCKERFILE.format(
        python=args.python, entry=args.entry, module=Path(args.entry).stem,
    )
    out = Path(args.out) if args.out else root / "Dockerfile"

    plan = WritePlan()
    plan.add(out, content, force=args.force,
             reason=f"python:{args.python}-slim, non-root, no credentials, auto memory off")
    if not args.no_dockerignore:
        plan.add(root / ".dockerignore", DOCKERIGNORE, force=args.force,
                 reason="keeps .env, .git and results out of the build context")
    if not (root / "requirements.txt").is_file():
        plan.add(root / "requirements.txt",
                 REQUIREMENTS.format(minimum=SDK_MIN_SUPPORTED), force=args.force,
                 reason="the Dockerfile installs from it")

    payload = {
        "python": args.python, "entry": args.entry, "out": str(out),
        "dry_run": args.dry_run, "plan": plan.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(plan.to_md())
        print()
        if args.dry_run:
            print("--- Dockerfile (not written) ---")
            print(content)
    if args.dry_run:
        return EXIT_OK

    written = plan.apply()
    if not written:
        if not args.json:
            print("nothing written; pass --force to replace existing files")
        return EXIT_FINDINGS
    if not args.json:
        for path in written:
            print(f"wrote {path}")
        print("Supply the credential at run time. Check the result with "
              "deploy_check.py before you build.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
