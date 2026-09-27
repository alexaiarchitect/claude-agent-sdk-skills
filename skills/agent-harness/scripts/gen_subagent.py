#!/usr/bin/env python3
"""Write a subagent: an `AgentDefinition` snippet, or a `.claude/agents/<name>.md` file.

A subagent is a second agent instance with its own context window. The parent
sends it one prompt string and gets back one final message; nothing else
crosses. That is the whole value — an exploration that would fill the main
conversation happens somewhere else — and also the whole risk, because the
parent cannot see what it did.

Three things this generator insists on, because the SDK does not:

* **`tools`** — omitted, a subagent inherits every tool available to subagents.
  Name what its prompt actually needs (`SUB001`).
* **`maxTurns`** — the parent's `max_turns` does not cap a subagent, and every
  subagent request counts toward the query's `total_cost_usd` (`SUB003`).
* **the subagent tool** — Claude reaches a subagent through a tool the docs and
  SDK call `Agent` and the CLI reports as `Task`. Both names have to be
  available, or nothing delegates (`OPT040`).

`--as python` writes an `AgentDefinition` for the `agents` option: explicit,
travels with the code, and unaffected by `setting_sources`. `--as markdown`
writes `.claude/agents/<name>.md`, which only loads when `setting_sources`
includes `project` — so it is the wrong choice for an eval and the right one for
a subagent you also want in interactive Claude Code.

    gen_subagent.py --name shelf-auditor --description "Counts copies on the shelf"
        --tools Read Grep [--model inherit] [--max-turns 4] [--prompt-file p]
        [--as python|markdown] [--out path] [--dry-run] [--force] [--json]

Exit codes: 0 written (or planned, under --dry-run), 1 nothing to write,
2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import RETIRED_MODELS  # noqa: E402
from agent_sdk_skills.env import classify_model_id  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WritePlan  # noqa: E402

#: A subagent name is referenced by Claude and by `.claude/agents/<name>.md`.
NAME = re.compile(r"^[a-z0-9][a-z0-9\-]*$")

DEFAULT_PROMPT = """You are {name}.

{description}

Rules:
1. Do only what you were asked in the prompt you received; you cannot see the
   parent conversation, so do not assume context you were not given.
2. Report the result in your final message, with the evidence you relied on.
   Only that final message reaches the parent.
3. If you cannot do the task with the tools you have, say so instead of
   improvising.
"""

PYTHON_TEMPLATE = '''"""Subagent "{name}", for the `agents` option.

Claude decides on its own when to delegate. It reads `description` to make that
decision, so write the description for Claude, not for a human reader: say when
to use this agent, not what it is.
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

{constant} = AgentDefinition(
    description={description!r},
    prompt={prompt!r},
    tools={tools!r},
    model={model!r},
    maxTurns={max_turns},
)

# In your builder:
#
#     return ClaudeAgentOptions(
#         agents={{"{name}": {constant}}},
#         # both spellings: the docs and SDK say Agent, the CLI reports Task
#         allowed_tools=[..., "Agent", "Task"],
#         max_budget_usd=1.00,          # counts subagent spend too
#         env={{"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
#              "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "5"}},
#     )
'''

MARKDOWN_TEMPLATE = """---
name: {name}
description: {description}
tools: {tools_csv}
{model_line}---

{prompt}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", required=True, help="lower-case, hyphenated")
    parser.add_argument("--description", required=True,
                        help="when Claude should delegate to this agent; Claude reads it")
    parser.add_argument("--tools", nargs="*", default=[],
                        help="the tools it may use. Empty means it inherits every tool "
                             "available to subagents, which is rarely what you want")
    parser.add_argument("--model", default="inherit",
                        help="an alias, a full id, or 'inherit' (default) to use the main "
                             "model, which keeps an eval to one variable")
    parser.add_argument("--max-turns", type=int, default=4,
                        help="the subagent's own ceiling; the parent's max_turns does not "
                             "cap it")
    parser.add_argument("--prompt-file", help="read the system prompt from this file")
    parser.add_argument("--as", dest="kind", choices=("python", "markdown"), default="python")
    parser.add_argument("--out", help="where to write (default: agents_<name>.py or "
                                     ".claude/agents/<name>.md)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the write plan and the snippet; write nothing")
    parser.add_argument("--force", action="store_true", help="replace an existing file")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args(argv)

    if not NAME.match(args.name):
        print(f"error: {args.name!r} is not a usable subagent name: lower-case letters, "
              "digits and hyphens, starting with a letter or digit.", file=sys.stderr)
        return EXIT_USAGE
    if args.max_turns < 1:
        print("error: --max-turns must be at least 1", file=sys.stderr)
        return EXIT_USAGE
    if args.model not in ("inherit",) and classify_model_id(args.model) == "retired":
        print(f"error: {args.model} is retired; requests to it fail. Retired ids: "
              + ", ".join(RETIRED_MODELS[:4]) + ", ...", file=sys.stderr)
        return EXIT_USAGE

    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.is_file():
            print(f"error: {prompt_path} does not exist", file=sys.stderr)
            return EXIT_USAGE
        prompt = prompt_path.read_text(encoding="utf-8")
    else:
        prompt = DEFAULT_PROMPT.format(name=args.name, description=args.description)

    constant = args.name.replace("-", "_").upper()
    if args.kind == "python":
        out = Path(args.out) if args.out else Path(f"agents_{args.name.replace('-', '_')}.py")
        content = PYTHON_TEMPLATE.format(
            name=args.name, constant=constant, description=args.description,
            prompt=prompt, tools=list(args.tools) or None, model=args.model,
            max_turns=args.max_turns,
        )
    else:
        out = Path(args.out) if args.out else Path(".claude") / "agents" / f"{args.name}.md"
        model_line = f"model: {args.model}\n" if args.model != "inherit" else ""
        content = MARKDOWN_TEMPLATE.format(
            name=args.name, description=args.description,
            tools_csv=", ".join(args.tools) or "Read, Grep",
            model_line=model_line, prompt=prompt.strip(),
        )

    plan = WritePlan()
    plan.add(out, content, force=args.force,
             reason=f'subagent "{args.name}", '
                    f"tools={args.tools or 'inherited (SUB001)'}, "
                    f"maxTurns={args.max_turns}")

    notes: list[str] = []
    if not args.tools:
        notes.append("no --tools given, so this subagent inherits every tool available to "
                     "subagents (SUB001). Name the ones its prompt needs.")
    if args.kind == "markdown":
        notes.append(".claude/agents/ files load only when setting_sources includes "
                     "`project`, so an eval with setting_sources=[] will not see this one. "
                     "A programmatic `agents` entry of the same name wins anyway.")
    notes.append('Claude reaches it through a tool named "Agent" in the docs and SDK and '
                 'reported as "Task" by the CLI: allow both.')

    payload = {
        "name": args.name, "kind": args.kind, "tools": list(args.tools),
        "model": args.model, "max_turns": args.max_turns, "out": str(out),
        "dry_run": args.dry_run, "notes": notes, "plan": plan.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(plan.to_md())
        print()
        for note in notes:
            print(f"- {note}")
        if args.dry_run:
            print()
            print("--- snippet (not written) ---")
            print(content)
    if args.dry_run:
        return EXIT_OK

    written = plan.apply()
    if not written:
        if not args.json:
            print("nothing written; pass --force to replace an existing file")
        return EXIT_FINDINGS
    if not args.json:
        for path in written:
            print(f"wrote {path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
