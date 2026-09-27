#!/usr/bin/env python3
"""Check whether an agent is ready to be hosted, rather than run on a laptop.

Hosting an Agent SDK agent is not deployment as usual, because `query()` spawns
a `claude` subprocess that owns a shell, a working directory and a transcript on
local disk. Four things follow, and they are what this checks:

* **the credential.** Anthropic's own note: "Unless previously approved,
  Anthropic does not allow third party developers to offer claude.ai login or
  rate limits for their products, including agents built on the Claude Agent
  SDK." A subscription token in a container that serves other people is a
  policy problem, not a configuration preference. Use an API key, an
  `ANTHROPIC_BASE_URL` gateway that injects one outside the container, or a
  cloud provider.
* **the ceilings.** Claude decides when to spawn subagents; one prompt can grow
  into a tree, and every request counts toward the query's cost.
* **the isolation.** Default SDK behaviour reads settings and `CLAUDE.md` from
  the filesystem, so in a shared container one tenant's context reaches another
  tenant's session.
* **the evidence.** Long-lived processes making many round trips are opaque
  without telemetry.

Findings are the `HST0xx` band, defined by this script. Report only.

    deploy_check.py <project> [--target docker|k8s|ci] [--format json|md] [--json]

Exit codes: 0 no errors, 1 errors, 2 nothing to check.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.env import read_dotenv  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.options_ast import extract_project  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport, Option,
)

DOCS = "https://code.claude.com/docs/en/agent-sdk"
SRC_HOSTING = f"{DOCS}/hosting"
SRC_ISOLATION = f"{DOCS}/hosting#multi-tenant-isolation"
SRC_SECURE = f"{DOCS}/secure-deployment#credential-management"
SRC_POLICY = f"{DOCS}/quickstart"
SRC_COSTS = f"{DOCS}/subagents#cap-subagent-depth-concurrency-and-spend"
SRC_OBSERVABILITY = f"{DOCS}/observability"
SRC_SESSION_STORE = f"{DOCS}/session-storage"

#: Files that describe a container or a deployment.
CONTAINER_FILES = ("Dockerfile", "Containerfile", "docker-compose.yml",
                   "docker-compose.yaml", "compose.yml", "compose.yaml")
#: Credentials that bill an API account or a provider: fine for a hosted agent.
API_CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                   "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                   "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS")
#: A subscription credential: personal use only.
SUBSCRIPTION_CREDENTIALS = ("CLAUDE_CODE_OAUTH_TOKEN",)

SECRET_LITERAL = re.compile(
    r"(?:ANTHROPIC_API_KEY|CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_AUTH_TOKEN|AWS_SECRET_ACCESS_KEY)"
    r"\s*[=:]\s*[\"']?(?!\$|\s*$|\"\"|''|<)([^\s\"'#]{8,})"
)
SK_ANT = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")


def _copy_targets(text: str):
    """Yield the source arguments of every COPY/ADD instruction, line by line.

    Line by line, because a regular expression over the whole file happily
    matches a `COPY` on one line against a `.env` mentioned in a comment three
    lines later — which is exactly the false positive this check must not have.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        head, _, rest = stripped.partition(" ")
        if head.upper() not in ("COPY", "ADD") or not rest:
            continue
        yield [token for token in rest.split() if not token.startswith("--")]


def copies_dotenv(text: str) -> bool:
    return any(
        token == ".env" or token.startswith(".env.")
        for tokens in _copy_targets(text) for token in tokens[:-1] or tokens
    )


def copies_everything(text: str) -> bool:
    return any(tokens and tokens[0] in (".", "./") for tokens in _copy_targets(text))


