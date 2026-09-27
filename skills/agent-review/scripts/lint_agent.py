#!/usr/bin/env python3
"""Review a Claude Agent SDK agent's source without running it.

Everything is read from the syntax tree, so a missing virtualenv, a broken
dependency or a side effect at import time cannot affect the review — and the
review works on the project that does not start, which is when you need it.

Ten dimensions:

1.  entry point — can anything outside the module obtain the options
2.  legacy names — `claude_code_sdk`, `ClaudeCodeOptions`, deprecated fields
3.  model policy — hardcoded, retiring, retired, or absent
4.  credentials — a key literal in source, a missing `.env.example`
5.  tool surface — what `allowed_tools`, `disallowed_tools` and `tools` really do
6.  limits — `max_turns`, `max_budget_usd`
7.  context — `setting_sources`, and what the host machine leaks into a run
8.  hooks — async, three parameters, the right return shape, a valid matcher
9.  MCP — servers that exist, commands on PATH, readable `@tool` schemas
10. subagents, system prompt, structured output

Report only. It never edits.

    lint_agent.py <project> [--strict] [--format json|md] [--json] [--no-path-check]

Exit codes: 0 no errors, 1 errors (or any warning under `--strict`),
2 nothing to review.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _checks import (  # noqa: E402
    SRC_DEPRECATIONS, SRC_OPTIONS, hook_findings, mcp_findings, permission_findings,
    setting_sources_of, subagent_findings, subagent_tool_allowed,
)
from agent_sdk_skills import (  # noqa: E402
    EFFORT_LEVELS, MODEL_ENV_VAR, SUBAGENT_TOOL_NAMES,
)
from agent_sdk_skills.env import classify_model_id, version_at_least  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.options_ast import extract_project  # noqa: E402
from agent_sdk_skills.report import (  # noqa: E402
    EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport, Option,
)

DOCS = "https://code.claude.com/docs/en/agent-sdk"
SRC_MIGRATION = f"{DOCS}/migration-guide"
SRC_SETTING_SOURCES = f"{DOCS}/claude-code-features#control-filesystem-settings-with-settingsources"
SRC_SYSTEM_PROMPT = f"{DOCS}/modifying-system-prompts#how-system-prompts-work"
SRC_STRUCTURED = f"{DOCS}/structured-outputs"
SRC_AGENT_LOOP = f"{DOCS}/agent-loop#turns-and-budget"
SRC_SUBAGENTS = f"{DOCS}/subagents#programmatic-definition-recommended"
SRC_QUICKSTART = f"{DOCS}/quickstart"
SRC_MODEL_CONFIG = "https://code.claude.com/docs/en/model-config#default-model-setting"

#: The release in which `setting_sources=[]` started taking effect in Python.
SETTING_SOURCES_FIXED_IN = "0.1.60"

_PIN = re.compile(r"claude[-_]agent[-_]sdk\s*(==|<=|~=|<)\s*([0-9][0-9A-Za-z.\-]*)")


def pinned_sdk_ceiling(project: Path) -> tuple[str, str] | None:
    """The `(file, version)` of an SDK pin that cannot exceed that version."""
    for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py"):
        path = project / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _PIN.finditer(text):
            return name, match.group(2)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="project root or agent module")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as failures, and bypassPermissions as an error")
    parser.add_argument("--format", choices=("json", "md"), default="md")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        help="print the gap report as JSON instead of markdown")
    parser.add_argument("--no-path-check", action="store_true",
                        help="skip looking for stdio MCP commands on this machine's PATH")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(target)
    root = Path(layout.project_root or target)
    # Naming one module means reviewing that module. Reading its whole directory
    # would attribute a sibling's subagents and servers to it, which is how a
    # sweep over an examples/ directory reports the same finding 25 times.
    facts = extract_project(target if target.is_file() else root)
    if not facts.modules:
        print(f"error: no Claude Agent SDK usage under {target} "
              "(no module imports claude_agent_sdk)", file=sys.stderr)
        return EXIT_USAGE

    report = GapReport(subject=str(root), skill="agent-review")
    primary = facts.primary
    claude = layout.claude

    # -- 0. unparseable modules ------------------------------------------
    for module in facts.modules:
        if module.syntax_error:
            report.add("AGT000", "error", "agent",
                       f"could not parse: {module.syntax_error}", path=module.path,
                       fix="the reviewer reads source, so a file it cannot parse is a file "
                           "it cannot judge. Fix the syntax first.")

    # -- 1. entry point ---------------------------------------------------
    if primary is None:
        report.add("AGT001", "error", "agent",
                   "no ClaudeAgentOptions is constructed anywhere in this project",
                   path=facts.modules[0].path,
                   fix="an agent is a module that builds options and runs a session. "
                       "Expose `build_options() -> ClaudeAgentOptions` so a runner can "
                       "obtain them.",
                   source=SRC_OPTIONS)
    else:
        if len(facts.modules) > 1 and not facts.has_build_options:
            report.add("AGT002", "warn", "agent",
                       f"{len(facts.modules)} modules use the SDK and none defines "
                       "build_options(), so the entry point is a guess",
                       path=primary.path,
                       fix="name the entry point: define `build_options()` in the module "
                           "that owns the agent, or set `agent: \"module:function\"` in "
                           "evals/eval_config.json (or AGENT_ENTRY in .env).",
                       source=SRC_OPTIONS)
        if all(call.in_main for call in facts.options_calls):
            report.add("AGT003", "warn", "agent",
                       f"the options are built inside {primary.function}(), so nothing "
                       "outside this process can obtain them",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="move the construction into `build_options()` and call it from "
                           f"{primary.function}(). Until then every eval override is a "
                           "source edit, and the review below covers only what is literal.",
                       source=SRC_OPTIONS)
    for call in facts.query_calls:
        if call.call == "query" and not call.has_options:
            report.add("AGT004", "warn", "agent",
                       "query() is called with no options, so the session runs on SDK "
                       "defaults: no model pinned, no tool restriction, no ceilings",
                       path=call.path, locator=f"line {call.lineno}",
                       fix="pass options=build_options(). The defaults also load the host "
                           "machine's settings and CLAUDE.md files.",
                       source=SRC_OPTIONS)

    # -- 2. legacy names --------------------------------------------------
    for module in facts.modules:
        if module.imports_legacy_sdk:
            report.add("AGT030", "error", "agent",
                       "imports `claude_code_sdk`, the package's former name",
                       path=module.path,
                       fix="`pip install claude-agent-sdk` and import from "
                           "`claude_agent_sdk`. The old package no longer receives the "
                           "options, messages and hooks this plugin describes.",
                       source=SRC_MIGRATION)
    for call in facts.options_calls:
        if call.legacy:
            report.add("AGT030", "error", "options",
                       "uses `ClaudeCodeOptions`, renamed to `ClaudeAgentOptions`",
                       path=call.path, locator=f"line {call.lineno}",
                       fix="rename the class. Most fields carried over, but the current "
                           "ones (`tools`, `setting_sources`, `max_budget_usd`, `agents`, "
                           "`skills`, `effort`, `output_format`) only exist on the new one.",
                       source=SRC_MIGRATION)
    for module in facts.modules:
        for name in module.deprecated_options:
            if name == "max_thinking_tokens":
                report.add("AGT031", "warn", "options",
                           "`max_thinking_tokens` is deprecated",
                           path=module.path,
                           fix="use `thinking={\"type\": \"adaptive\"}` (or "
                               "`{\"type\": \"enabled\", \"budget_tokens\": N}`). On newer "
                               "models the old field is read as on/off only.",
                           source="claude-agent-sdk 0.2.162 types.py:2350")
            else:
                report.add("AGT031", "warn", "options",
                           "`debug_stderr` is deprecated and is no longer read by the "
                           "transport, so it silences nothing and captures nothing",
                           path=module.path,
                           fix="pass the `stderr` callback instead: "
                               "`stderr=lambda line: log.debug(line)`.",
                           source="claude-agent-sdk 0.2.162 types.py:2149")

    # -- 3. model policy --------------------------------------------------
    option_models = [
        ref for ref in facts.model_refs if ref.where in ("options", "env_default")
    ]
    for ref in option_models:
        if ref.hardcoded and ref.value:
            report.add("AGT010", "warn", "model",
                       f"the model id {ref.value} is hardcoded",
                       path=ref.path, locator=f"line {ref.lineno}",
                       fix=f"read it from the environment: "
                           f"os.getenv(\"{MODEL_ENV_VAR}\", \"{ref.value}\"). A dated id "
                           "gets retired and the agent stops working on a date nobody "
                           "wrote down.",
                       source=SRC_DEPRECATIONS)
        grade = classify_model_id(ref.value) if ref.value else "unknown"
        if grade == "retired":
            report.add("AGT012", "error", "model",
                       f"{ref.value} is retired and no longer served",
                       path=ref.path, locator=f"line {ref.lineno}",
                       fix="pick a current id from the models overview; requests to a "
                           "retired model fail outright.",
                       source=SRC_DEPRECATIONS)
        elif grade == "retiring":
            report.add("AGT011", "warn", "model",
                       f"{ref.value} is retirement-eligible",
                       path=ref.path, locator=f"line {ref.lineno}",
                       fix="move to a current id before the retirement date, or use an "
                           "alias and let the CLI resolve it.",
                       source=SRC_DEPRECATIONS)
    if primary is not None and not primary.has("model") and not primary.has("fallback_model"):
        report.add("OPT012", "warn", "model",
                   "no model is set, so the session starts on Claude Code's default",
                   path=primary.path, locator=f"line {primary.lineno}",
                   fix="pin it: model=os.getenv(\"CLAUDE_MODEL\", \"claude-sonnet-5-5\"). "
                       "Measured on this machine, the CLI default (claude-fable-5-1) cost "
                       "about four times what Sonnet cost for the same trivial prompt, and "
                       "results stop being comparable when the model can change under you.",
                   source=SRC_MODEL_CONFIG)

    # -- 4. credentials ---------------------------------------------------
    for secret in facts.secrets:
        report.add("AGT020", "error", "credentials",
                   f"a credential literal is in source ({secret.preview})",
                   path=secret.path, locator=f"line {secret.lineno}",
                   fix="delete it, rotate the key, and read it from the environment. The "
                       "SDK never reads a credential from your code: the bundled CLI "
                       "picks it up from the subprocess environment.",
                   source=SRC_QUICKSTART)
    if not layout.example_files:
        report.add("AGT021", "info", "credentials",
                   "no .env.example, so nothing tells the next person which variables "
                   "this agent needs",
                   path=str(root),
                   fix="list CLAUDE_MODEL and the credential choice with the key line "
                       "commented out, plus a `claude setup-token` note for CI.",
                   source=SRC_QUICKSTART)

    # -- 5. tool surface and permissions (shared) -------------------------
    report.extend(permission_findings(facts, strict=args.strict))

    # -- 6. limits --------------------------------------------------------
    if primary is not None:
        if not primary.has("max_turns"):
            report.add("OPT010", "warn", "limits",
                       "no max_turns, so a loop has no ceiling",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="set max_turns. Note it is not a hard stop on assistant turns: "
                           "assert on terminal_reason == \"max_turns\" or subtype == "
                           "\"error_max_turns\", never on num_turns.",
                       source=SRC_AGENT_LOOP)
        if not primary.has("max_budget_usd"):
            report.add("OPT011", "warn", "limits",
                       "no max_budget_usd, so nothing stops a run that goes wrong "
                       "expensively",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="set max_budget_usd. It counts the call's own spend including "
                           "subagent requests, refuses to spawn more subagents at the cap, "
                           "and ends the query with subtype error_max_budget_usd.",
                       source=SRC_AGENT_LOOP)

    # -- 7. context and settings -----------------------------------------
    if primary is not None:
        explicit, sources = setting_sources_of(facts)
        has_local_config = bool(claude and claude.any)
        if not explicit:
            severity = "warn" if has_local_config else "info"
            report.add("OPT020", severity, "context",
                       "setting_sources is not set, so the SDK matches the CLI and loads "
                       "user, project and local settings plus every CLAUDE.md it finds",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="pass setting_sources=[] for an eval or a CI run, so the host "
                           "machine's configuration cannot change the result. Measured on "
                           "this machine, the same prompt cost 17x more with the default "
                           "than with setting_sources=[] and strict_mcp_config=True, "
                           "because of ambient config in the cache-creation tokens.",
                       source=SRC_SETTING_SOURCES)
        elif sources == []:
            pin = pinned_sdk_ceiling(root)
            if pin and not version_at_least(pin[1], SETTING_SOURCES_FIXED_IN):
                report.add("OPT021", "warn", "context",
                           f"setting_sources=[] but {pin[0]} pins claude-agent-sdk "
                           f"{pin[1]}, where an empty list was treated as unset",
                           path=str(root / pin[0]),
                           fix=f"raise the pin to >= {SETTING_SOURCES_FIXED_IN}. Until "
                               "then the isolation silently does not happen.",
                           source=f"{DOCS}/python#claudeagentoptions")

    # -- 8, 9. hooks and MCP (shared) -------------------------------------
    report.extend(hook_findings(facts, claude))
    report.extend(mcp_findings(facts, check_path=not args.no_path_check))

    # -- 10. subagents, prompt, structured output -------------------------
    if primary is not None:
        if primary.system_prompt_kind == "absent":
            report.add("OPT030", "info", "prompt",
                       "no system_prompt, so the SDK uses its minimal default: tool "
                       "calling and nothing else",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="that is correct for a thin tool-calling loop. For anything "
                           "with a persona or a refusal rule, write a prompt, or use "
                           "{\"type\": \"preset\", \"preset\": \"claude_code\"} to get "
                           "Claude Code's tool and safety guidance. `claude -p` uses the "
                           "preset; the SDK does not.",
                       source=SRC_SYSTEM_PROMPT)
        elif primary.system_prompt_kind == "preset" and not primary.system_prompt_append:
            report.add("OPT031", "info", "prompt",
                       "the claude_code preset is used with no `append`, so the agent has "
                       "Claude Code's instructions and none of its own",
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="add `append` with the product's own rules; nothing is removed, "
                           "so it is the lowest-risk customization.",
                       source=SRC_SYSTEM_PROMPT)
    for call in facts.options_calls:
        if call.agents and not subagent_tool_allowed(call):
            report.add("OPT040", "warn", "subagents",
                       f"{len(call.agents)} subagent(s) are defined but the subagent tool "
                       "is not available, so Claude cannot delegate to any of them",
                       path=call.path, locator=f"line {call.lineno}",
                       fix="add \"Agent\" (the docs' and SDK's name) or \"Task\" (what the "
                           "CLI reports) to allowed_tools, and do not remove it with "
                           "disallowed_tools or a `tools` list that omits it.",
                       source=SRC_SUBAGENTS)

    if primary is not None:
        if primary.output_format is not None:
            fmt = primary.output_format
            if not fmt.is_json_schema:
                report.add("OPT050", "error", "options",
                           "output_format is not a {\"type\": \"json_schema\", \"schema\": "
                           "{...}} object, so the CLI ignores it silently and "
                           "structured_output stays empty",
                           path=primary.path, locator=f"line {fmt.lineno}",
                           fix="the transport acts only on type == \"json_schema\" and "
                               "passes `schema` through as --json-schema. Any other type "
                               "is dropped without an error.",
                           source=SRC_STRUCTURED)
        effort = primary.get("effort")
        effort_value = effort.as_str() if effort else None
        if effort_value is not None and effort_value not in EFFORT_LEVELS:
            report.add("OPT061", "error", "options",
                       f'effort="{effort_value}" is not one of the five levels',
                       path=primary.path, locator=f"line {primary.lineno}",
                       fix="one of: " + ", ".join(EFFORT_LEVELS),
                       source="claude-agent-sdk 0.2.162 types.py:37 (EffortLevel)")
    report.extend(subagent_findings(facts, claude))

    # -- what was found ---------------------------------------------------
    report.discovered = {
        "entry": {
            "style": layout.style,
            "module": primary.path if primary else None,
            "builder": (primary.function or "module level") if primary else None,
            "injectable": primary.injectable if primary else False,
            "entry_spec": layout.entry_spec,
        },
        "options": {
            "fields": primary.names() if primary else [],
            "model": (primary.get("model").to_dict() if primary and primary.has("model") else None),
            "permission_mode": (primary.get("permission_mode").as_str()
                                if primary and primary.has("permission_mode") else None),
            "setting_sources": setting_sources_of(facts)[1],
        },
        "tools": {
            "in_process": facts.tool_names(),
            "mcp_servers": [f"{s.key} ({s.kind})" for s in facts.mcp_servers],
            "allowed_tools": primary.str_list("allowed_tools") if primary else [],
            "disallowed_tools": primary.str_list("disallowed_tools") if primary else [],
        },
        "harness": {
            "hook_events": sorted({h.event for h in facts.hooks}),
            "subagents": [a.name for a in facts.agents],
            "claude_files": (claude.to_dict() if claude else None),
        },
        "modules": [m.path for m in facts.modules],
    }

    if report.count("error"):
        report.add_option(Option(
            key="1", label="Fix the errors, then re-run this review", recommended=True,
            detail="each error is something the SDK rejects, ignores, or acts on in a way "
                   "that makes the run mean something else",
        ))
    elif report.count("warn"):
        report.add_option(Option(
            key="1", label="Address the warnings", recommended=True,
            detail="each one runs today and misleads, or stops running on a date",
        ))
    report.add_option(Option(
        key=str(len(report.options) + 1), label="Design the harness",
        detail="hooks, permissions, MCP servers and subagents: /agent-sdk:agent-harness",
    ))
    report.add_option(Option(
        key=str(len(report.options) + 1), label="Prove it loads",
        detail="run scripts/load_agent.py to import the entry point in an interpreter "
               "that has the SDK; it never starts a session",
    ))

    print(report.render(args.format))
    if report.count("error"):
        return EXIT_FINDINGS
    if args.strict and report.count("warn"):
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
