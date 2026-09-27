#!/usr/bin/env python3
"""Check that a project's CI workflows really gate on its Claude Agent SDK evals.

A workflow that looks like an eval gate and is not one is worse than no gate: it
turns "the evals pass" into something nobody verifies. The failures worth
catching are specific, and each has an id in the `CI0xx` band:

======  ==============================================================  ========
id      what                                                            severity
======  ==============================================================  ========
CI001   no workflow runs the eval runner                                error*
CI010   a runner step with no `--tier`, so the tier is whatever the
        config's default happens to be                                  warn
CI011   judge graders on the per-pull-request path                      warn
CI020   a credential written as a literal instead of ${{ secrets.* }}   error
CI021   no credential reaches the runner step                           error
CI030   neither `--max-cost-usd` nor `timeout-minutes`: nothing stops
        a runaway suite                                                 warn
CI031   no `--max-cost-usd` while spending a subscription's quota       info
CI040   `evals/results` is never uploaded or persisted                  info
CI050   `PYTHONPATH` does not carry `evals/runner`                      error
CI060   `claude-code-action` is the gate, so an agent decides what
        runs                                                           info
CI022   `--concurrency` above 1 on an OAuth token                      warn
======  ==============================================================  ========

\\* CI001 is an error when the project has eval cases and informational when it
has none: a project with nothing to score is not yet failing to score it.

**The YAML reader.** This plugin imports no third-party package, so workflows are
read by the small subset parser below: block mappings, block sequences, flow
sequences (`[a, b]`), literal and folded block scalars, and `#` comments. It does
not implement anchors, aliases, merge keys, multi-document streams, explicit
tags, quoted keys containing a colon, or multi-line flow collections, and it
keeps `on` as the string key `on` rather than resolving YAML 1.1's boolean. That
is enough for GitHub workflow files, which are written in that subset; anything
it cannot parse is reported as unparsed rather than silently passing.

    lint_workflows.py <project> [--json] [--strict]

Exit codes: 0 clean, 1 errors (with `--strict`, warnings count as errors),
2 usage error (the project does not exist).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills.eval_config import load_config, tier_graders  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport  # noqa: E402

DOCS_ACTIONS = "https://code.claude.com/docs/en/github-actions"
DOCS_ENV = "https://code.claude.com/docs/en/env-vars"
PLUGIN = "this plugin's skills/eval-ci/references/workflows.md"

#: A step whose `run` mentions one of these is running the eval suite.
RUNNER_MARKERS = ("agent_sdk_evals", "run_evals.py", "test_evals.py")
#: Env names that carry a credential to the CLI the SDK spawns.
CREDENTIAL_ENV = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
#: Backend switches that mean the credential comes from a cloud provider instead.
PROVIDER_ENV = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
#: `claude-code-action` inputs that carry the same credentials.
ACTION_CREDENTIAL_INPUTS = ("claude_code_oauth_token", "anthropic_api_key")

EXPRESSION = re.compile(r"\$\{\{.*?\}\}")
TIER_FLAG = re.compile(r"--tier[= ]+([A-Za-z0-9_-]+)")
CONCURRENCY_FLAG = re.compile(r"--concurrency[= ]+(\d+)")


# -- the YAML subset reader -------------------------------------------------

_KEY = re.compile(r"^(?P<key>[^:#\s][^:#]*):(?:\s+(?P<value>.*))?$")
_BLOCK_SCALARS = ("|", "|-", "|+", ">", ">-", ">+")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _significant(lines: list[str], i: int) -> int:
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            return i
        i += 1
    return len(lines)


def _strip_comment(value: str) -> str:
    quote: str | None = None
    for index, char in enumerate(value):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or value[index - 1] in " \t"):
            return value[:index].rstrip()
    return value.rstrip()


def _scalar(raw: str) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [] if not inner else [_scalar(part) for part in inner.split(",")]
    if raw in ("true", "True", "yes", "on"):
        return True
    if raw in ("false", "False", "no", "off"):
        return False
    if raw in ("null", "~", ""):
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def _read_block_scalar(lines: list[str], i: int, key_indent: int) -> tuple[str, int]:
    body: list[str] = []
    while i < len(lines):
        if lines[i].strip() == "":
            body.append("")
            i += 1
            continue
        if _indent(lines[i]) <= key_indent:
            break
        body.append(lines[i])
        i += 1
    widths = [_indent(line) for line in body if line.strip()]
    cut = min(widths) if widths else 0
    return "\n".join(line[cut:] if line.strip() else "" for line in body), i


def _parse_block(lines: list[str], i: int, indent: int | None) -> tuple[Any, int]:
    i = _significant(lines, i)
    if i >= len(lines):
        return None, i
    base = _indent(lines[i]) if indent is None else indent
    stripped = lines[i].strip()
    if stripped == "-" or stripped.startswith("- "):
        return _parse_seq(lines, i, base)
    return _parse_map(lines, i, base)


def _parse_child(lines: list[str], i: int, parent_indent: int) -> tuple[Any, int]:
    i = _significant(lines, i)
    if i >= len(lines):
        return None, i
    here = _indent(lines[i])
    stripped = lines[i].strip()
    if here > parent_indent:
        return _parse_block(lines, i, here)
    # A sequence may sit at the same column as the key that owns it.
    if here == parent_indent and (stripped == "-" or stripped.startswith("- ")):
        return _parse_seq(lines, i, here)
    return None, i


def _parse_map(lines: list[str], i: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while True:
        i = _significant(lines, i)
        if i >= len(lines) or _indent(lines[i]) != indent:
            break
        stripped = lines[i].strip()
        if stripped == "-" or stripped.startswith("- "):
            break
        match = _KEY.match(stripped)
        if not match:
            i += 1
            continue
        key = match.group("key").strip().strip("\"'")
        raw = _strip_comment((match.group("value") or "").strip())
        if raw in _BLOCK_SCALARS:
            out[key], i = _read_block_scalar(lines, i + 1, indent)
        elif raw == "":
            out[key], i = _parse_child(lines, i + 1, indent)
        else:
            out[key] = _scalar(raw)
            i += 1
    return out, i


def _parse_seq(lines: list[str], i: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while True:
        i = _significant(lines, i)
        if i >= len(lines) or _indent(lines[i]) != indent:
            break
        raw = lines[i]
        stripped = raw.strip()
        if not (stripped == "-" or stripped.startswith("- ")):
            break
        if stripped == "-":
            item, i = _parse_child(lines, i + 1, indent)
            out.append(item)
            continue
        rest = stripped[1:].lstrip()
        column = raw.index("-", indent) + 1
        column += len(raw[column:]) - len(raw[column:].lstrip(" "))
        if _KEY.match(rest):
            # Rewrite the item's first line as a plain mapping line at the
            # column its siblings already use, then parse it as one block.
            lines[i] = " " * column + rest
            item, i = _parse_block(lines, i, column)
        else:
            item, i = _scalar(_strip_comment(rest)), i + 1
        out.append(item)
    return out, i


def parse_workflow(text: str) -> dict[str, Any]:
    """The subset of YAML a GitHub workflow file uses. See the module docstring."""
    document, _ = _parse_block(text.splitlines(), 0, None)
    return document if isinstance(document, dict) else {}


# -- views over a parsed workflow ------------------------------------------

def triggers(document: dict[str, Any]) -> list[str]:
    value = document.get("on")
    if isinstance(value, dict):
        return sorted(str(k) for k in value)
    if isinstance(value, list):
        return sorted(str(v) for v in value)
    return [str(value)] if value else []


def jobs(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = document.get("jobs")
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if isinstance(v, dict)}


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    value = job.get("steps")
    return [s for s in value if isinstance(s, dict)] if isinstance(value, list) else []


def env_of(*scopes: dict[str, Any] | None) -> dict[str, str]:
    """Workflow, job and step `env` merged, later scopes winning."""
    merged: dict[str, str] = {}
    for scope in scopes:
        block = (scope or {}).get("env")
        if isinstance(block, dict):
            merged.update({str(k): "" if v is None else str(v) for k, v in block.items()})
    return merged


def is_runner_step(step: dict[str, Any]) -> bool:
    run = step.get("run")
    return isinstance(run, str) and any(marker in run for marker in RUNNER_MARKERS)


def is_literal(value: str) -> bool:
    """A credential value that is not an expression is baked into the file."""
    return bool(value.strip()) and not EXPRESSION.search(value)


# -- the checks ------------------------------------------------------------

def check(project: Path, report: GapReport) -> dict[str, Any]:
    layout = detect_layout(project)
    cases = layout.evals.case_count if layout.evals else 0
    config = load_config(project / "evals" / "eval_config.json")
    pr_tier_judges = config.ok and "judge" in tier_graders(config, "pr")

    directory = project / ".github" / "workflows"
    files = sorted(directory.glob("*.y*ml")) if directory.is_dir() else []
    facts: dict[str, Any] = {
        "workflows": [f.name for f in files], "cases": cases,
        "unparsed": [], "runner_steps": 0, "pr_tier_lists_judge": pr_tier_judges,
    }
    if pr_tier_judges:
        report.add(
            "CI011", "warn", "ci",
            "the `pr` tier in eval_config.json lists `judge` graders, so every pull request "
            "pays for judge calls",
            path=str(config.path),
            fix="move judge graders to the nightly tier: the pr tier should be free graders "
                "only (/agent-sdk:eval-criteria)",
            source=PLUGIN,
        )

    gating_steps = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            facts["unparsed"].append(f"{path.name}: {exc}")
            continue
        document = parse_workflow(text)
        if not document:
            facts["unparsed"].append(f"{path.name}: nothing this reader understands")
            continue
        gating_steps += _check_one(project, path, text, document, report,
                                  pr_tier_judges=pr_tier_judges)

    facts["runner_steps"] = gating_steps
    if gating_steps == 0:
        report.add(
            "CI001", "error" if cases else "info", "ci",
            "no workflow runs the eval runner, so nothing in CI checks the agent's behaviour"
            + (f" ({cases} case(s) exist and are never scored)" if cases
               else " (and there are no cases to score yet)"),
            path=str(directory),
            fix="generate the gate: `gen_workflows.py <project> --tier both`",
            source=PLUGIN,
        )
    return facts


def _check_one(project: Path, path: Path, text: str, document: dict[str, Any],
               report: GapReport, *, pr_tier_judges: bool) -> int:
    """Check one workflow file; return how many runner steps it has."""
    where = str(path)
    on = triggers(document)
    per_change = any(trigger in ("pull_request", "pull_request_target", "push") for trigger in on)
    found = 0

    for job_name, job in jobs(document).items():
        for index, step in enumerate(steps(job), start=1):
            locator = f"jobs.{job_name}.steps[{index}]"
            merged = env_of(document, job, step)
            uses = step.get("uses") if isinstance(step.get("uses"), str) else ""
            inputs = step.get("with") if isinstance(step.get("with"), dict) else {}

            # CI020 — a credential literal, in a step env or an action input.
            for name in CREDENTIAL_ENV:
                value = merged.get(name)
                if value is not None and is_literal(value):
                    report.add(
                        "CI020", "error", "ci",
                        f"`{name}` is set to a literal value in the workflow file",
                        path=where, locator=locator,
                        fix=f"use `${{{{ secrets.{name} }}}}`; a credential committed to a "
                            "workflow is in the repository history for good, and rotating it "
                            "means minting a new one",
                        source=DOCS_ACTIONS,
                    )
            for name in ACTION_CREDENTIAL_INPUTS:
                value = inputs.get(name)
                if isinstance(value, str) and is_literal(value):
                    report.add(
                        "CI020", "error", "ci",
                        f"the `{name}` input is a literal value, not a secret reference",
                        path=where, locator=locator,
                        fix=f"pass `${{{{ secrets.{name.upper()} }}}}`",
                        source=DOCS_ACTIONS,
                    )

            # CI060 — the action shape: useful for a narrative, not for a gate.
            if "claude-code-action" in uses:
                report.add(
                    "CI060", "info", "ci",
                    "this job runs `claude-code-action`, where an agent decides what to run: "
                    "useful for a written review, not a deterministic gate",
                    path=where, locator=locator,
                    fix="gate on a plain step running `python -m agent_sdk_evals run`, and keep "
                        "the action for the narrative if you want both",
                    source=DOCS_ACTIONS,
                )

            if not is_runner_step(step):
                continue
            found += 1
            run = str(step.get("run") or "")

            # CI050 — the runner is imported from the copy in the repository.
            pythonpath = merged.get("PYTHONPATH", "")
            inline = "PYTHONPATH=" in run
            if "evals/runner" not in pythonpath and not inline and "pip install" not in run:
                report.add(
                    "CI050", "error", "ci",
                    "the step runs the eval runner but PYTHONPATH does not carry "
                    "`evals/runner`, so it will fail at `import agent_sdk_evals`",
                    path=where, locator=locator,
                    fix="set `PYTHONPATH: evals/runner:.` in the step's env; the runner copy is "
                        "imported from the repository, never installed, and the trailing `.` "
                        "keeps the agent module importable",
                    source=PLUGIN,
                )

            # CI021 — a credential has to reach this step.
            has_credential = any(name in merged for name in CREDENTIAL_ENV)
            provider = [name for name in PROVIDER_ENV if name in merged]
            if not has_credential and not provider:
                report.add(
                    "CI021", "error", "ci",
                    "neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY reaches the runner "
                    "step, so every case will fail at the credential rather than on its merits",
                    path=where, locator=locator,
                    fix="add `CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}` "
                        "(from `claude setup-token`) or the ANTHROPIC_API_KEY equivalent; a "
                        "cloud backend switch instead needs that provider's own credentials",
                    source=DOCS_ENV,
                )
            subscription = ("CLAUDE_CODE_OAUTH_TOKEN" in merged
                            and "ANTHROPIC_API_KEY" not in merged and not provider)

            # CI010 — an implicit tier is an unknown cost.
            tier_match = TIER_FLAG.search(run)
            if not tier_match:
                report.add(
                    "CI010", "warn", "ci",
                    "the runner step passes no `--tier`, so what it runs (and what it costs) "
                    "depends on the config's default",
                    path=where, locator=locator,
                    fix="pass `--tier pr` on the per-change path and `--tier nightly` on the "
                        "schedule",
                    source=PLUGIN,
                )
            elif per_change and tier_match.group(1) in ("nightly", "judge"):
                report.add(
                    "CI011", "warn", "ci",
                    f"a per-change job runs `--tier {tier_match.group(1)}`, which pays judge "
                    "calls on every push or pull request",
                    path=where, locator=locator,
                    fix="run `--tier pr` here and keep the judged tier on a schedule",
                    source=PLUGIN,
                )

            # CI022 — every session is a full CLI child on the same credential.
            concurrency = CONCURRENCY_FLAG.search(run)
            if subscription and concurrency and int(concurrency.group(1)) > 1:
                report.add(
                    "CI022", "warn", "ci",
                    f"`--concurrency {concurrency.group(1)}` on an OAuth token: parallel "
                    "sessions draw on one plan's usage limits and reach a rejected rate limit "
                    "sooner, which marks runs NOT_EVALUATED",
                    path=where, locator=locator,
                    fix="use `--concurrency 1` on a subscription token, or move to an API key",
                    source=DOCS_ENV,
                )

            # CI030 / CI031 — something has to stop a runaway suite.
            ceiling = "--max-cost-usd" in run
            timeout = job.get("timeout-minutes")
            if not ceiling and not isinstance(timeout, int):
                report.add(
                    "CI030", "warn", "ci",
                    "no `--max-cost-usd` and no `timeout-minutes`: nothing stops a suite that "
                    "loops or a job that hangs",
                    path=where, locator=locator,
                    fix="pass `--max-cost-usd X` and set `timeout-minutes` on the job",
                    source=PLUGIN,
                )
            elif not ceiling and subscription:
                report.add(
                    "CI031", "info", "ci",
                    "no `--max-cost-usd` while spending a subscription's quota: the job's "
                    "timeout will stop it, but only after the plan's usage limits have taken "
                    "the hit",
                    path=where, locator=locator,
                    fix="pass `--max-cost-usd X`; on a subscription it is an estimate-based "
                        "ceiling on quota rather than on a bill",
                    source=PLUGIN,
                )

        # CI040 — a red pipeline with no artifact makes everyone re-run locally.
        if any(is_runner_step(step) for step in steps(job)):
            persisted = any(
                "upload-artifact" in str(step.get("uses") or "")
                or "actions/cache" in str(step.get("uses") or "")
                or "evals/results" in str(step.get("run") or "")
                for step in steps(job)
            )
            if not persisted:
                report.add(
                    "CI040", "info", "ci",
                    "`evals/results/` is neither uploaded nor otherwise persisted, so a failure "
                    "cannot be examined without re-running the suite",
                    path=where, locator=f"jobs.{job_name}",
                    fix="add `actions/upload-artifact@v4` with `path: evals/results/` and "
                        "`if: always()`",
                    source=PLUGIN,
                )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--strict", action="store_true",
                        help="count warnings as errors for the exit code")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_USAGE
    layout = detect_layout(target)
    project = Path(layout.project_root or target)

    report = GapReport(subject=str(project), skill="eval-ci")
    report.discovered = check(project, report)
    if args.strict:
        for finding in report.findings:
            if finding.severity == "warn":
                finding.severity = "error"

    print(report.to_json() if args.json else report.to_md())
    return EXIT_FINDINGS if report.has_errors() else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