OTEL_VARS = ("OTEL_TRACES_EXPORTER", "OTEL_METRICS_EXPORTER", "OTEL_LOGS_EXPORTER",
             "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_PROTOCOL")


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="project root")
    parser.add_argument("--target", choices=("docker", "k8s", "ci"), default="docker",
                        help="what it is being deployed to; changes the advice, not the rules")
    parser.add_argument("--format", choices=("json", "md"), default="md")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        help="print the gap report as JSON instead of markdown")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(target)
    root = Path(layout.project_root or target)
    facts = extract_project(root)
    if not facts.modules:
        print(f"error: no Claude Agent SDK usage under {target}", file=sys.stderr)
        return EXIT_USAGE

    report = GapReport(subject=str(root), skill="agent-deploy")
    primary = facts.primary

    container_files = [root / name for name in CONTAINER_FILES if (root / name).is_file()]
    container_text = {path.name: read(path) for path in container_files}

    env_files = {Path(p).name: read_dotenv(p) for p in layout.env_files}
    example_files = {Path(p).name: read_dotenv(p) for p in layout.example_files}
    declared_env: dict[str, str] = {}
    for values in (*example_files.values(), *env_files.values()):
        declared_env.update({k: v for k, v in values.items() if v})

    options_env = {}
    if primary is not None and primary.has("env"):
        options_env = primary.get("env").as_dict()

    def env_mentions(name: str) -> bool:
        return (name in declared_env or name in options_env
                or any(name in text for text in container_text.values()))

    hosted = bool(container_files) or args.target in ("k8s",)

    # -- HST001 / HST002: the credential --------------------------------
    subscription = [name for name in SUBSCRIPTION_CREDENTIALS if env_mentions(name)]
    api = [name for name in API_CREDENTIALS if env_mentions(name)]
    if hosted and subscription:
        report.add("HST001", "error", "credentials",
                   f"a subscription credential ({', '.join(subscription)}) is configured "
                   "for a container image",
                   path=str(root),
                   fix="Anthropic does not allow third-party developers to offer claude.ai "
                       "login or rate limits for their products, including agents built on "
                       "the Agent SDK, unless previously approved. Use ANTHROPIC_API_KEY, "
                       "an ANTHROPIC_BASE_URL gateway that injects the key outside the "
                       "container, or a cloud provider. An OAuth token is also tied to one "
                       "person's plan and expires.",
                   source=SRC_POLICY)
    if hosted and not api and not subscription:
        report.add("HST002", "error", "credentials",
                   "no credential path for the container: nothing sets an API key, a "
                   "gateway base URL, or a provider switch",
                   path=str(root),
                   fix="the subprocess reads ANTHROPIC_API_KEY from its environment. "
                       "Supply it from a secret manager at run time, or set "
                       "ANTHROPIC_BASE_URL to a proxy that adds the key after the request "
                       "leaves the container.",
                   source=SRC_SECURE)

    # -- HST010 / HST011 / HST012: ceilings ------------------------------
    if primary is not None:
        if not primary.has("max_turns"):
            report.add("HST010", "warn", "cost",
                       "no max_turns: a hosted session has no turn ceiling",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="a container that serves other people needs a bound it cannot "
                           "talk its way past.",
                       source=SRC_COSTS)
        if not primary.has("max_budget_usd"):
            report.add("HST011", "warn", "cost",
                       "no max_budget_usd: nothing caps what one request can spend",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="the cap counts subagent requests too, refuses to spawn more "
                           "subagents at the limit, stops background ones, and ends the "
                           "query with subtype error_max_budget_usd. Token cost dominates "
                           "container cost by an order of magnitude or more.",
                       source=SRC_COSTS)
        if facts.agents and not (
            env_mentions("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH")
            or env_mentions("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS")
        ):
            report.add("HST012", "info", "cost",
                       f"{len(facts.agents)} subagent(s) are defined and neither the depth "
                       "nor the concurrency cap is set",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="defaults are 3 layers of nesting and 20 concurrent subagents. "
                           "Set CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH and "
                           "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS in the `env` option; in "
                           "Python `env` merges into the inherited environment.",
                       source=SRC_COSTS)

    # -- HST020 / HST021 / HST022: isolation -----------------------------
    if primary is not None:
        sources_value = primary.get("setting_sources")
        isolated = bool(sources_value and sources_value.is_known and sources_value.value == [])
        if hosted and not isolated:
            report.add("HST020", "warn", "isolation",
                       "setting_sources is not [] for an agent that runs in a container",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="default behaviour reads settings and CLAUDE.md from the "
                           "filesystem, so in a shared container one tenant's context can "
                           "reach another tenant's session — and on a fresh host the run "
                           "behaves differently from the one you tested.",
                       source=SRC_ISOLATION)
        if hosted and not env_mentions("CLAUDE_CODE_DISABLE_AUTO_MEMORY"):
            report.add("HST021", "info", "isolation",
                       "auto memory is not disabled",
                       path=str(root),
                       fix="auto memory at ~/.claude/projects/<project>/memory/ loads into "
                           "the system prompt regardless of setting_sources. Set "
                           "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 in `env`.",
                       source=SRC_ISOLATION)
        if hosted and not primary.has("cwd"):
            report.add("HST022", "info", "isolation",
                       "no per-session cwd: every session inherits the application's "
                       "working directory",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="one session is one subprocess, and it owns a shell in that "
                           "directory. Pass a distinct cwd per session so artefacts and "
                           "transcripts cannot collide.",
                       source=SRC_HOSTING)

    # -- HST030: telemetry -----------------------------------------------
    otel_present = [name for name in OTEL_VARS if env_mentions(name)]
    telemetry_on = env_mentions("CLAUDE_CODE_ENABLE_TELEMETRY")
    if not otel_present:
        report.add("HST030", "info", "observability",
                   "no OpenTelemetry configuration: a hosted run leaves no record of which "
                   "tools ran, how long they took, or where it stalled",
                   path=str(root),
                   fix="set CLAUDE_CODE_ENABLE_TELEMETRY=1 and at least one exporter at the "
                       "container level; the CLI exports directly to your collector. Traces "
                       "additionally need CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1.",
                   source=SRC_OBSERVABILITY)
    elif not telemetry_on:
        report.add("HST030", "warn", "observability",
                   f"OTEL exporters are configured ({', '.join(otel_present)}) but "
                   "CLAUDE_CODE_ENABLE_TELEMETRY is not set, so nothing is exported",
                   path=str(root),
                   fix="telemetry is off until CLAUDE_CODE_ENABLE_TELEMETRY=1. The "
                       "exporters alone do nothing.",
                   source=SRC_OBSERVABILITY)

    # -- HST040 / HST041: what is in the image ---------------------------
    for name, text in container_text.items():
        for match in SK_ANT.finditer(text):
            report.add("HST040", "error", "credentials",
                       f"a credential literal is baked into {name} "
                       f"({match.group(0)[:12]}…)",
                       path=str(root / name),
                       fix="rotate it now: anyone who can pull the image has it, and it is "
                           "in every layer of the build history. Pass it at run time from a "
                           "secret manager instead.",
                       source=SRC_SECURE)
        for match in SECRET_LITERAL.finditer(text):
            value = match.group(1)
            if value.startswith(("${", "$", "<")) or SK_ANT.match(value):
                continue
            report.add("HST040", "error", "credentials",
                       f"{name} sets a credential to a literal value",
                       path=str(root / name), locator=match.group(0)[:40],
                       fix="reference a build-time secret or a run-time environment "
                           "variable; never a literal in a layer.",
                       source=SRC_SECURE)
        if copies_dotenv(text):
            report.add("HST041", "error", "credentials",
                       f"{name} copies a .env file into the image",
                       path=str(root / name),
                       fix="delete the COPY. The file persists in the image layer even if a "
                           "later step removes it. Pass the values as environment variables "
                           "at run time.",
                       source=SRC_SECURE)
        elif copies_everything(text) and layout.env_files:
            report.add("HST041", "error", "credentials",
                       f"{name} copies the whole directory into the image, and a .env file "
                       "is present",
                       path=str(root / name),
                       fix="add .env to .dockerignore, or copy only the files the image "
                           "needs.",
                       source=SRC_SECURE)

    # -- HST050: resumable sessions --------------------------------------
    resumable = bool(primary and (primary.has("resume") or primary.has("session_id")
                                  or primary.has("fork_session")
                                  or primary.has("resume_session_at")))
    if resumable and not (primary and primary.has("session_store")):
        report.add("HST050", "info", "state",
                   "the agent resumes sessions but configures no SessionStore, so the "
                   "transcript lives only on the container's local disk",
                   path=primary.path if primary else str(root),
                   fix="local disk is lost on restart, scale-down or a move to another "
                       "node. A SessionStore mirrors transcripts (not CLAUDE.md memory, not "
                       "working-directory artefacts) to durable storage.",
                   source=SRC_SESSION_STORE)

    if not container_files and args.target == "docker":
        report.add_gap("GAP-CONTAINER", "No container definition",
                       "nothing describes how this agent runs anywhere but here",
                       "scripts/gen_dockerfile.py writes a python:3.12-slim image with a "
                       "non-root user, no secrets, auto memory disabled and the telemetry "
                       "variables commented.")

    report.discovered = {
        "target": args.target,
        "container_files": [p.name for p in container_files],
        "credential": {
            "api_style": api, "subscription_style": subscription,
            "hosted": hosted,
        },
        "isolation": {
            "setting_sources": (primary.get("setting_sources").value
                                if primary and primary.has("setting_sources") else None),
            "strict_mcp_config": (primary.get("strict_mcp_config").value
                                  if primary and primary.has("strict_mcp_config") else False),
            "per_session_cwd": bool(primary and primary.has("cwd")),
            "auto_memory_disabled": env_mentions("CLAUDE_CODE_DISABLE_AUTO_MEMORY"),
        },
        "ceilings": {
            "max_turns": (primary.get("max_turns").value
                          if primary and primary.has("max_turns") else None),
            "max_budget_usd": (primary.get("max_budget_usd").value
                               if primary and primary.has("max_budget_usd") else None),
            "subagents": [a.name for a in facts.agents],
        },
        "telemetry": {"enabled": telemetry_on, "exporters": otel_present},
        "env_files": [Path(p).name for p in layout.env_files],
        "example_files": [Path(p).name for p in layout.example_files],
    }

    if report.count("error"):
        report.add_option(Option(
            key="1", label="Fix the deployment errors", recommended=True,
            detail="a credential in an image and a subscription credential in a hosted "
                   "agent are both things you cannot fix later",
        ))
    report.add_option(Option(
        key=str(len(report.options) + 1), label="Generate a container definition",
        detail="scripts/gen_dockerfile.py: python:3.12-slim, non-root, no secrets, auto "
               "memory off, telemetry commented, healthcheck hint",
        writes=["Dockerfile"],
    ))
    report.add_option(Option(
        key=str(len(report.options) + 1), label="Generate a locked-down settings file",
        detail="scripts/gen_secure_settings.py: setting_sources=[], strict_mcp_config, "
               "permission rules, and the egress note",
        writes=["agent_settings.json", ".env.deploy.example"],
    ))

    print(report.render(args.format))
    return EXIT_FINDINGS if report.count("error") else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
