#!/usr/bin/env python3
"""Write the eval scaffold around an agent that already exists.

This is the second half of `/agent-sdk:agent-create`: the runner copy is the
machine, this is the paperwork it needs. Six things, none of them the agent:

* `evals/eval_config.json` — the model (env-driven, so it does not go stale),
  the isolation defaults, the judge block and the two tiers.
* `evals/smoke/` — one starter case with two free graders that hold for any
  agent: the run ended cleanly, and the reply is not a traceback. The prompt
  body is a TODO, because only the author knows what this agent does.
* `evals/mocks/README.md` — where mocked MCP tools go and why.
* `.env.example` — `CLAUDE_MODEL`, the two credential variables commented out,
  and `AGENT_ENTRY`. The SDK does not read `.env`; this file is the contract
  between the developer, CI and the next person.
* `tests/test_evals.py` — rendered from the `eval-ci` template, so a project
  that runs pytest gates on the suite without a workflow.
* `.gitignore` — `.env` and `evals/results/`, merged into an existing file
  rather than replacing it.

Nothing is written until the plan says so: `--dry-run` prints the write plan
and touches nothing, and a file that already exists is skipped unless
`--force`. The `.gitignore` is the exception: it is *merged*, never replaced.

    eval_scaffold.py <project> [--model M] [--judge-model M]
                     [--force] [--dry-run] [--json]

Exit codes: 0 planned or written, 1 written with warnings to act on (no agent
entry point, nothing was new), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import DEFAULT_MODEL, MODEL_ENV_VAR  # noqa: E402
from agent_sdk_skills.eval_config import default_config  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.templating import WriteItem, WritePlan, dumps_json, render_file  # noqa: E402

TEMPLATES = Path(__file__).resolve().parents[2] / "eval-ci" / "assets" / "templates"

GITIGNORE_LINES = (".env", "evals/results/")

SMOKE_PROMPT = """---
name: smoke
category: happy
tags: [happy, smoke]
runs: 1
max_turns: 6
---
TODO: replace this line with one real request in this agent's domain — the
simplest thing a user would actually ask for, phrased the way they would phrase
it. Keep it to one behaviour; a case that asks for three things cannot tell you
which one broke.
"""

TERMINAL_GRADER = """---
name: ends_cleanly
type: terminal
subtype: success
---
Proves the session finished its loop without erroring: the result message came
back with `subtype: success` rather than `error_max_turns`,
`error_during_execution` or `error_max_budget_usd`. When you size the case's
`max_turns`, count each turn with tool calls plus one for the final text-only
response; without that extra turn the run ends with `error_max_turns` and no
final response.

It does not prove the agent did the work, or did it well. A run that answered
"I cannot help with that" and stopped ends just as cleanly as one that did the
job. This is the floor every other grader in the case stands on — when it
fails, the others are usually noise.
"""

REGEX_GRADER = """---
name: no_traceback
type: regex
pattern: "Traceback \\\\(most recent call last\\\\)"
match: not_contains
target: last_message
---
Proves the agent did not hand the user a Python traceback. When a tool raises,
the error reaches the model as a tool result, and a model that has run out of
ideas will sometimes paste it into the reply verbatim.

It does not prove the run succeeded — an agent that failed silently, or
apologized without explaining, passes this. It is a cheap, always-true
assertion to start from; replace it with a check on what this agent is supposed
to say as soon as you know what that is.
"""

MOCKS_README = """# Mocked MCP tools

A mock replaces one MCP server with an in-process one whose answers are fixed,
so a case measures the agent's decisions instead of the backend's mood. Without
mocks a failing case has two possible causes and you cannot tell them apart.

Layout — one directory per server, one file per tool:

```
evals/mocks/<server>/<tool>.md
```

Each file is frontmatter plus a body:

```markdown
---
type: canned              # canned | agent
description: what the model is told this tool does
schema:                   # the input schema the in-process server advertises
  title: str
latency_ms: 40            # optional: what a slow backend feels like
---
{{input.title}}: 2 copies available; reserved by nobody.
```

Three things worth knowing before you write one:

* The model sees the tool as `mcp__<server>__<tool>`, and the trace records
  that name. Graders should use the qualified form.
* Input is validated against `schema` **before** the body is rendered, so a
  mock cannot observe malformed input unless its schema is permissive. That is
  usually what you want; when you are testing the agent's error handling,
  loosen the schema and set `error:` instead.
* A case opts in by name: `mocks: [<server>]` in its frontmatter. A mock for a
  server the agent no longer has is reported as MCP020, not silently ignored.

Generate a first draft from the agent's own tool schemas with
`/agent-sdk:eval-simulation` (`gen_mocks.py --from-agent`), then edit the
bodies — the generator knows the shapes, not the answers.
"""

ENV_EXAMPLE = f"""# Copy to `.env` and fill in. The Agent SDK does NOT read this file itself:
# export the variables, or load them with python-dotenv before building options.

# The model every run and every eval pins. Without it the SDK inherits Claude
# Code's default, which is not the same model on every machine or every week.
{MODEL_ENV_VAR}={DEFAULT_MODEL}

