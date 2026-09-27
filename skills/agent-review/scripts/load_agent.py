#!/usr/bin/env python3
"""Import the agent's entry point and print the options it built. No session.

The static review catches most problems, but only an import proves the module
loads: a missing dependency, a circular import, a builder that raises, a
keyword `ClaudeAgentOptions` does not have (a dataclass raises `TypeError` on
one). And only the built object shows what a computed value came out as.

Nothing here imports the SDK into *this* interpreter. The probe below is a
string, executed by the interpreter `agent_sdk_skills.env.resolve_runner`
found: `$AGENT_SDK_PYTHON`, a virtualenv at or above the project, a `python3`
on PATH that can import `claude_agent_sdk`, or `uv run --with`.

**It never starts a session.** The probe calls the builder and reads the
dataclass; it does not call `query()`, does not construct a `ClaudeSDKClient`,
and spends nothing. What it costs is one import of the project's own code,
which is the thing being tested.

    load_agent.py <project> [--entry module:function] [--json] [--timeout s]

Exit codes: 0 loaded, 1 did not load, 2 no interpreter with the SDK (or no
agent to load).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.env import detect_credential, resolve_runner  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.sdk_subprocess import describe_runner, run_probe  # noqa: E402

#: Executed by the resolved interpreter, never by this one. The literal
#: `build_options` has to appear in this source: the test fake recognises the
#: load probe by it and answers without a real SDK.
PROBE = r'''
import importlib, json, os, sys, traceback

project, entry = sys.argv[1], sys.argv[2]
sys.path.insert(0, project)
result = {"entry": entry, "project": project}


def kind_of_system_prompt(value):
    if value is None:
        return "absent"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return str(value.get("type", "dict"))
    return type(value).__name__


try:
    import claude_agent_sdk as sdk

    # Read the version from installed metadata rather than the dunder, so this
    # probe cannot be mistaken for the interpreter version probe in env.py.
    try:
        from importlib.metadata import version as distribution_version

        result["sdk_version"] = distribution_version("claude-agent-sdk")
    except Exception:
        result["sdk_version"] = "unknown"
    result["cli_version"] = getattr(sdk, "__cli_version__", None)

    module_path, _, function_name = entry.partition(":")
    function_name = function_name or "build_options"
    module = importlib.import_module(module_path)
    result["module_file"] = getattr(module, "__file__", None)
    builder = getattr(module, function_name, None)
    if builder is None:
        raise AttributeError(
            "%s exposes no %s(); name the builder with --entry module:function"
            % (module_path, function_name)
        )
    result["builder"] = function_name
    options = builder()
    result["options_type"] = type(options).__name__

    def read(name, default=None):
        return getattr(options, name, default)

    servers = read("mcp_servers", {}) or {}
    hooks = read("hooks", None) or {}
    agents = read("agents", None) or {}
    result["options"] = {
        "model": read("model"),
        "fallback_model": read("fallback_model"),
        "tools": read("tools"),
        "allowed_tools": list(read("allowed_tools", []) or []),
        "disallowed_tools": list(read("disallowed_tools", []) or []),
        "permission_mode": read("permission_mode"),
        "max_turns": read("max_turns"),
        "max_budget_usd": read("max_budget_usd"),
        "setting_sources": read("setting_sources"),
        "strict_mcp_config": read("strict_mcp_config"),
        "effort": read("effort"),
        "mcp_servers": sorted(servers) if isinstance(servers, dict) else str(servers),
        "hook_events": sorted(hooks) if isinstance(hooks, dict) else str(hooks),
        "agents": sorted(agents) if isinstance(agents, dict) else str(agents),
        "output_format_present": read("output_format") is not None,
        "system_prompt": kind_of_system_prompt(read("system_prompt")),
    }
    # Every field the installed dataclass declares, so a review run against a
    # newer SDK can say which options this agent never touches.
    fields = getattr(type(options), "__dataclass_fields__", {})
    result["option_fields"] = sorted(fields)
    result["loaded"] = True
except BaseException as exc:
    result["loaded"] = False
    result["error_type"] = type(exc).__name__
    result["error"] = str(exc)
    result["traceback"] = traceback.format_exc().splitlines()[-12:]

print(json.dumps(result))
'''

HINTS = {
    "ModuleNotFoundError":
        "the interpreter that ran this cannot see the module. Either the project is not "
        "on sys.path (run from the project root), or a dependency is missing from that "
        "interpreter - install the project's requirements into the same environment as "
        "claude-agent-sdk.",
    "ImportError":
        "a name could not be imported. Several moved when claude_code_sdk became "
        "claude_agent_sdk; check the migration reference. `MessageParseError` in "
        "particular is not exported from the package root and must come from "
        "claude_agent_sdk._errors.",
    "AttributeError":
        "the module imports but exposes no builder. Define "
        "`build_options() -> ClaudeAgentOptions`, or name yours with "
        "--entry module:function.",
    "TypeError":
        "ClaudeAgentOptions rejected a keyword. It is a plain dataclass, so an unknown "
        "or misspelled field raises immediately - compare the name against the 49 fields "
        "in references/options-reference.md.",
    "ValueError":
        "a value was rejected at construction. The `skills` option validates names "
        "strictly (no parentheses, commas, wildcards or leading slash) since SDK 0.2.129.",
    "FileNotFoundError":
        "the builder read a file that is not there. A system prompt loaded from disk or a "
        "catalog fixture is usually relative to the working directory.",
    "CLINotFoundError":
        "the SDK could not find a `claude` binary. Most installs bundle one; a source "
        "checkout may not. Install Claude Code, or pass cli_path.",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="project root")
    parser.add_argument("--entry", help="module:function to load (default: the convention "
                                       "agent:build_options, or AGENT_ENTRY)")
    parser.add_argument("--json", action="store_true", help="print the probe result as JSON")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.exists():
        print(f"error: {project} does not exist", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(project)
    root = Path(layout.project_root or project)

    entry = args.entry
    if not entry:
        credential = detect_credential(root, ask_cli=False)
        entry = credential.entry_env or os.environ.get("AGENT_ENTRY") or layout.entry_spec
    if not entry:
        print(f"error: nothing to load under {root}: no build_options(), no AGENT_ENTRY, "
              "and no --entry", file=sys.stderr)
        return EXIT_USAGE

    runner = resolve_runner(root)
    if not runner.available:
        print(f"error: {runner.note}", file=sys.stderr)
        return EXIT_USAGE

    outcome = run_probe(runner, PROBE, [str(root), entry], cwd=root, timeout=args.timeout)
    payload: dict = {"runner": describe_runner(runner), "entry": entry, "project": str(root)}
    parsed = outcome.last_json()
    if parsed:
        payload.update(parsed)
    if "loaded" not in payload:
        payload["loaded"] = False
        payload["error_type"] = "ProbeFailed"
        payload["error"] = outcome.tail(15) or "the probe produced no output"
    if not payload["loaded"] and payload.get("error_type") in HINTS:
        payload["hint"] = HINTS[payload["error_type"]]

    if args.json:
        print(json.dumps(payload, indent=2))
    elif payload["loaded"]:
        options = payload.get("options") or {}
        print(f"Loaded    {payload['entry']}")
        print(f"Runner    {payload['runner']}")
        if payload.get("sdk_version"):
            print(f"SDK       {payload['sdk_version']}"
                  + (f" (bundled CLI {payload['cli_version']})" if payload.get("cli_version") else ""))
        print(f"Model     {options.get('model')}")
        print(f"Tools     tools={options.get('tools')!r} "
              f"allowed={options.get('allowed_tools')} "
              f"disallowed={options.get('disallowed_tools')}")
        print(f"Limits    max_turns={options.get('max_turns')} "
              f"max_budget_usd={options.get('max_budget_usd')} "
              f"permission_mode={options.get('permission_mode')}")
        print(f"Context   setting_sources={options.get('setting_sources')!r} "
              f"strict_mcp_config={options.get('strict_mcp_config')}")
        print(f"Harness   mcp={options.get('mcp_servers')} "
              f"hooks={options.get('hook_events')} agents={options.get('agents')}")
        print(f"Shape     system_prompt={options.get('system_prompt')} "
              f"output_format={'set' if options.get('output_format_present') else 'none'}")
        print("No session was started; nothing was spent.")
    else:
        print(f"Did not load: {payload.get('error_type')}: {payload.get('error')}")
        if payload.get("hint"):
            print(f"Likely:   {payload['hint']}")
        for line in (payload.get("traceback") or [])[-6:]:
            print(f"  {line}")

    return EXIT_OK if payload["loaded"] else EXIT_FINDINGS


if __name__ == "__main__":
    raise SystemExit(main())
