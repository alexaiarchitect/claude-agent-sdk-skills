#!/usr/bin/env python3
"""Print a design brief for an agent: the questions its design has to answer.

`design_check.py` reports what looks wrong. This lays the same facts out as
the four decisions Anthropic's agent-building articles keep returning to, so
a reviewer can walk the user through them:

  1. Tool inventory   every in-process tool, its description length, its
                      parameters, its server and the DSG ids it triggers
  2. Subagents        per AgentDefinition (and for "no subagents"): split by
                      context or by problem type, parallel disposable windows,
                      conflicting instructions — keep or fold, and the fold
                      procedure, one subagent at a time
  3. Verification     rules, then visual feedback, then an LLM judge, mapped to
                      this plugin's grader types
  4. Long-running     ceilings, compaction, init script, JSON feature list,
                      progress file, one feature per session, git checkpoints,
                      an end-to-end check at session start, generator and
                      evaluator kept apart

Detected facts are marked `yes`/`no`; what source cannot show is marked `ask`.
The brief makes no decision for the user. It reads source and file names
only; it never writes.

    design_brief.py <project> [--json] [--format json|md]

Exit codes: 0 brief printed, 2 nothing to brief (missing path, no SDK usage,
source that does not parse).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _design import (  # noqa: E402
    COMPACT_WINDOW_VAR, DOC_COMPACTION, DOC_SUBAGENTS, DOC_TURNS, TOOL_COUNT_WARN, LoadError,
    agent_signals, check, cite, load,
)
from agent_sdk_skills.report import EXIT_OK, EXIT_USAGE  # noqa: E402

KEEP_QUESTIONS = [
    {"question": "Is the split by context rather than by problem type?",
     "keep_if": "the work needs little from the rest of the conversation and returns a compact "
                "result (an independent research path, a black-box verification)",
     "fold_if": "it exists because a team or a topic owns it; that split loses context at every handoff"},
    {"question": "Does it need parallel, fresh, disposable context windows?",
     "keep_if": "several run at once, or each reads material the parent never needs to see",
     "fold_if": "it runs alone and its findings are needed in full by the next step"},
    {"question": "Does one loop measurably degrade from context bloat?",
     "keep_if": "an eval shows the single loop scoring worse on the same tasks",
     "fold_if": "nobody has measured it; then folding is the experiment"},
    {"question": "Would folding merge conflicting instructions or overload tool choice?",
     "keep_if": "the merged system prompt would contradict itself, or the main loop already "
                f"chooses among more than {TOOL_COUNT_WARN} tools",
     "fold_if": "its rules fit in a skill the main loop loads on demand"},
]

FOLD_PROCEDURE = [
    "Write task-completion evals first: even 10 golden examples; run each task more than once.",
    "Baseline: call the subagent as a tool from the main loop, so the main agent keeps the conversation.",
    "Fold one subagent at a time: its prompt becomes a skill, its API calls become MCP tools.",
    "Compare with and without it per task; look at which tasks flipped, not only the score.",
    "Keep it as a subagent only if the folded version scores worse; then repeat for the next.",
]

ADD_SUBAGENT_WHEN = [
    "breadth-first exploration over material the parent does not need (searches, large documents)",
    "independent paths that can run in parallel and each return a short summary",
    "black-box verification by a reviewer that must not share the generator's context",
]

VERIFICATION_LADDER = [
    {"rung": "1. Rules", "robustness": "most robust",
     "what": "explicit checks with a reason when they fail: schema validation, lint, a tool "
             "returning is_error with what to change",
     "graders": ["regex", "tool_used", "tool_order", "trajectory", "no_tool", "structured_output",
                 "final_text", "terminal", "budget", "hook_event", "file_exists"]},
    {"rung": "2. Visual feedback", "robustness": "for rendered output",
     "what": "screenshots or renders checked for layout and content, e.g. through a browser "
             "automation MCP server",
     "graders": ["file_exists (the rendered artifact)", "llm (judging the artifact)"]},
    {"rung": "3. LLM as judge", "robustness": "least robust, adds latency",
     "what": "a separate model grades fuzzy criteria such as tone; calibrate it with few-shot "
             "score breakdowns and keep it apart from the generator",
     "graders": ["llm"]},
]

#: What the brief cites each article for.
CITED_FOR = {
    1: "gather context, take action, verify; the verification ladder",
    2: "workflows against agents; poka-yoke tools",
    3: "a minimal tool set; compaction and note-taking",
    4: "tool descriptions, names, pagination and namespacing",
    7: "keep or fold a subagent; the fold procedure; 30-50 tool definitions",
    8: "init script, JSON feature list, progress file, one feature per session",
    9: "generator and evaluator kept apart",
    10: "what a subagent must be told; when multi-agent pays",
}


def long_running(subject, signals: dict[str, Any]) -> list[dict[str, str]]:
    root = subject.root if subject.root.is_dir() else subject.root.parent

    def present(*names: str) -> bool:
        return any((root / n).exists() for n in names)

    def in_git() -> bool:
        return any((d / ".git").exists() for d in [root, *list(root.parents)[:3]])

    def yn(flag: bool | None) -> str:
        return "ask" if flag is None else ("yes" if flag else "no")

    sources = signals.get("setting_sources")
    rules_survive = None if sources is None else ("project" in sources)
    agents = [a.name.lower() for a in subject.facts.agents]
    evaluator = any(word in name for name in agents for word in ("evaluat", "review", "qa", "verif"))
    return [
        {"item": "a ceiling ends a runaway loop (max_turns, max_budget_usd or a budget hook)",
         "status": yn(bool(signals) and bool(signals.get("max_turns") or signals.get("max_budget_usd")
                                             or signals.get("budget_hook"))),
         "why": "max_turns counts each turn with tool calls plus one for the final text-only response"},
        {"item": f"the compaction point is chosen ({COMPACT_WINDOW_VAR} in env)",
         "status": yn(bool(signals.get("compact_window"))) if signals else "ask",
         "why": "compaction keeps a run going but is lossy; set where it happens"},
        {"item": "a PreCompact hook archives the transcript before compaction",
         "status": yn(bool(signals.get("pre_compact_hook"))) if signals else "ask",
         "why": "the session log, not the context window, is what you recover from"},
        {"item": "persistent rules live in CLAUDE.md loaded through setting_sources",
         "status": yn(rules_survive),
         "why": "CLAUDE.md is re-injected on every request; early instructions may not survive compaction"},
        {"item": "an init script starts the environment (init.sh)",
         "status": yn(present("init.sh", "scripts/init.sh")),
         "why": "each session otherwise spends turns working out how to run the app"},
        {"item": "a feature list in JSON with passes: false per item",
         "status": yn(present("feature_list.json", "features.json")),
         "why": "the model is less likely to rewrite JSON than Markdown; sessions flip only `passes`"},
        {"item": "a progress file sessions read first and update last",
         "status": yn(present("claude-progress.txt", "progress.md", "PROGRESS.md", "NOTES.md")),
         "why": "a new session has no memory of the last one"},
        {"item": "one feature per session, ending in a clean, committed state", "status": "ask",
         "why": "one-shotting runs out of context mid-feature and leaves it half-built"},
        {"item": "git checkpoints with descriptive commits", "status": yn(in_git()),
         "why": "lets a session see what changed and revert a bad step"},
        {"item": "an end-to-end check at session start, as a user would", "status": "ask",
         "why": "unit tests and curl alone marked broken features as done"},
        {"item": "generator and evaluator kept apart for subjective quality",
         "status": "yes" if evaluator else "ask",
         "why": "a standalone evaluator tuned to be skeptical beats self-critique"},
    ]


def build(subject) -> dict[str, Any]:
    report, extra = check(subject)
    views = extra["views"]
    signals = extra["discovered"]["long_running"]
    subagents = []
    for agent in subject.facts.agents:
        sig = agent_signals(agent, subject.texts.get(agent.name))
        ids = sorted({f.id for f in report.findings
                      if f.id == "DSG007" and f"`{agent.name}`" in f.message})
        subagents.append({**sig, "findings": ids, "questions": KEEP_QUESTIONS,
                          "default": "fold, unless a question above is answered 'keep' with evidence"})
    return {
        "path": str(subject.root),
        "tools": [v.to_dict() for v in views],
        "reachable_tools": extra["discovered"]["reachable_tools"],
        "tool_count_threshold": TOOL_COUNT_WARN,
        "findings": [{"id": f.id, "severity": f.severity, "message": f.message} for f in report.findings],
        "summary": report.summary,
        "subagents": subagents,
        "no_subagents": {"applies": not subagents, "add_one_when": ADD_SUBAGENT_WHEN},
        "fold_procedure": FOLD_PROCEDURE,
        "verification_ladder": VERIFICATION_LADDER,
        "long_running": long_running(subject, signals),
        "sources": [cite(n, what) for n, what in CITED_FOR.items()]
                   + [DOC_SUBAGENTS, DOC_TURNS, DOC_COMPACTION],
    }


def render(brief: dict[str, Any]) -> str:
    out = [f"# Design brief: {brief['path']}", "",
           "Report only: nothing was written. `ask` marks what the source cannot show.", ""]

    out += ["## 1. Tool inventory", "",
            "| Tool | Server | Description | Params | Findings |", "|---|---|---|---|---|"]
    for t in brief["tools"]:
        params = ", ".join(t["params"]) if t["params_known"] else "(not readable)"
        out.append(f"| `{t['name']}` | {t['server'] or '-'} | {t['description_chars']} chars "
                   f"| {params or 'none'} | {', '.join(t['findings']) or '-'} |")
    if not brief["tools"]:
        out.append("| (no in-process tools) | | | | |")
    out += ["", f"Reachable tool definitions: {brief['reachable_tools']} "
                f"(tool choice tends to degrade past {brief['tool_count_threshold']}).", ""]

    out += ["## 2. Subagents: keep or fold", ""]
    for agent in brief["subagents"]:
        out += [f"### `{agent['name']}`", "",
                f"- tools scoped: {'yes' if agent['tools_scoped'] else 'no (inherits)'}; "
                f"maxTurns: {agent['max_turns'] if agent['max_turns'] is not None else 'none'}; "
                f"states what to return: "
                f"{'ask' if agent['states_output'] is None else ('yes' if agent['states_output'] else 'no')}"
                f"{' (' + ', '.join(agent['findings']) + ')' if agent['findings'] else ''}",
                "", "| Question | Keep if | Fold if | Answer |", "|---|---|---|---|"]
        for number, q in enumerate(agent["questions"], 1):
            answer = "ask"
            if number == 4 and brief["reachable_tools"] > brief["tool_count_threshold"]:
                answer = f"ask (signal: {brief['reachable_tools']} reachable tools)"
            out.append(f"| {q['question']} | {q['keep_if']} | {q['fold_if']} | {answer} |")
        out += ["", f"Default: {agent['default']}.", ""]
    if brief["no_subagents"]["applies"]:
        out += ["No subagents: the single loop is the default and usually the better one. "
                "Add one only for:", ""]
        out += [f"- {item}" for item in brief["no_subagents"]["add_one_when"]]
        out.append("")
    out += ["Fold procedure:", ""]
    out += [f"{i}. {step}" for i, step in enumerate(brief["fold_procedure"], 1)]
    out.append("")

    out += ["## 3. Verification ladder", "",
            "| Rung | Robustness | What | Graders in this plugin |", "|---|---|---|---|"]
    for rung in brief["verification_ladder"]:
        out.append(f"| {rung['rung']} | {rung['robustness']} | {rung['what']} "
                   f"| {', '.join(rung['graders'])} |")
    out.append("")

    out += ["## 4. Long-running checklist", "", "| Item | Status | Why |", "|---|---|---|"]
    for row in brief["long_running"]:
        out.append(f"| {row['item']} | {row['status']} | {row['why']} |")
    out.append("")

    s = brief["summary"]
    out += [f"design_check findings: {s['warnings']} warning(s), {s['infos']} note(s).", "",
            "Sources: " + "; ".join(brief["sources"]) + "."]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="project root or agent module")
    parser.add_argument("--format", choices=("json", "md"), default="md")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        help="print the brief as structured JSON instead of markdown")
    args = parser.parse_args(argv)

    try:
        subject = load(args.project)
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    brief = build(subject)
    print(json.dumps(brief, indent=2) if args.format == "json" else render(brief))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
