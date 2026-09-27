"""Which rules in the agent's system prompt does the eval suite actually test?

A suite can have twenty cases and still prove nothing about the one rule that
matters, because cases are written from what the agent *does* and rules are
written from what it *must*. This module puts the two lists side by side.

Four questions, four functions:

* :func:`extract_rules` — what does the system prompt oblige the agent to do?
  Numbered and bulleted rules, each flagged as a refusal (`never`, `refuse`,
  `do not`) or an ordering rule (`before`, `only after`, `first`).
* :func:`matrix` — which rules has at least one case aimed at?
* :func:`shape` — does the suite have the mix of categories that makes a
  regression suite rather than a demo (one of each, adversarial at least a
  fifth)?
* :func:`n_plus_one_gaps` — every refusal rule needs a case that *tries* to
  break it, scored by something that cannot be talked out of: a `no_tool`
  grader or an EXACT trajectory. A refusal proved only by a judge reading the
  reply is a refusal proved by a second model's opinion.

Honesty rules, because the alternative is a matrix that looks complete:

* The rules come from a **literal** system prompt read with :mod:`ast`. When
  the prompt is built at runtime — a f-string over a database, a file read, a
  `{"type": "preset"}` mapping — :func:`read_system_prompt` returns kind
  ``dynamic`` and every consumer reports "unknown" rather than zero rules.
* A rule is "covered" when a case mentions its tool or one of its key phrases.
  That is evidence a case was *aimed* at the rule, never evidence the rule
  holds. The reports say so, and coverage gaps are advice, not failures.

Standard library only: this is plugin-side code and must run before the
project's environment does.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import SUBAGENT_TOOL_NAMES, SYNTHETIC_TOOLS
from . import evalcase, graders as graders_mod

__all__ = [
    "Rule", "SystemPrompt", "extract_rules", "read_system_prompt",
    "summarize_cases", "matrix", "shape", "n_plus_one_gaps", "tool_coverage",
    "TARGET_SHAPE", "ADVERSARIAL_SHARE", "UNKNOWN",
]

#: What a consumer prints when the system prompt could not be read statically.
UNKNOWN = "unknown"

#: The categories a suite should carry at least one of, and the share of the
#: suite adversarial cases should reach. Both are defaults a caller may raise;
#: neither is a law, which is why `shape` returns advice and not a verdict.
TARGET_SHAPE = evalcase.CATEGORIES
ADVERSARIAL_SHARE = 0.20

#: A rule line: `1.` / `1)` / `-` / `*` / `•`, then the text.
_BULLET = re.compile(r"^\s*(?:(\d+)[.)]|[-*•])\s+(?P<text>\S.*)$")
#: A continuation of the previous rule: indented, no marker of its own.
_CONTINUATION = re.compile(r"^\s{2,}\S")

#: Obligation words that make a bare sentence a rule when nothing is numbered.
_OBLIGATION = re.compile(
    r"\b(?:must|never|always|do not|don't|only|refuse|decline|shall|should not|"
    r"may not|cannot|are not to|before you|after you)\b", re.I)

_REFUSAL = re.compile(
    r"\b(?:never|refuse|refuses|refusal|decline|declines|reject|rejects|"
    r"do not|don't|must not|may not|cannot|can't|shall not|without|"
    r"under no circumstances|avoid)\b", re.I)

_ORDERING = re.compile(
    r"\b(?:only after|before|after|first|then|prior to|once you have|"
    r"until|followed by|precede[sd]?)\b", re.I)

#: Tool-ish tokens: an MCP-qualified name, a backticked identifier, a
#: snake_case identifier, or one of the CLI's CamelCase built-ins.
_MCP_TOOL = re.compile(r"\bmcp__[A-Za-z0-9_]+__[A-Za-z0-9_]+\b")
_BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:__[A-Za-z0-9_]+)*)`")
_SNAKE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")
_BUILTIN_TOOLS = (
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch",
    "NotebookEdit", "TodoWrite", "Task", "Agent", "Skill",
)

_STOPWORDS = frozenset("""
a an and are as at be been before but by can cannot do does doing done for from
had has have if in into is it its may must never no not of on once only or
other should so than that the their them then there these they this to under
until up use used user very was were what when which while who will with would
you your yours agent always
""".split())


@dataclass
class Rule:
    """One obligation read out of the system prompt.

    `index` is the rule's position in the prompt, so a report can say "rule 2"
    the way the prompt does. `tools` and `phrases` are what a case has to
    mention for the rule to count as *aimed at*, never as *proved*.
    """

    index: int
    text: str
    is_refusal: bool = False
    is_ordering: bool = False
    tools: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    kind: str = "bullet"          # bullet | numbered | sentence

    @property
    def id(self) -> str:
        return f"rule-{self.index}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.id
        return data


@dataclass
class SystemPrompt:
    """The prompt text, and how much of it could actually be read."""

    text: str | None = None
    kind: str = "absent"          # literal | dynamic | absent | unreadable
    path: str | None = None
    locator: str | None = None
    note: str | None = None

    @property
    def readable(self) -> bool:
        return self.kind == "literal" and bool((self.text or "").strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "path": self.path, "locator": self.locator,
            "chars": len(self.text or ""), "readable": self.readable,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# reading the prompt
# ---------------------------------------------------------------------------

def _string_value(node: ast.AST | None) -> str | None:
    """A literal string, including implicit and `+` concatenation."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_value(node.left)
        right = _string_value(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _from_module(tree: ast.AST, path: str) -> SystemPrompt | None:
    """`SYSTEM_PROMPT = "..."` at module level, and the `system_prompt=` kwarg.

    `options_ast` reports the *kind* of a system prompt but never its text, so
    this reader exists here rather than there. It parses; it never executes.
    """
    constants: dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                constants[node.target.id] = node.value

    for name in ("SYSTEM_PROMPT", "SYSTEM_PROMPT_TEXT", "PROMPT", "INSTRUCTIONS"):
        text = _string_value(constants.get(name))
        if text and text.strip():
            return SystemPrompt(text=text, kind="literal", path=path, locator=name)

    dynamic: SystemPrompt | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "system_prompt":
            continue
        value = node.value
        text = _string_value(value)
        if text is None and isinstance(value, ast.Name):
            text = _string_value(constants.get(value.id))
        if text and text.strip():
            return SystemPrompt(text=text, kind="literal", path=path,
                                locator="system_prompt=")
        if isinstance(value, ast.Dict):
            for key, item in zip(value.keys, value.values):
                if isinstance(key, ast.Constant) and key.value == "append":
                    appended = _string_value(item)
                    if appended and appended.strip():
                        return SystemPrompt(
                            text=appended, kind="literal", path=path,
                            locator="system_prompt.append",
                            note="only the appended text is literal; the preset it extends "
                                 "is Claude Code's own prompt and is not readable here")
        dynamic = SystemPrompt(
            text=None, kind="dynamic", path=path, locator="system_prompt=",
            note="the prompt is built at runtime (an f-string, a variable, a preset or a "
                 "file), so its rules cannot be listed without running the agent")
    return dynamic


def read_system_prompt(target: Path | str) -> SystemPrompt:
    """The agent's system prompt, read with `ast` and never executed.

    `target` may be a module or a project directory; in a directory the modules
    that import the SDK are tried first, `agent.py` before the rest.
    """
    path = Path(target).expanduser()
    if path.is_file():
        candidates = [path]
    elif path.is_dir():
        from .layout import find_agent_modules

        found = [Path(usage.path) for usage in find_agent_modules(path)]
        if not found:
            found = sorted(p for p in path.glob("*.py") if p.name != "setup.py")
        candidates = sorted(found, key=lambda p: (p.name != "agent.py", str(p)))
    else:
        return SystemPrompt(kind="absent", note=f"{path} does not exist")

    fallback: SystemPrompt | None = None
    for candidate in candidates:
        try:
            tree = ast.parse(candidate.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError) as exc:
            fallback = fallback or SystemPrompt(
                kind="unreadable", path=str(candidate), note=str(exc))
            continue
        found = _from_module(tree, str(candidate))
        if found is None:
            continue
        if found.readable:
            return found
        fallback = fallback or found
    return fallback or SystemPrompt(
        kind="absent",
        note="no literal system prompt found; the agent may rely on Claude Code's default")


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def _tools_in(text: str) -> list[str]:
    found: list[str] = []
    for match in _MCP_TOOL.finditer(text):
        found.append(match.group(0))
    for match in _BACKTICKED.finditer(text):
        found.append(match.group(1))
    for match in _SNAKE.finditer(text):
        found.append(match.group(1))
    for name in _BUILTIN_TOOLS:
        if re.search(rf"\b{name}\b", text):
            found.append(name)
    out: list[str] = []
    for name in found:
        if len(name) > 2 and name not in out:
            out.append(name)
    return out


def _phrases_in(text: str, *, limit: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_'-]+", text.lower())
    keep: list[str] = []
    for word in words:
        bare = word.strip("'-")
        if len(bare) < 4 or bare in _STOPWORDS or bare in keep:
            continue
        keep.append(bare)
        if len(keep) >= limit:
            break
    return keep


def _make_rule(index: int, text: str, kind: str) -> Rule:
    clean = " ".join(text.split())
    return Rule(
        index=index,
        text=clean,
        is_refusal=bool(_REFUSAL.search(clean)),
        is_ordering=bool(_ORDERING.search(clean)),
        tools=_tools_in(clean),
        phrases=_phrases_in(clean),
        kind=kind,
    )


def extract_rules(system_prompt_text: str | None) -> list[Rule]:
    """The numbered or bulleted obligations in a system prompt.

    Bullets and numbered items are the rules; an indented line continues the
    one above it. A prompt written as prose has no markers, so sentences
    carrying an obligation word (`must`, `never`, `only`, `before you`) are
    used instead — marked `kind="sentence"`, because that fallback is a guess
    and a report should say which it is looking at.
    """
    text = system_prompt_text or ""
    if not text.strip():
        return []

    collected: list[tuple[str, str]] = []      # (text, kind)
    for raw in text.splitlines():
        match = _BULLET.match(raw)
        if match:
            kind = "numbered" if match.group(1) else "bullet"
            collected.append([match.group("text"), kind])  # type: ignore[arg-type]
            continue
        if collected and _CONTINUATION.match(raw) and raw.strip():
            collected[-1][0] += " " + raw.strip()          # type: ignore[index]

    if collected:
        return [_make_rule(i, item[0], item[1]) for i, item in enumerate(collected, start=1)]

    rules: list[Rule] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n{2,}", text):
        clean = sentence.strip()
        if len(clean) < 12 or not _OBLIGATION.search(clean):
            continue
        rules.append(_make_rule(len(rules) + 1, clean, "sentence"))
    return rules


# ---------------------------------------------------------------------------
# cases
# ---------------------------------------------------------------------------

def _case_tools(case: evalcase.LoadedCase) -> list[str]:
    names: list[str] = []
    for grader in case.graders:
        for name in graders_mod.grader_tool_names(grader.meta):
            normalized = graders_mod.normalize_tool_name(name)
            if normalized not in names:
                names.append(normalized)
    return names


def _case_text(case: evalcase.LoadedCase) -> str:
    parts = [case.name, case.body or "", " ".join(case.turns), " ".join(case.tags)]
    for grader in case.graders:
        parts.append(grader.name)
        parts.append(grader.body or "")
        for key in ("pattern", "reference", "tool", "before", "after", "path", "focus"):
            value = grader.meta.get(key)
            if isinstance(value, str):
                parts.append(value)
        tools = grader.meta.get("tools")
        if isinstance(tools, list):
            parts.extend(str(t) for t in tools)
    return " ".join(parts).lower()


def _restraint_scored(case: evalcase.LoadedCase) -> bool:
    """Does this case prove restraint by something a model cannot argue with?

    `no_tool`, or a `trajectory` grader under EXACT — those read the trace.
    An `llm` grader reading the reply proves the agent *said* it refused.
    """
    for grader in case.graders:
        if grader.type == "no_tool":
            return True
        if grader.type == "trajectory":
            match = str(grader.meta.get("match") or "").strip().upper()
            if match == "EXACT":
                return True
        if grader.type == "tool_used":
            try:
                if int(grader.meta.get("max", -1)) == 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def summarize_cases(evals_dir: Path | str) -> list[dict[str, Any]]:
    """One row per case: what `evalcase.case_summary` says, plus the text a
    coverage check searches and the tools the graders name.

    Loading goes through `evalcase.iter_cases`, so the reserved directories
    (`runner/`, `results/`, `mocks/`, …) are never mistaken for cases and a
    case that fails to parse still appears, with its `ok` flag false.
    """
    rows: list[dict[str, Any]] = []
    for case in evalcase.iter_cases(evals_dir):
        row = evalcase.case_summary(case)
        row["tools"] = _case_tools(case)
        row["text"] = _case_text(case)
        row["prompt"] = (case.body or "").strip()
        row["restraint_scored"] = _restraint_scored(case)
        row["adversarial"] = case.category == "adversarial" or "adversarial" in case.tags
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------

def _mentions(row: dict[str, Any], needle: str) -> bool:
    needle = needle.strip().lower()
    if not needle:
        return False
    if any(needle == tool.lower() or needle in tool.lower() for tool in row.get("tools", [])):
        return True
    text = row.get("text", "")
    if "_" in needle or "__" in needle:
        return needle in text
    return re.search(rf"\b{re.escape(needle)}\b", text) is not None


def matrix(rules: Sequence[Rule], cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Which rules does at least one case aim at?

    A rule is *aimed at* when a case's prompt, tags or graders mention one of
    the rule's tools, or two of its key phrases (one phrase is a coincidence —
    "book" appears in every case of a library agent). The result carries the
    evidence, so the reader can disagree with the heuristic on a specific row.
    """
    rows: list[dict[str, Any]] = []
    for rule in rules:
        hits: list[dict[str, Any]] = []
        for case in cases:
            by_tool = [tool for tool in rule.tools if _mentions(case, tool)]
            by_phrase = [phrase for phrase in rule.phrases if _mentions(case, phrase)]
            if by_tool or len(by_phrase) >= 2:
                hits.append({
                    "case": case.get("name"),
                    "category": case.get("category"),
                    "matched_tools": by_tool,
                    "matched_phrases": by_phrase,
                })
        rows.append({
            "rule": rule.to_dict(),
            "covered": bool(hits),
            "cases": hits,
        })
    uncovered = [r["rule"]["id"] for r in rows if not r["covered"]]
    return {
        "rows": rows,
        "total_rules": len(rows),
        "covered": len(rows) - len(uncovered),
        "uncovered": uncovered,
        "basis": "a case mentions the rule's tool, or two of its key phrases; that is "
                 "evidence the case was aimed at the rule, not that the rule holds",
    }


# ---------------------------------------------------------------------------
# suite shape
# ---------------------------------------------------------------------------

def shape(
    cases: Sequence[dict[str, Any]],
    *,
    required: Sequence[str] = TARGET_SHAPE,
    adversarial_share: float = ADVERSARIAL_SHARE,
) -> dict[str, Any]:
    """The suite's category mix against the shape a regression suite needs.

    Two targets, both defaults a caller may raise: one case of every category,
    and adversarial cases at or above `adversarial_share` of the suite. The
    adversarial share is the one that decays silently — happy-path cases are
    the easy ones to write, so a suite drifts towards proving only that the
    agent works when nothing goes wrong.
    """
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.get("category") or "(none)"] = counts.get(case.get("category") or "(none)", 0) + 1
    total = len(cases)
    adversarial = sum(1 for c in cases if c.get("adversarial"))
    ratio = (adversarial / total) if total else 0.0
    missing = [name for name in required if counts.get(name, 0) == 0]

    gaps: list[dict[str, str]] = []
    for name in missing:
        gaps.append({
            "id": f"shape-{name}",
            "what": f"no `{name}` case",
            "why": _CATEGORY_WHY.get(name, "this category proves something the others cannot"),
            "recommendation": f"write one with `/agent-sdk:eval-create` "
                              f"(gen_cases.py --category {name})",
        })
    if total and ratio < adversarial_share:
        needed = max(1, int(-(-adversarial_share * total // 1)) - adversarial)
        gaps.append({
            "id": "shape-adversarial-share",
            "what": f"adversarial cases are {adversarial}/{total} ({ratio:.0%}), "
                    f"below the {adversarial_share:.0%} target",
            "why": "happy-path cases prove the agent works when nothing goes wrong, which is "
                   "not the failure people report. The rules an agent breaks under pressure "
                   "are the ones nobody wrote a case for",
            "recommendation": f"add {needed} adversarial case(s): one per refusal rule, each "
                              "scored with `no_tool` or an EXACT trajectory",
        })
    if counts.get("(none)"):
        gaps.append({
            "id": "shape-uncategorized",
            "what": f"{counts['(none)']} case(s) declare no `category`",
            "why": "the category is what a tier filter and a coverage report group on; "
                   "without it a case is invisible to both (EVC030)",
            "recommendation": "add `category:` to each case's frontmatter",
        })
    return {
        "total": total,
        "counts": dict(sorted(counts.items())),
        "adversarial": adversarial,
        "adversarial_ratio": round(ratio, 3),
        "adversarial_target": adversarial_share,
        "missing_categories": missing,
        "ok": not gaps,
        "gaps": gaps,
    }


_CATEGORY_WHY = {
    "happy": "without one, nothing proves the agent does its job at all; every other "
             "category assumes the happy path already works",
    "edge": "the boundaries (empty result, ambiguous request, unavailable item) are where "
            "an agent improvises, and improvisation is what regresses",
    "adversarial": "a rule with no case that tries to break it is a rule nobody is testing; "
                   "the agent's restraint is the behaviour that decays first",
    "memory": "a multi-turn case proves the session carries context; single-turn cases "
              "cannot tell a memory failure from a prompt failure",
    "regression": "a bug with no case comes back. A regression case is the record that "
                  "someone once saw this go wrong",
}


# ---------------------------------------------------------------------------
# n + 1
# ---------------------------------------------------------------------------

def n_plus_one_gaps(
    rules: Sequence[Rule],
    cases: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Refusal rules with no case that tries to break them, and how they fail.

    The n+1 rule: n rules need n cases that exercise them plus one case per
    refusal that *attempts the forbidden thing*. The attempt has to be scored
    against the trace — `no_tool`, an EXACT trajectory, or `tool_used` with
    `max: 0`. A judge reading the final reply grades the apology, not the act.
    """
    out: list[dict[str, Any]] = []
    for rule in rules:
        if not rule.is_refusal:
            continue
        aimed = [
            case for case in cases
            if any(_mentions(case, tool) for tool in rule.tools)
            or sum(1 for phrase in rule.phrases if _mentions(case, phrase)) >= 2
        ]
        scored = [case for case in aimed if case.get("restraint_scored")]
        if scored:
            continue
        if aimed:
            reason = "no_trace_check"
            named = ", ".join(str(c.get("name")) for c in aimed[:3])
            what = (f"{rule.id} is a refusal rule; {named} "
                    f"{'aims' if len(aimed) == 1 else 'aim'} at it, but nothing reads the "
                    "trace — only the reply is scored")
            recommendation = ("add a `no_tool` grader naming the tool the rule forbids, or set "
                              "the trajectory grader's `match: EXACT`. Keep the `llm` grader: "
                              "it proves the explanation, the trace check proves the restraint")
        else:
            reason = "no_case"
            what = f"{rule.id} is a refusal rule with no case that attempts the forbidden action"
            recommendation = ("write an adversarial case whose prompt asks for exactly what the "
                              "rule forbids, with a `no_tool` grader on "
                              + (f"`{rule.tools[0]}`" if rule.tools else "the tool it names"))
        out.append({
            "rule": rule.to_dict(),
            "reason": reason,
            "what": what,
            "why": "a refusal nobody tests is a refusal that survives only as long as the "
                   "prompt wording does; every model upgrade is a chance to lose it silently",
            "recommendation": recommendation,
            "aimed_cases": [c.get("name") for c in aimed],
        })
    return out


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

def tool_coverage(
    agent_tools: Iterable[str] | None,
    cases: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Which of the agent's tools does any grader assert about?

    `agent_tools=None` means the tool list could not be determined — an agent
    whose options are built at runtime, or a project that would not parse. The
    result then says `unknown` rather than reporting every tool as uncovered,
    which would be a lie dressed as a finding.
    """
    if agent_tools is None:
        return {
            "status": UNKNOWN,
            "note": "the agent's tool list could not be read statically; run "
                    "`/agent-sdk:agent-review` (load_agent.py) to obtain it from a live import",
            "by_tool": {}, "untested": [], "grader_only": [],
        }
    known = sorted({graders_mod.normalize_tool_name(t) for t in agent_tools})
    by_tool: dict[str, list[str]] = {tool: [] for tool in known}
    grader_only: list[str] = []
    for case in cases:
        for tool in case.get("tools", []):
            if tool in by_tool:
                if case.get("name") not in by_tool[tool]:
                    by_tool[tool].append(str(case.get("name")))
            elif tool not in grader_only and tool not in SYNTHETIC_TOOLS \
                    and tool not in SUBAGENT_TOOL_NAMES:
                grader_only.append(tool)
    untested = [tool for tool, names in by_tool.items() if not names]
    return {
        "status": "ok",
        "by_tool": by_tool,
        "untested": untested,
        "grader_only": sorted(grader_only),
        "covered": len(known) - len(untested),
        "total": len(known),
    }