# Credential. Leave both unset to run on your Claude subscription (the stored
# `claude login`). An API key, when set, wins over the subscription and bills
# the API. `claude setup-token` mints an OAuth token for CI, tied to one
# person's plan.
# ANTHROPIC_API_KEY=sk-ant-...
# CLAUDE_CODE_OAUTH_TOKEN=...

# Entry point, if `build_options()` is not in `agent.py`. `module:function`.
# AGENT_ENTRY=agent:build_options
"""


def _gitignore_item(project: Path) -> WriteItem | None:
    """Merge the two lines in, or create the file. Never replace it."""
    path = project / ".gitignore"
    if not path.is_file():
        body = ("# Secrets and eval output.\n"
                + "\n".join(GITIGNORE_LINES) + "\n__pycache__/\n")
        return WriteItem(str(path), body, action="create",
                         reason="no .gitignore yet")
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError as exc:
        return WriteItem(str(path), "", action="skip", reason=f"unreadable: {exc}")
    present = {line.strip() for line in existing.splitlines()}
    missing = [line for line in GITIGNORE_LINES
               if line not in present and line.rstrip("/") not in present]
    if not missing:
        return None
    body = existing
    if not body.endswith("\n"):
        body += "\n"
    body += "\n# Added by /agent-sdk:agent-create — secrets and eval output.\n"
    body += "\n".join(missing) + "\n"
    return WriteItem(str(path), body, action="merge",
                     reason=f"appends {', '.join(missing)}; nothing existing is removed")


def build_plan(project: Path, *, model: str | None, judge_model: str | None,
               force: bool, entry: str) -> tuple[WritePlan, list[str]]:
    plan = WritePlan()
    warnings: list[str] = []
    evals = project / "evals"

    config = default_config(model=model, judge_model=judge_model, agent=entry)
    plan.add(evals / "eval_config.json", dumps_json(config), force=force,
             reason="pins the model, the isolation defaults, the judge and the two tiers")
    plan.add(evals / "smoke" / "prompt.md", SMOKE_PROMPT, force=force,
             reason="starter case; the body is a TODO only the author can fill in")
    plan.add(evals / "smoke" / "graders" / "ends_cleanly.md", TERMINAL_GRADER, force=force)
    plan.add(evals / "smoke" / "graders" / "no_traceback.md", REGEX_GRADER, force=force)
    plan.add(evals / "mocks" / "README.md", MOCKS_README, force=force)
    plan.add(project / ".env.example", ENV_EXAMPLE, force=force,
             reason="documentation, not secrets: every value here is a name or a default")

    template = TEMPLATES / "test_evals.py.tmpl"
    if template.is_file():
        rendered = render_file(template, {
            "PROJECT_NAME": project.name, "TIER": "pr", "MAX_COST": "5.00"})
        plan.add(project / "tests" / "test_evals.py", rendered, force=force,
                 reason="pytest gate over the pr tier; marked `evals` so `-m 'not evals'` skips it")
    else:                                    # pragma: no cover - the template ships with the plugin
        warnings.append(f"the eval-ci template is missing ({template}); no pytest gate written")

    item = _gitignore_item(project)
    if item is not None:
        plan.items.append(item)

    return plan, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--model", help=f"agent model (default: ${{{MODEL_ENV_VAR}:-{DEFAULT_MODEL}}})")
    parser.add_argument("--judge-model", help="judge model for `llm` graders")
    parser.add_argument("--force", action="store_true", help="replace files that already exist")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    warnings: list[str] = []
    entry = layout.entry_spec or "agent:build_options"
    if not layout.is_agent:
        warnings.append(
            "no agent module found here: the config will name `agent:build_options`, which "
            "nothing implements yet. This skill wraps an agent; it does not write one.")
    elif not layout.entry_spec:
        warnings.append(
            "no `build_options()` entry point: the runner cannot obtain the options to "
            "override them (AGT003). Expose one, or set `agent` in evals/eval_config.json.")

    plan, template_warnings = build_plan(
        project, model=args.model, judge_model=args.judge_model,
        force=args.force, entry=entry)
    warnings.extend(template_warnings)

    written = [] if args.dry_run else plan.apply()
    skipped = [i.path for i in plan.items if i.action == "skip"]
    if skipped and not args.force:
        warnings.append(
            f"{len(skipped)} file(s) already existed and were left alone; pass --force to "
            "replace them, or edit them by hand")

    payload = {
        "project": str(project),
        "entry": entry,
        "model": args.model or f"${{{MODEL_ENV_VAR}:-{DEFAULT_MODEL}}}",
        "judge_model": args.judge_model,
        "dry_run": args.dry_run,
        "plan": plan.to_dict(),
        "written": written,
        "warnings": warnings,
        "next": [
            "fill in evals/smoke/prompt.md with one real request",
            "install the runner copy: install_runner.py <project>",
            "validate: ../eval-review/scripts/validate_cases.py <project>",
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# eval_scaffold: {project}\n")
        print(plan.to_md())
        print()
        print(f"- entry point: `{entry}`")
        print(f"- model: `{payload['model']}`")
        if args.dry_run:
            print("\n_Dry run: nothing was written._")
        else:
            print(f"\n_Wrote {len(written)} file(s)._")
        for warning in warnings:
            print(f"\n- warning: {warning}")
        print("\nNext: " + "; ".join(payload["next"]))
    return EXIT_FINDINGS if warnings else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
