"""Shared analysis for `design_check.py` and `design_brief.py`.

Both scripts read an agent the same way `lint_harness.py` does — the syntax
tree, through `agent_sdk_skills.options_ast` — and judge the parts of it that
are *design* rather than wiring: what the model is shown about each tool, how
many tools it has to choose between, what a subagent is told to bring back, and
whether anything bounds or sustains a long run.

Every rule cites the Anthropic article it comes from (title, date, canonical
URL) and the `code.claude.com` page that states the current mechanics. The
articles give the reasoning; the docs say how the SDK behaves today. Where the
two differ, the docs win.

Not a script: the leading underscore keeps it out of the plugin's script list.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_sdk_skills.layout import detect_layout
from agent_sdk_skills.options_ast import AgentDef, ProjectFacts, ToolDef, extract_project
from agent_sdk_skills.report import GapReport, Option

# ---------------------------------------------------------------------------
# citations
# ---------------------------------------------------------------------------

#: The articles this skill draws on: canonical URL, current title, date.
#: Read 2026-10-29; `/engineering/` paths now 308 to `/research/`.
ARTICLES: dict[int, tuple[str, str, str]] = {
    1: ("https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk",
        "Building agents with the Claude Agent SDK", "2025-09-29"),
    2: ("https://www.anthropic.com/research/building-effective-agents",
        "Building effective AI agents", "2024-12-19"),
    3: ("https://www.anthropic.com/research/effective-context-engineering-for-ai-agents",
        "Effective context engineering for AI agents", "2025-09-29"),
    4: ("https://www.anthropic.com/research/writing-tools-for-agents",
        "Writing effective tools for AI agents", "2025-09-11"),
    5: ("https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills",
        "Equipping agents with Agent Skills", "2025-10-16"),
    6: ("https://www.anthropic.com/research/code-execution-with-mcp",
        "Code execution with MCP for efficient agents", "2025-11-04"),
    7: ("https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop",
        "Building agents: When to fold subagents into your main agent loop", "2026-10-22"),
    8: ("https://www.anthropic.com/research/effective-harnesses-for-long-running-agents",
        "Effective harnesses for long-running agents", "2025-11-26"),
    9: ("https://www.anthropic.com/research/harness-design-long-running-apps",
        "Harness design for long-running apps", "2026-03-24"),
    10: ("https://www.anthropic.com/research/multi-agent-research-system",
         "How we built our multi-agent research system", "2025-06-13"),
    11: ("https://www.anthropic.com/research/managed-agents",
         "Scaling Managed Agents with stable interfaces", "2026-04-08"),
}

DOCS = "https://code.claude.com/docs/en/agent-sdk"
DOC_CUSTOM_TOOLS = f"{DOCS}/custom-tools"
DOC_TOOL_ANNOTATIONS = f"{DOCS}/custom-tools#add-tool-annotations"
DOC_MCP_OUTPUT = f"{DOCS}/mcp#tool-output-exceeds-maximum-allowed-tokens"
DOC_TOOL_SEARCH = f"{DOCS}/tool-search"
DOC_SUBAGENTS = f"{DOCS}/subagents"
DOC_TURNS = f"{DOCS}/agent-loop#turns-and-budget"
DOC_COMPACTION = f"{DOCS}/agent-loop#automatic-compaction"
DOC_ENV_VARS = "https://code.claude.com/docs/en/env-vars"


def cite(number: int, what: str) -> str:
    """`<URL> ("Title", YYYY-MM-DD, what it is cited for)`."""
    url, title, date = ARTICLES[number]
    return f'{url} ("{title}", {date}, {what})'


def sources(*parts: str) -> str:
    return "; ".join(parts)


SRC = {
    "DSG001": sources(cite(4, "prompt-engineer tool descriptions as for a new hire"),
                      cite(2, "Appendix 2, the agent-computer interface"),
                      DOC_CUSTOM_TOOLS),
    "DSG002": sources(cite(4, "unambiguous parameter names: user_id, not user"),
                      cite(2, "Appendix 2, poka-yoke the arguments"),
                      DOC_CUSTOM_TOOLS),
    "DSG003": sources(cite(4, "search over list; pagination, filtering and truncation defaults"),
                      DOC_MCP_OUTPUT),
    "DSG004": sources(cite(4, "namespacing related tools by service and resource"),
                      f"{DOCS}/mcp#tool-naming-convention"),
    "DSG005": sources(cite(3, "bloated tool sets with overlapping functionality"),
                      cite(4, "each tool needs a clear, distinct purpose"),
                      DOC_CUSTOM_TOOLS),
    "DSG006": sources(cite(7, "tool choice degrades past 30-50 tool definitions"),
                      cite(3, "a minimal viable tool set"),
                      DOC_TOOL_SEARCH),
    "DSG007": sources(cite(10, "each subagent needs an objective, an output format, tool guidance "
                               "and task boundaries"),
                      cite(7, "split by context, return a compact result"),
                      DOC_SUBAGENTS),
    "DSG008": sources(cite(8, "sessions with no memory of the last; compaction is not enough"),
                      cite(3, "compaction, note-taking and sub-agents for long horizons"),
                      DOC_TURNS, DOC_COMPACTION),
}

# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

#: DSG001: the floor below which a description cannot say when to use a tool,
#: what it returns and how it differs from its neighbours.
MIN_DESCRIPTION = 40
#: DSG002: parameter names the model has to guess the meaning of.
AMBIGUOUS_PARAMS = ("id", "user", "data", "input", "value", "item", "obj")
#: DSG003: names that promise "everything".
LIST_LIKE = re.compile(r"(?:^|_)(list|get_all|fetch|dump)_")
#: DSG003: any of these tokens in a parameter name bounds the response.
BOUNDING_TOKENS = {"limit", "page", "offset", "query", "filter", "max", "results",
                   "cursor", "q", "search", "size", "top", "since", "until"}
#: DSG004: the SDK already prefixes every in-process tool with
#: `mcp__<server>__`; at three tools that is namespace enough. From four on,
#: resource-level naming is what lets the model tell them apart.
NAMESPACE_MIN_TOOLS = 4
#: DSG005: verbs that mean "read me something" to a model.
READ_VERBS = {"find", "search", "lookup", "look", "get", "fetch", "query", "retrieve",
              "read", "show", "locate"}
FILLER = {"by", "the", "a", "an", "for", "of", "info", "details", "up"}
#: DSG006: the low end of the 30-50 range in article #7.
TOOL_COUNT_WARN = 30
#: DSG007: any of these suggests an output format, an objective or a boundary.
DELEGATION_WORDS = re.compile(
    r"\b(return\w*|report\w*|output\w*|format\w*|only|do not|don't|never|scope\w*)\b",
    re.IGNORECASE,
)
COMPACT_WINDOW_VAR = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
BUDGET_HOOK = re.compile(r"budget|cost|spend", re.IGNORECASE)

#: Claude Code's own tool names; DSG006 counts only what the agent adds.
BUILT_IN_TOOLS = {
    "Agent", "Task", "Bash", "BashOutput", "Edit", "Glob", "Grep", "KillBash", "KillShell",
    "LS", "MultiEdit", "NotebookEdit", "NotebookRead", "Read", "SendMessage", "Skill",
    "TaskStop", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch", "Write",
    "AskUserQuestion", "ExitPlanMode", "ListMcpResources", "ReadMcpResource", "Monitor",
}

# ---------------------------------------------------------------------------
# facts beyond options_ast
# ---------------------------------------------------------------------------


@dataclass
class AgentText:
    """The literal `description` and `prompt` of one subagent, when knowable."""

    name: str
    description: str | None = None
    prompt: str | None = None
    lineno: int = 0
    path: str | None = None


@dataclass
class ToolView:
    """One in-process tool as the model sees it."""

    name: str
    func: str
    description: str
    params: list[str]
    params_known: bool
    server: str | None
    path: str | None
    lineno: int
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "function": self.func, "server": self.server,
            "description_chars": len(self.description), "params": self.params,
            "params_known": self.params_known, "path": self.path, "lineno": self.lineno,
            "findings": sorted(set(self.findings)),
        }


def _string_of(node: ast.AST | None, constants: dict[str, ast.AST], depth: int = 0) -> str | None:
    """A string literal, a module constant, a concatenation or a dedent of one."""
    if node is None or depth > 8:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.Name) and node.id in constants:
        return _string_of(constants[node.id], constants, depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_of(node.left, constants, depth + 1)
        right = _string_of(node.right, constants, depth + 1)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Call) and node.args:
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in ("dedent", "cleandoc", "strip"):
            return _string_of(node.args[0], constants, depth + 1)
    return None


def agent_texts(paths: list[str]) -> dict[str, AgentText]:
    """Read each `agents={"name": AgentDefinition(...)}` entry's prose."""
    found: dict[str, AgentText] = {}
    for path in paths:
        try:
            tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        constants: dict[str, ast.AST] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                constants[stmt.targets[0].id] = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value:
                constants[stmt.target.id] = stmt.value
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                fields: dict[str, ast.AST] = {}
                if isinstance(value, ast.Call):
                    callee = value.func.attr if isinstance(value.func, ast.Attribute) else getattr(value.func, "id", "")
                    if callee != "AgentDefinition":
                        continue
                    fields = {k.arg: k.value for k in value.keywords if k.arg}
                else:
                    continue
                found[key.value] = AgentText(
                    name=key.value,
                    description=_string_of(fields.get("description"), constants),
                    prompt=_string_of(fields.get("prompt"), constants),
                    lineno=getattr(value, "lineno", 0), path=path,
                )
    return found


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


