"""The grader catalog: what each check needs, and what it does not prove.

A grader is one file, `evals/<case>/graders/<slug>.md`. Its frontmatter names a
`type` and the fields that type needs; its body is prose for the next reader.
Twelve types ship, and they split into exactly two cost tiers:

* **free** — reads the trace, the result event or the run's files. No model call,
  so it is safe in a per-PR gate and safe to re-run over a saved trace.
* **judge** — only ``llm``. Sends the evidence to a judge model, so it costs
  tokens per sample and its verdict is a distribution, not a fact.

Tier is **derived from `type`, never declared**: a case cannot make a judge check
cheap by relabelling it, and `eval_config.json`'s `tiers.<name>.graders` filters
on the derived value.

Every spec carries a `not_proven` line, because the honest half of a grader is
what it leaves open. `tool_used: reserve_book` proves a call happened; it does
not prove the arguments were right, that the call succeeded, or that the answer
reflected the result. A suite whose graders are all `tool_used` will pass an
agent that calls the right tools with the wrong inputs and then lies about it.

Three semantics are measured, not assumed, and would silently corrupt results if
a grader ignored them (see :data:`SEMANTICS_NOTES` and CONTRACTS §2.1):

1. ``StructuredOutput`` is a **synthetic** tool call the CLI fabricates for
   `output_format` results. Trajectory-shaped graders skip it unless named.
2. The subagent tool has **two names** — the CLI reports ``Task``, the SDK and
   docs say ``Agent``. A grader naming either matches both.
3. ``budget.max_turns`` is the grader's own ceiling on `result.num_turns`, not a
   check that `ClaudeAgentOptions.max_turns` tripped (`max_turns=1` produced
   `num_turns=2`). Use a ``terminal`` grader to assert the limit fired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import SUBAGENT_TOOL_NAMES, SYNTHETIC_TOOLS
from .report import Finding

#: Citations. Every finding points at one of these so a reader can check the rule.
_SRC_CATALOG = "this plugin's grader catalog (CONTRACTS §2)"
_SRC_SEMANTICS = "measured: .dev/VERIFIED-FACTS.md §5, §8 (CONTRACTS §2.1)"
_SRC_HOOKS = "claude_agent_sdk types.py HookEvent literal (10 values)"
_SRC_RESULT = "claude_agent_sdk types.py:1695 ResultMessage (0.2.174)"

TIER_FREE = "free"
TIER_JUDGE = "judge"
TIERS = (TIER_FREE, TIER_JUDGE)

#: Where a grader may look. `last_message` is the agent's final text, `trace`
#: the whole event stream, `files` the run's working directory, `mock_calls` the
#: call log the mock wrapper keeps, `result` the `ResultMessage` event.
TARGETS = ("last_message", "trace", "files", "mock_calls", "result", "result.structured_output")

#: Keys every grader file may carry whatever its type.
COMMON_KEYS = frozenset({"name", "type", "description", "weight", "informational"})


@dataclass(frozen=True)
class GraderSpec:
    """One grader type's contract.

    `required` fields must all be present. `one_of` groups are satisfied by at
    least one member — `structured_output` needs `schema` **or** `schema_file`,
    `budget` needs at least one ceiling, `terminal` at least one of its two
    assertions. `targets` is the closed set the `target` key may name.
    """

    type: str
    tier: str
    description: str
    not_proven: str
    required: tuple[str, ...] = ()
    one_of: tuple[tuple[str, ...], ...] = ()
    optional: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    default_target: str | None = None
    #: True when the check reads the tool-call sequence and must therefore skip
    #: synthetic tools and honour the Task/Agent alias.
    tool_shaped: bool = False
    #: The body carries a required field (only `llm`, whose body is `criteria`).
    body_is: str | None = None
    source: str = _SRC_CATALOG

    @property
    def all_keys(self) -> frozenset[str]:
        flat = {name for group in self.one_of for name in group}
        return frozenset(self.required) | frozenset(self.optional) | flat | COMMON_KEYS | {"target"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type, "tier": self.tier, "description": self.description,
            "not_proven": self.not_proven, "required": list(self.required),
            "one_of": [list(group) for group in self.one_of],
            "optional": list(self.optional), "targets": list(self.targets),
            "default_target": self.default_target, "tool_shaped": self.tool_shaped,
            "body_is": self.body_is,
        }


#: Budget ceilings, mapped to the measured `usage` keys. `cache_creation` in the
#: raw usage payload is a nested dict of ephemeral TTL buckets, never a number,
#: so the cache ceilings read `cache_*_input_tokens` instead.
BUDGET_CEILINGS = (
    "max_cost_usd", "max_turns", "max_input_tokens", "max_output_tokens",
    "max_duration_ms", "max_cache_read_tokens", "max_cache_creation_tokens",
)

#: Which `usage` key each token ceiling compares against.
BUDGET_USAGE_KEYS = {
    "max_input_tokens": "input_tokens",
    "max_output_tokens": "output_tokens",
    "max_cache_read_tokens": "cache_read_input_tokens",
    "max_cache_creation_tokens": "cache_creation_input_tokens",
}

REGEX_MATCH_MODES = ("contains", "not_contains")
TRAJECTORY_MATCH_MODES = ("EXACT", "IN_ORDER", "ANY_ORDER")
ARGS_MATCH_MODES = ("exact", "subset", "ignore")
FINAL_TEXT_MODES = ("exact", "contains", "rouge1")
HOOK_DECISIONS = ("allow", "deny")

#: `count:N` is the third `regex.match` form; it is checked by pattern.
COUNT_MATCH = re.compile(r"^count:\d+$")


GRADER_CATALOG: dict[str, GraderSpec] = {
    "llm": GraderSpec(
        type="llm", tier=TIER_JUDGE, body_is="criteria",
        description="a judge model answers one PASS/FAIL question about the evidence",
        not_proven="that another sample would agree; a judge verdict is a distribution, "
                   "so a single sample is a coin-flip on a borderline case",
        required=("criteria",), optional=("focus", "samples", "model", "target"),
        targets=("last_message", "trace"), default_target="last_message",
        source="code.claude.com/en/docs/claude-code/plugins-reference (grader grammar) "
               "+ CONTRACTS §9",
    ),
    "regex": GraderSpec(
        type="regex", tier=TIER_FREE,
        description="a regular expression must (or must not) match the target text",
        not_proven="that the agent meant it; a phrase can appear in a refusal, a quotation "
                   "or an apology as easily as in the answer you wanted",
        required=("pattern",), optional=("flags", "match", "target"),
        targets=("last_message", "trace", "files", "mock_calls"), default_target="last_message",
    ),
    "tool_used": GraderSpec(
        type="tool_used", tier=TIER_FREE, tool_shaped=True,
        description="a named tool was called between `min` and `max` times",
        not_proven="that the arguments were right or the call succeeded; pair it with "
                   "`input_match`, or with a `trajectory` grader for order",
        required=("tool",), optional=("input_match", "min", "max", "target"),
        targets=("trace", "mock_calls"), default_target="trace",
    ),
    "tool_order": GraderSpec(
        type="tool_order", tier=TIER_FREE, tool_shaped=True,
        description="one tool was called before another at least once",
        not_proven="that nothing happened in between, and not that either call was "
                   "correct — only their relative order",
        required=("before", "after"), optional=("target",),
        targets=("trace",), default_target="trace",
    ),
    "file_exists": GraderSpec(
        type="file_exists", tier=TIER_FREE,
        description="a glob matches at least one file in the run's working directory",
        not_proven="anything about the file's contents; add a `regex` grader with "
                   "`target: files` for that",
        required=("path",), optional=("target",),
        targets=("files",), default_target="files",
    ),
    "trajectory": GraderSpec(
        type="trajectory", tier=TIER_FREE, tool_shaped=True,
        description="the tool-call sequence matches an expected one under EXACT, "
                    "IN_ORDER or ANY_ORDER",
        not_proven="that the answer was right; an agent can walk the golden path and "
                   "still summarize it wrongly (see the trajectory x answer quadrant)",
        required=("expected",), optional=("match", "args_match", "threshold", "target"),
        targets=("trace",), default_target="trace",
    ),
    "structured_output": GraderSpec(
        type="structured_output", tier=TIER_FREE,
        description="`result.structured_output` validates against a schema, and "
                    "optionally equals or contains given values",
        not_proven="that the values are true — a well-shaped object can be confidently "
                   "wrong. Note the CLI delivers it via a synthetic `StructuredOutput` call",
        one_of=(("schema", "schema_file"),), optional=("equals", "contains", "target"),
        targets=("result.structured_output",), default_target="result.structured_output",
        source="measured: VERIFIED-FACTS §5 (ResultMessage.structured_output)",
    ),
    "budget": GraderSpec(
        type="budget", tier=TIER_FREE,
        description="the run stayed under cost, turn, token, cache or duration ceilings",
        not_proven="that the run was correct, and not that a limit *tripped*: "
                   "`max_turns=1` was measured producing `num_turns=2`, and "
                   "`ClaudeAgentOptions.max_budget_usd` is a **soft** cap — the estimate "
                   "can finish over it, so leave headroom. "
                   "Use `terminal` to assert a limit fired",
        one_of=(BUDGET_CEILINGS,), optional=("informational", "target"),
        targets=("result",), default_target="result",
        source=_SRC_RESULT + " + measured VERIFIED-FACTS §8.1",
    ),
    "hook_event": GraderSpec(
        type="hook_event", tier=TIER_FREE,
        description="a hook fired for an event, optionally with a matcher or a decision",
        not_proven="anything, unless the runner's capture hook is registered for that "
                   "event: `include_hook_events=True` alone emits nothing, and the "
                   "grader is then NOT_EVALUATED rather than FAILED",
        required=("event",), optional=("matcher", "min", "max", "decision", "target"),
        targets=("trace",), default_target="trace",
        source=_SRC_HOOKS + " + measured VERIFIED-FACTS §8.6",
    ),
    "final_text": GraderSpec(
        type="final_text", tier=TIER_FREE,
        description="the final assistant text matches a reference exactly, by "
                    "containment, or by ROUGE-1 overlap above a threshold",
        not_proven="meaning. ROUGE-1 compares word overlap, so a paraphrase scores low "
                   "and a fluent contradiction can score high",
        required=("reference",), optional=("mode", "threshold", "target"),
        targets=("last_message",), default_target="last_message",
    ),
    "no_tool": GraderSpec(
        type="no_tool", tier=TIER_FREE, tool_shaped=True,
        description="none of the named tools was called — the restraint check",
        not_proven="that the agent refused for the right reason, or said anything useful; "
                   "pair it with an `llm` grader on the explanation",
        required=("tools",), optional=("target",),
        targets=("trace",), default_target="trace",
    ),
    "terminal": GraderSpec(
        type="terminal", tier=TIER_FREE,
        description="the run ended the expected way: a `subtype` and/or a `terminal_reason`",
        not_proven="that the work was done; `subtype: success` only means the loop "
                   "finished without erroring",
        one_of=(("subtype", "terminal_reason"),), optional=("allow_error", "target"),
        targets=("result",), default_target="result",
        source=_SRC_RESULT,
    ),
}

GRADER_TYPES = tuple(GRADER_CATALOG)
JUDGE_TYPES = tuple(spec.type for spec in GRADER_CATALOG.values() if spec.tier == TIER_JUDGE)
FREE_TYPES = tuple(spec.type for spec in GRADER_CATALOG.values() if spec.tier == TIER_FREE)
#: Types that read the tool-call sequence, and so must skip synthetic tools.
TOOL_SHAPED_TYPES = tuple(spec.type for spec in GRADER_CATALOG.values() if spec.tool_shaped)
#: Types that read the `result` event, and so cannot be graded on an imported
#: session (a session JSONL carries no result line).
RESULT_SHAPED_TYPES = ("budget", "terminal", "structured_output")


# ---------------------------------------------------------------------------
# semantics the graders must share with the runner
# ---------------------------------------------------------------------------

#: CONTRACTS §2.1 as data, so `grader_info.py` can print it and a skill can
#: quote it without re-deriving it. Each note is one rule plus its evidence.
SEMANTICS_NOTES: tuple[dict[str, str], ...] = (
    {
        "id": "synthetic-tools",
        "applies_to": "tool_used, tool_order, trajectory, no_tool",
        "rule": "Tool names in SYNTHETIC_TOOLS ({}) are skipped unless the grader names "
                "one explicitly.".format(", ".join(SYNTHETIC_TOOLS)),
        "why": "The CLI delivers `output_format` results as a synthetic ToolUseBlock named "
               "StructuredOutput. Without the skip, every structured-output case sees a "
               "phantom call and `no_tool` fails spuriously.",
        "source": _SRC_SEMANTICS,
    },
    {
        "id": "subagent-alias",
        "applies_to": "tool_used, tool_order, trajectory, no_tool",
        "rule": "`{}` and `{}` are the same tool; a grader naming either matches both.".format(
            *SUBAGENT_TOOL_NAMES),
        "why": "The CLI reports `Task`; the SDK and docs say `Agent`.",
        "source": _SRC_SEMANTICS,
    },
    {
        "id": "budget-turns",
        "applies_to": "budget, terminal",
        "rule": "`budget.max_turns` compares `result.num_turns` against the grader's own "
                "ceiling. It is not a check that `ClaudeAgentOptions.max_turns` tripped.",
        "why": "Measured: `max_turns=1` produced `num_turns=2` with subtype `success`. "
               "To assert the limit fired use `terminal: {subtype: error_max_turns}` or "
               "`terminal: {terminal_reason: max_turns}`.",
        "source": _SRC_SEMANTICS,
    },
    {
        "id": "budget-cost-delta",
        "applies_to": "budget",
        "rule": "`max_cost_usd` is compared against the case total — the last "
                "`total_cost_usd` of the session — not a sum of per-turn costs.",
        "why": "`total_cost_usd` is a session running total (measured 0.004991 then "
               "0.0061734 across two turns), so summing double-counts. The trace records "
               "`cost_delta_usd` per turn for attribution.",
        "source": _SRC_SEMANTICS,
    },
    {
        "id": "usage-keys",
        "applies_to": "budget",
        "rule": "Token ceilings map to `usage.input_tokens`, `usage.output_tokens`, "
                "`usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens`.",
        "why": "`usage.cache_creation` is a nested dict of ephemeral TTL buckets, never a "
               "number; reading it as a count silently compares a dict to an int.",
        "source": "measured: VERIFIED-FACTS §2.2",
    },
    {
        "id": "is-error-null",
        "applies_to": "tool_used, trajectory, regex",
        "rule": "`ToolResultBlock.is_error` is `null` on success, not `False`. Test "
                "truthiness, never `is False`.",
        "why": "Measured on every successful tool result in run 2 and run 3.",
        "source": _SRC_SEMANTICS,
    },
    {
        "id": "hook-capture",
        "applies_to": "hook_event",
        "rule": "A `hook_event` grader is NOT_EVALUATED, not FAILED, when the runner's "
                "capture hook was not registered for the named event.",
        "why": "`include_hook_events=True` alone emitted zero hook events (run 2). "
               "Absence of evidence is not evidence of absence.",
        "source": _SRC_SEMANTICS,
    },
    {
        "id": "session-import",
        "applies_to": "budget, terminal, structured_output",
        "rule": "On evidence imported from a Claude Code session JSONL these graders are "
                "NOT_EVALUATED.",
        "why": "A session file carries no result line, so there is no cost, no "
               "`num_turns` and no `terminal_reason` to read.",
        "source": "measured: VERIFIED-FACTS §10 (25-line session, no result line)",
    },
    {
        "id": "which-model-ran",
        "applies_to": "budget, llm",
        "rule": "To assert which model ran, read `assistant_text.model`, not "
                "`model_usage.keys()`; to read the cost, loop over every entry.",
        "why": "Every measured run also billed a model nobody asked for for CLI-internal "
               "work (`claude-haiku-4-5-20251001` in 2026-09; `claude-haiku-5-5` on CLI "
               "2.1.294, 2.1.301 and 2.1.310, measured 2026-10-11, 2026-10-17 and 2026-10-24), so `model_usage` names extra models and the "
               "first entry is not the total.",
        "source": "measured: VERIFIED-FACTS §8.3 and the 0.2.165, 0.2.168 and 0.2.174 re-measurements",
    },
)


def tier_of(grader_type: str | None) -> str:
    """The cost tier a grader type implies. Unknown types are treated as free.

    Unknown means "this plugin does not know it", which is already reported as
    EVC010; calling it `judge` on top of that would quietly inflate cost
    estimates for what is usually a typo.
    """
    spec = GRADER_CATALOG.get(str(grader_type or ""))
    return spec.tier if spec else TIER_FREE


def spec_for(grader_type: str | None) -> GraderSpec | None:
    return GRADER_CATALOG.get(str(grader_type or ""))


def tiers_of(grader_types: Iterable[str]) -> set[str]:
    return {tier_of(t) for t in grader_types}


def normalize_tool_name(name: str) -> str:
    """Fold the subagent tool's two names onto one key.

    `Task` (what the CLI reports) and `Agent` (what the SDK and docs call it)
    are the same tool, so a grader naming either must match either.
    """
    text = str(name or "")
    return SUBAGENT_TOOL_NAMES[0] if text in SUBAGENT_TOOL_NAMES else text


def tool_names_match(grader_tool: str, actual_tool: str) -> bool:
    """Does a grader's tool name refer to this actual call?"""
    return normalize_tool_name(grader_tool) == normalize_tool_name(actual_tool)


def is_synthetic(tool: str) -> bool:
    return str(tool or "") in SYNTHETIC_TOOLS


def names_synthetic(meta: dict[str, Any]) -> bool:
    """Did this grader explicitly ask about a synthetic tool?

    If it did, the synthetic call must stay visible — the grader is presumably
    checking that structured output was produced at all.
    """
    named: list[str] = []
    for key in ("tool", "before", "after"):
        value = meta.get(key)
        if isinstance(value, str):
            named.append(value)
    for key in ("tools",):
        value = meta.get(key)
        if isinstance(value, list):
            named.extend(str(v) for v in value)
    for item in meta.get("expected") or []:
        if isinstance(item, dict) and item.get("tool"):
            named.append(str(item["tool"]))
        elif isinstance(item, str):
            named.append(item)
    return any(is_synthetic(name) for name in named)


def grader_tool_names(meta: dict[str, Any]) -> list[str]:
    """Every tool name a grader's frontmatter names, in reading order."""
    names: list[str] = []
    for key in ("tool", "before", "after"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    value = meta.get("tools")
    if isinstance(value, list):
        names.extend(str(v).strip() for v in value if str(v).strip())
    elif isinstance(value, str) and value.strip():
        names.append(value.strip())
    for item in meta.get("expected") or []:
        if isinstance(item, dict) and item.get("tool"):
            names.append(str(item["tool"]).strip())
        elif isinstance(item, str) and item.strip():
            names.append(item.strip())
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate_grader(
    meta: dict[str, Any],
    body: str = "",
    *,
    path: str | None = None,
    name: str | None = None,
) -> list[Finding]:
    """Findings for one grader file's frontmatter and body.

    Three ids:

    ``EVC010``
        the `type` is missing or not in the catalog — nothing else can be
        checked, so validation stops there.
    ``EVC011``
        a required field is missing (including a `one_of` group where none of
        the alternatives is present, and `llm` with an empty body).
    ``EVC012``
        `target` names a place this type cannot read, or an enum-valued field
        (`match`, `args_match`, `mode`, `decision`) carries a value the runner
        does not implement.

    Unknown frontmatter keys are reported as ``EVC002``, the same id the case
    loader uses, because it is the same mistake in a different file.
    """
    label = name or (meta.get("name") if isinstance(meta.get("name"), str) else None) or "grader"
    out: list[Finding] = []

    def add(fid: str, severity: str, message: str, *, fix: str = "", source: str | None = None,
            locator: str | None = None) -> None:
        out.append(Finding(
            id=fid, severity=severity, area="grader",
            message=f"grader {label!r}: {message}",
            path=path, locator=locator, fix=fix or None, source=source or _SRC_CATALOG,
        ))

    raw_type = meta.get("type")
    spec = spec_for(raw_type if isinstance(raw_type, str) else None)
    if spec is None:
        known = ", ".join(sorted(GRADER_CATALOG))
        shown = raw_type if raw_type not in (None, "") else "(missing)"
        add("EVC010", "error", f"unknown grader type {shown!r}",
            fix=f"use one of: {known}", locator="type")
        return out

    # -- required fields ------------------------------------------------
    for field_name in spec.required:
        if field_name == spec.body_is:
            # A `---` line ends the criterion; what follows is the prose note, so
            # a file that is *only* a note has no criterion at all.
            from .rubrics import split_criteria
            if not split_criteria(body)[0]:
                add("EVC011", "error",
                    f"type {spec.type!r} takes its {field_name!r} from the file body, which is empty",
                    fix="write the PASS/FAIL question under the frontmatter, one claim, "
                        "with an explicit FAIL clause", locator="body")
            continue
        if _missing(meta.get(field_name)):
            add("EVC011", "error", f"type {spec.type!r} requires {field_name!r}",
                fix=f"add `{field_name}:` to the frontmatter", locator=field_name)

    for group in spec.one_of:
        if not any(not _missing(meta.get(alt)) for alt in group):
            shown = ", ".join(group)
            add("EVC011", "error",
                f"type {spec.type!r} needs at least one of: {shown}",
                fix=f"add one of `{group[0]}:` … to the frontmatter")

    # -- target ---------------------------------------------------------
    target = meta.get("target")
    if isinstance(target, dict):
        # `{source: file, path: ...}` — only `llm` reads a file as evidence.
        if spec.type != "llm":
            add("EVC012", "error",
                f"type {spec.type!r} cannot take a file target",
                fix=f"valid targets: {', '.join(spec.targets)}", locator="target")
        elif not target.get("path"):
            add("EVC011", "error", "a file target needs a `path`",
                fix="target:\n  source: file\n  path: out/report.md", locator="target.path")
    elif isinstance(target, str) and target.strip():
        if target.strip() not in spec.targets:
            add("EVC012", "error",
                f"type {spec.type!r} cannot read target {target.strip()!r}",
                fix=f"valid targets: {', '.join(spec.targets)}"
                    + (f" (default {spec.default_target})" if spec.default_target else ""),
                locator="target")
    elif target is not None and not isinstance(target, (str, dict)):
        add("EVC012", "error", f"`target` must be a name or a file mapping, got {type(target).__name__}",
            locator="target")

    out.extend(_validate_enums(spec, meta, add=add))
    out.extend(_validate_unknown_keys(spec, meta, add=add))
    return out


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _validate_enums(spec: GraderSpec, meta: dict[str, Any], *, add) -> list[Finding]:
    """Enum-valued fields, checked against what the runner implements."""
    checks: list[tuple[str, tuple[str, ...], bool]] = []
    if spec.type == "regex":
        checks.append(("match", REGEX_MATCH_MODES, True))
    if spec.type == "trajectory":
        checks.append(("match", TRAJECTORY_MATCH_MODES, False))
        checks.append(("args_match", ARGS_MATCH_MODES, False))
    if spec.type == "final_text":
        checks.append(("mode", FINAL_TEXT_MODES, False))
    if spec.type == "hook_event":
        checks.append(("decision", HOOK_DECISIONS, False))

    for key, allowed, allow_count in checks:
        value = meta.get(key)
        if value is None:
            continue
        text = str(value)
        if text in allowed:
            continue
        if allow_count and COUNT_MATCH.match(text):
            continue
        extra = " (or `count:N`)" if allow_count else ""
        add("EVC012", "error",
            f"{key}: {text!r} is not one of {', '.join(allowed)}{extra}",
            fix=f"use one of: {', '.join(allowed)}{extra}", locator=key)

    if spec.type == "regex" and isinstance(meta.get("pattern"), str):
        try:
            re.compile(meta["pattern"])
        except re.error as exc:
            add("EVC012", "error", f"pattern does not compile: {exc}",
                fix="escape the regex metacharacters you meant literally", locator="pattern")

    if spec.type == "trajectory":
        expected = meta.get("expected")
        if expected is not None and not isinstance(expected, list):
            add("EVC012", "error", "`expected` must be a list of {tool, args?} entries",
                locator="expected")
        elif isinstance(expected, list):
            for index, item in enumerate(expected):
                if isinstance(item, dict) and not item.get("tool"):
                    add("EVC011", "error", f"expected[{index}] has no `tool`",
                        locator=f"expected[{index}]")
                elif not isinstance(item, (dict, str)):
                    add("EVC012", "error",
                        f"expected[{index}] must be a mapping or a tool name",
                        locator=f"expected[{index}]")

    if spec.type == "no_tool" and meta.get("tools") is not None \
            and not isinstance(meta.get("tools"), list):
        add("EVC012", "error", "`tools` must be a list of tool names", locator="tools")

    if spec.type == "hook_event":
        from . import PYTHON_HOOK_EVENTS
        event = meta.get("event")
        if isinstance(event, str) and event.strip() and event.strip() not in PYTHON_HOOK_EVENTS:
            add("EVC012", "error",
                f"event {event.strip()!r} is not one of the Python SDK's HookEvent values",
                fix="valid events: " + ", ".join(PYTHON_HOOK_EVENTS)
                    + " (SessionStart/SessionEnd are not among them)",
                source=_SRC_HOOKS, locator="event")

    for key in ("threshold",):
        value = meta.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            add("EVC012", "error", f"{key} must be a number in [0, 1], got {value!r}", locator=key)

    for key in ("min", "max", "samples"):
        value = meta.get(key)
        if value is None or isinstance(value, bool):
            continue
        if not isinstance(value, int) or value < 0:
            add("EVC012", "error", f"{key} must be a non-negative integer, got {value!r}", locator=key)
    return []


def _validate_unknown_keys(spec: GraderSpec, meta: dict[str, Any], *, add) -> list[Finding]:
    allowed = spec.all_keys
    for key in meta:
        if key not in allowed:
            close = _closest(key, sorted(allowed))
            add("EVC002", "warn", f"unknown key {key!r} for type {spec.type!r}",
                fix=(f"did you mean {close!r}?" if close else
                     f"keys for {spec.type!r}: {', '.join(sorted(allowed))}"),
                locator=key)
    return []


def _closest(word: str, candidates: list[str]) -> str | None:
    """The nearest candidate by edit distance, when it is near enough to help."""
    best, best_distance = None, 99
    for candidate in candidates:
        distance = _edit_distance(word, candidate)
        if distance < best_distance:
            best, best_distance = candidate, distance
    limit = 1 if len(word) <= 4 else 2 if len(word) <= 8 else 3
    return best if best_distance <= limit else None


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def catalog_rows() -> list[dict[str, str]]:
    """One row per grader type, ready for a markdown table."""
    rows: list[dict[str, str]] = []
    for spec in GRADER_CATALOG.values():
        required = list(spec.required)
        for group in spec.one_of:
            required.append(" | ".join(group) if len(group) <= 3 else f"one of {len(group)} ceilings")
        rows.append({
            "type": spec.type,
            "tier": spec.tier,
            "required": ", ".join(required) or "—",
            "optional": ", ".join(spec.optional) or "—",
            "target": spec.default_target or "—",
            "targets": ", ".join(spec.targets) or "—",
            "description": spec.description,
            "not_proven": spec.not_proven,
        })
    return rows


def catalog_table(*, columns: tuple[str, ...] = ("type", "tier", "required", "optional", "target")) -> str:
    """The catalog as a markdown table, for a skill to print."""
    rows = catalog_rows()
    head = "| " + " | ".join(columns) + " |"
    rule = "|" + "|".join("---" for _ in columns) + "|"
    lines = [head, rule]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")).replace("|", "\\|") for c in columns) + " |")
    return "\n".join(lines)


def semantics_lines() -> list[str]:
    """The measured semantics as one readable block."""
    lines: list[str] = []
    for note in SEMANTICS_NOTES:
        lines.append(f"- **{note['id']}** ({note['applies_to']}): {note['rule']}")
        lines.append(f"  - Why: {note['why']}")
        lines.append(f"  - Source: {note['source']}")
    return lines