class LoadError(Exception):
    """Nothing to judge: a missing path, no SDK usage, or unparseable source."""


@dataclass
class Subject:
    root: Path
    facts: ProjectFacts
    texts: dict[str, AgentText]


def load(target_arg: str) -> Subject:
    target = Path(target_arg).expanduser()
    if not target.exists():
        raise LoadError(f"{target} does not exist")
    layout = detect_layout(target)
    root = Path(layout.project_root or target)
    facts = extract_project(target if target.is_file() else root)
    broken = [m for m in facts.modules if m.syntax_error]
    if broken:
        raise LoadError("could not parse "
                        + ", ".join(f"{m.path} ({m.syntax_error})" for m in broken)
                        + "; a design review reads the source, so fix the syntax first")
    if not facts.modules:
        raise LoadError(f"no Claude Agent SDK usage under {target} "
                        "(no module imports claude_agent_sdk)")
    return Subject(root=root, facts=facts, texts=agent_texts([m.path for m in facts.modules]))


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[_\-\s]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()) if t]


def _singular(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tool_views(facts: ProjectFacts) -> list[ToolView]:
    server_of: dict[str, str] = {}
    for server in facts.sdk_servers:
        for ref in server.tool_refs:
            if server.name:
                server_of.setdefault(ref, server.name)
    views: list[ToolView] = []
    for tool in facts.tools:
        known = tool.schema_kind in ("types", "json_schema", "missing")
        views.append(ToolView(
            name=tool.tool_name or tool.func_name, func=tool.func_name,
            description=(tool.description or "").strip() if isinstance(tool.description, str) else "",
            params=list(tool.schema_keys) if known else [], params_known=known,
            server=server_of.get(tool.func_name), path=tool.path, lineno=tool.lineno,
        ))
    return views


def _signature(name: str, namespace: set[str]) -> tuple[str, tuple[str, ...]]:
    tokens = [t for t in _tokens(name) if t not in namespace and t not in FILLER]
    if not tokens:
        return "", ()
    verb = tokens[0]
    verb = "find" if verb in READ_VERBS else verb
    return verb, tuple(sorted({_singular(t) for t in tokens[1:]}))


def _shared(tokens_per_tool: list[list[str]], position: int) -> str | None:
    picks = {_singular(t[position]) for t in tokens_per_tool if t}
    if len(picks) == 1 and all(tokens_per_tool):
        return picks.pop()
    return None


def reachable_tool_names(facts: ProjectFacts, views: list[ToolView]) -> list[str]:
    """In-process tools plus MCP tools pre-approved by name; built-ins excluded."""
    names = set(facts.tool_names())
    if not names:
        names = {f"mcp__{v.server or '?'}__{v.name}" for v in views}
    primary = facts.primary
    if primary is not None:
        for entry in primary.str_list("allowed_tools"):
            if entry in BUILT_IN_TOOLS or "(" in entry:
                continue
            parts = entry.split("__")
            if entry.startswith("mcp__") and len(parts) >= 3 and parts[2] and parts[2] != "*":
                names.add(entry)
    return sorted(names)


def check(subject: Subject) -> tuple[GapReport, dict[str, Any]]:
    facts = subject.facts
    report = GapReport(subject=str(subject.root), skill="agent-design")
    views = tool_views(facts)
    by_func = {v.func: v for v in views}

    def add(view: ToolView | None, fid: str, severity: str, message: str, fix: str,
            *, path: str | None = None, lineno: int = 0, area: str = "tools") -> None:
        if view is not None:
            view.findings.append(fid)
            path, lineno = view.path, view.lineno
        report.add(fid, severity, area, message, path=path,
                   locator=f"line {lineno}" if lineno else None, fix=fix, source=SRC[fid])

    # DSG001 / DSG002 / DSG003: one tool at a time.
    for view in views:
        if len(view.description) < MIN_DESCRIPTION:
            shown = f"{len(view.description)} characters" if view.description else "no description"
            add(view, "DSG001", "warn",
                f"tool `{view.name}` has {shown}; the model chooses tools from their descriptions",
                f"write at least {MIN_DESCRIPTION} characters: when to use it, what it returns, "
                "input formats, and how it differs from its neighbours, as you would brief a new hire")
        if view.params_known:
            vague = [p for p in view.params if p.lower() in AMBIGUOUS_PARAMS]
            if vague:
                add(view, "DSG002", "warn",
                    f"tool `{view.name}` takes ambiguous parameter(s) {', '.join(vague)}",
                    "name what the value is: `book_id`, `member_id`, `isbn`, not `id`; the model "
                    "fills arguments by reading names, and a vague one invites a guess")
            if LIST_LIKE.search(view.name):
                tokens = {t for p in view.params for t in _tokens(p)}
                if not tokens & BOUNDING_TOKENS:
                    add(view, "DSG003", "warn",
                        f"tool `{view.name}` reads like \"return everything\" and has no "
                        "limit, page, offset, query or filter parameter",
                        "prefer a search tool (`search_<resource>` with `query` and `limit`), or "
                        "paginate with a sensible default; MCP results over 25,000 tokens are "
                        "written to a file and replaced by an error the agent has to recover from")

    # DSG004: one server's tools with no common name part.
    for server in facts.sdk_servers:
        members = [by_func[r] for r in server.tool_refs if r in by_func]
        if len(members) < NAMESPACE_MIN_TOOLS:
            continue
        tokens = [_tokens(m.name) for m in members]
        prefix = _shared(tokens, 0)
        suffix = _shared([t[::-1] for t in tokens], 0)
        if prefix is None and suffix is None:
            add(None, "DSG004", "warn",
                f"server `{server.name}` exposes {len(members)} tools "
                f"({', '.join(m.name for m in members)}) with no shared prefix or suffix",
                "namespace by resource and action (`catalog_search`, `catalog_get`, "
                "`reservation_create`, `reservation_cancel`) and let your evals decide prefix "
                "against suffix; the `mcp__<server>__` prefix only separates servers",
                path=server.path, lineno=server.lineno)
            for member in members:
                member.findings.append("DSG004")

    # DSG005: two names a person could not tell apart.
    namespace = set()
    for server in facts.sdk_servers:
        members = [by_func[r] for r in server.tool_refs if r in by_func]
        tokens = [_tokens(m.name) for m in members]
        if len(members) >= 2:
            shared = _shared(tokens, 0)
            if shared:
                namespace.add(shared)
    signatures = [(v, _signature(v.name, namespace)) for v in views]
    clusters: list[list[ToolView]] = []
    seen: set[str] = set()
    for i, (left, (lverb, lnouns)) in enumerate(signatures):
        if left.name in seen or not lverb:
            continue
        group = [left]
        for right, (rverb, rnouns) in signatures[i + 1:]:
            if right.name in seen or rverb != lverb:
                continue
            if lnouns == rnouns or not lnouns or not rnouns:
                group.append(right)
        if len(group) > 1:
            seen.update(v.name for v in group)
            clusters.append(group)
    for group in clusters:
        names = ", ".join(f"`{v.name}`" for v in group)
        add(None, "DSG005", "warn",
            f"tools {names} overlap: same action on the same thing, as far as their names say",
            "consolidate into one tool with clear parameters, or rename and re-describe each so "
            "a person could say which one a request needs; overlapping tools split the model's choice",
            path=group[0].path, lineno=group[0].lineno)
        for view in group:
            view.findings.append("DSG005")

    # DSG006: how many tools the model has to choose between.
    reachable = reachable_tool_names(facts, views)
    if len(reachable) > TOOL_COUNT_WARN:
        primary = facts.primary
        add(None, "DSG006", "warn",
            f"{len(reachable)} tool definitions are reachable (in-process plus MCP tools named "
            f"in allowed_tools, built-ins excluded); above {TOOL_COUNT_WARN} tool choice tends to degrade",
            "group tools by user intent rather than one per API endpoint, drop what no eval task "
            "uses, and keep tool search on so schemas load on demand",
            path=primary.path if primary else None, lineno=primary.lineno if primary else 0,
            area="tools")

    # DSG007: what a subagent is told to bring back.
    for agent in facts.agents:
        text = subject.texts.get(agent.name)
        prose = " ".join(filter(None, [text.prompt if text else None,
                                       text.description if text else None]))
        if text is None or (text.prompt is None and text.description is None):
            continue
        if not DELEGATION_WORDS.search(prose):
            add(None, "DSG007", "info",
                f"subagent `{agent.name}`: its prompt and description name no output format, "
                "objective or boundary (no return/report/output/format/only/do not/scope)",
                "say what to return and in what shape (\"return at most five titles as "
                "`title — shelf mark`\"), which tools or sources to use, and what is out of scope; "
                "the parent sees only the final message",
                path=text.path, lineno=text.lineno or agent.lineno, area="subagents")

    # DSG008: nothing bounds or sustains a long run.
    primary = facts.primary
    long_running: dict[str, Any] = {}
    if primary is not None:
        has_turns = primary.has("max_turns")
        has_budget = primary.has("max_budget_usd")
        budget_hook = any(BUDGET_HOOK.search(cb) for h in facts.hooks for cb in h.callbacks)
        env = primary.get("env")
        env_known = env is None or env.is_known
        compact_set = bool(env is not None and COMPACT_WINDOW_VAR in env.as_dict())
        pre_compact = any(h.event == "PreCompact" for h in facts.hooks)
        long_running = {"max_turns": has_turns, "max_budget_usd": has_budget,
                        "budget_hook": budget_hook, "compact_window": compact_set,
                        "pre_compact_hook": pre_compact,
                        "setting_sources": primary.str_list("setting_sources") if primary.has("setting_sources") else None}
        missing: list[str] = []
        if not (has_turns or has_budget or budget_hook):
            missing.append("no max_turns, no max_budget_usd and no budget hook, so nothing ends a runaway loop")
        if env_known and not compact_set:
            missing.append(f"{COMPACT_WINDOW_VAR} is not set in env, so compaction happens at the default point")
        if missing:
            fixes: list[str] = []
            if not (has_turns or has_budget or budget_hook):
                fixes.append("set max_turns (count each turn with tool calls plus one for the "
                             "final text-only response) or max_budget_usd")
            if env_known and not compact_set:
                fixes.append(f"if a run can outgrow one window, choose the compaction point with "
                             f"{COMPACT_WINDOW_VAR} in env and archive with a PreCompact hook")
            fixes.append("for work that spans sessions, plan the handoff (progress file, JSON "
                         "feature list, git checkpoints): agent-design "
                         "references/long-running-harness.md")
            add(None, "DSG008", "info", "long-running signals: " + "; ".join(missing),
                "; ".join(fixes), path=primary.path, lineno=primary.lineno, area="long-running")

    discovered = {
        "tools": [v.to_dict() for v in views],
        "servers": [{"name": s.name, "tools": s.tool_refs} for s in facts.sdk_servers],
        "reachable_tools": len(reachable),
        "subagents": [a.name for a in facts.agents],
        "long_running": long_running,
    }
    report.discovered = {
        "tools": [f"{v.name} ({len(v.description)} chars; params: {', '.join(v.params) or 'none'})"
                  for v in views],
        "servers": [f"{s.name}: {', '.join(s.tool_refs) or '(dynamic)'}" for s in facts.sdk_servers],
        "reachable tool definitions": len(reachable),
        "subagents": [a.name for a in facts.agents],
    }
    if report.findings:
        report.add_option(Option(
            key="1", label="Walk through the design brief", recommended=True,
            detail="design_brief.py turns these findings into the tool table, the keep-or-fold "
                   "decision per subagent, the verification ladder and the long-running checklist",
        ))
    report.add_option(Option(
        key=str(len(report.options) + 1), label="Check the wiring",
        detail="hooks, permissions, MCP servers and subagent ceilings: /agent-sdk:agent-harness",
    ))
    return report, {"views": views, "agents": facts.agents, "discovered": discovered}


def agent_signals(agent: AgentDef, text: AgentText | None) -> dict[str, Any]:
    prose = " ".join(filter(None, [text.prompt if text else None, text.description if text else None]))
    return {
        "name": agent.name,
        "tools_scoped": agent.has_tools,
        "tools": agent.tools.as_str_list() if agent.tools else None,
        "max_turns": agent.max_turns.value if agent.max_turns else None,
        "model": agent.model.as_str() if agent.model else None,
        "states_output": bool(DELEGATION_WORDS.search(prose)) if prose else None,
    }


__all__ = [
    "ARTICLES", "SRC", "LoadError", "Subject", "ToolDef", "agent_signals", "check", "cite", "load",
]
