"""Load and validate one eval case: `prompt.md` plus `graders/*.md`.

A case is a directory. `prompt.md` carries the frontmatter and, in its body, the
first user prompt. `graders/` holds one file per assertion. That is the whole
format, and it is deliberately the same shape `claude plugin eval` uses, so
someone who has written plugin evals already knows how to read it.

    evals/refuse-double-booking/
      prompt.md                     frontmatter + the prompt
      graders/refuses.md            an llm criterion
      graders/no_reserve.md         a no_tool restraint check
      graders/looked_up_first.md    a tool_used check

The validation here is the cheap half of an eval suite's quality, and it runs
before anything is spent: it catches the mistakes that would otherwise produce a
confident, meaningless result. Three of them are worth naming because they are
the ones that pass CI while proving nothing:

* **A case with no graders never fails** (``EVC060``). It runs, it costs money,
  and it reports PASSED whatever the agent did.
* **An adversarial case scored with a lenient trajectory match** (``EVC041``).
  ``IN_ORDER`` allows extra calls in between — including the call the case
  exists to forbid. The restraint has to be asserted with ``no_tool`` or
  ``EXACT``, or it is not asserted at all.
* **A trajectory grader on a simulated-user case** (``EVC040``). The persona
  drives the conversation, so the tool sequence is not the case's to predict;
  asserting on it makes the case fail for reasons the author did not choose.

Finding ids, all in the ``EVC`` band:

======  =========================================================  ========
id      what                                                       severity
======  =========================================================  ========
EVC001  no prompt body and no `turns`                              error
EVC002  unknown frontmatter key                                    warn
EVC003  `overrides` names something that is not an option          error
EVC004  option exists but is runner-owned / not JSON-expressible   error
EVC005  a stray `prompt.md` outside a case directory               warn
EVC006  `turns` and `simulated_user` both set                      error
EVC007  an `env` key that does not start `EVAL_`                   error
EVC010  unknown grader type                                        error
EVC011  a required grader field is missing                         error
EVC012  a grader target or enum value is not valid for its type    error
EVC020  a grader names a tool neither the agent nor a mock has     warn
EVC030  no `category`                                              info
EVC031  unknown `category`                                         warn
EVC040  trajectory/no_tool on a simulated-user case                error
EVC041  adversarial or refusal case scored with a lenient match    warn
EVC042  a deprecated override                                      warn
EVC050  weak `llm` criteria                                        warn/error
EVC060  a case with no graders                                     warn
======  =========================================================  ========
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import (
    DEPRECATED_OPTIONS,
    OPTION_NAMES,
    OVERRIDABLE_OPTIONS,
    SUBAGENT_TOOL_NAMES,
    SYNTHETIC_TOOLS,
    frontmatter,
)
from . import graders as graders_mod
from . import rubrics
from .report import Finding

_SRC_CASE = "this plugin's case format (CONTRACTS §1)"
_SRC_OPTIONS = "claude_agent_sdk types.py:2326 ClaudeAgentOptions (0.2.168) (49 fields)"
_SRC_ISOLATION = "measured: VERIFIED-FACTS §8.4 (17x cost with ambient settings loaded)"
_SRC_MCP_NAMES = "code.claude.com/en/docs/claude-code/mcp (tools are mcp__<server>__<tool>)"

PROMPT_NAME = "prompt.md"
GRADERS_DIR = "graders"

CATEGORIES = ("happy", "edge", "adversarial", "memory", "regression")

#: Every key `prompt.md` frontmatter may carry (CONTRACTS §1).
CASE_KEYS = frozenset({
    "name", "tags", "category", "runs", "max_turns", "timeout_seconds", "agent",
    "turns", "simulated_user", "overrides", "mocks", "faults", "env", "scaffold_script",
})

#: Keys whose value must be a list of strings.
_LIST_KEYS = ("tags", "turns", "mocks")
#: Keys whose value must be a positive integer.
_POSITIVE_INT_KEYS = ("runs", "max_turns", "timeout_seconds")

#: `env` keys must be namespaced so a case cannot reach the credential chain.
ENV_PREFIX = "EVAL_"

#: Match modes that tolerate calls the expectation does not name.
LENIENT_MATCHES = ("IN_ORDER", "ANY_ORDER")
#: A case name or tag that reads as "the agent must not do this".
RESTRAINT_PATTERN = re.compile(r"(?:^|[-_])(?:no|not|never|refuse|refuses|refusal|deny|reject)(?:[-_]|$)", re.I)

#: `module:function`
AGENT_ENTRY = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


@dataclass
class LoadedGrader:
    """One grader file, parsed but not yet judged."""

    path: str
    name: str
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def type(self) -> str | None:
        value = self.meta.get("type")
        return value if isinstance(value, str) else None

    @property
    def tier(self) -> str:
        return graders_mod.tier_of(self.type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "name": self.name, "type": self.type, "tier": self.tier,
            "meta": self.meta, "body_chars": len(self.body), "errors": self.errors,
        }


@dataclass
class LoadedCase:
    """One case directory, parsed. `errors` are load failures, not findings.

    A case that failed to parse still loads — with `errors` filled in and
    whatever was readable — because a validator that returns nothing on a broken
    file tells the user nothing about the other nine cases.
    """

    dir: str
    name: str
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    graders: list[LoadedGrader] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def prompt_path(self) -> str:
        return str(Path(self.dir) / PROMPT_NAME)

    @property
    def category(self) -> str | None:
        value = self.meta.get("category")
        return value if isinstance(value, str) else None

    @property
    def tags(self) -> list[str]:
        value = self.meta.get("tags")
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)] if isinstance(value, str) and value.strip() else []

    @property
    def turns(self) -> list[str]:
        value = self.meta.get("turns")
        if isinstance(value, list):
            return [str(v) for v in value]
        return []

    @property
    def is_simulated(self) -> bool:
        return bool(self.meta.get("simulated_user"))

    @property
    def is_multi_turn(self) -> bool:
        return len(self.turns) > 1 or self.is_simulated

    @property
    def grader_types(self) -> list[str]:
        return [g.type for g in self.graders if g.type]

    @property
    def tier(self) -> str:
        """The cheapest tier that can run this case: `judge` if any llm grader."""
        return graders_mod.TIER_JUDGE if any(
            g.tier == graders_mod.TIER_JUDGE for g in self.graders
        ) else graders_mod.TIER_FREE

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "dir": self.dir, "name": self.name, "category": self.category,
            "tags": self.tags, "meta": self.meta, "body_chars": len(self.body),
            "graders": [g.to_dict() for g in self.graders], "tier": self.tier,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_case(case_dir: Path | str) -> LoadedCase:
    """Parse one case directory. Never raises: parse failures become `errors`."""
    root = Path(case_dir)
    case = LoadedCase(dir=str(root), name=root.name)
    prompt = root / PROMPT_NAME
    if not prompt.is_file():
        case.errors.append(f"no {PROMPT_NAME}")
        return case
    try:
        text = prompt.read_text(encoding="utf-8")
    except OSError as exc:
        case.errors.append(f"unreadable {PROMPT_NAME}: {exc}")
        return case
    try:
        document = frontmatter.parse(text)
        case.meta = document.meta
        case.body = document.body
    except frontmatter.FrontmatterError as exc:
        case.errors.append(f"{PROMPT_NAME}: {exc}")
        # The body is still worth having: a broken header does not hide the prompt.
        header, body = _salvage(text)
        case.body = body
        del header
    if isinstance(case.meta.get("name"), str) and case.meta["name"].strip():
        case.name = case.meta["name"].strip()
    case.graders = load_graders(root / GRADERS_DIR)
    return case


def _salvage(text: str) -> tuple[str | None, str]:
    """Best-effort body recovery from a file whose frontmatter does not parse."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != frontmatter.DELIMITER:
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == frontmatter.DELIMITER:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:]).lstrip("\n")
    return None, ""


def load_graders(graders_dir: Path | str) -> list[LoadedGrader]:
    """Parse every `*.md` in a case's `graders/`, in filename order."""
    root = Path(graders_dir)
    if not root.is_dir():
        return []
    loaded: list[LoadedGrader] = []
    for file in sorted(root.glob("*.md")):
        grader = LoadedGrader(path=str(file), name=file.stem)
        try:
            text = file.read_text(encoding="utf-8")
        except OSError as exc:
            grader.errors.append(f"unreadable: {exc}")
            loaded.append(grader)
            continue
        try:
            document = frontmatter.parse(text)
            grader.meta = document.meta
            grader.body = document.body
        except frontmatter.FrontmatterError as exc:
            grader.errors.append(str(exc))
        if isinstance(grader.meta.get("name"), str) and grader.meta["name"].strip():
            grader.name = grader.meta["name"].strip()
        loaded.append(grader)
    return loaded


def iter_cases(evals_dir: Path | str) -> Iterator[LoadedCase]:
    """Every case directory under `evals/`, in directory order.

    A case is any immediate subdirectory holding a `prompt.md`. The runner's own
    directories (`runner/`, `results/`, `mocks/`, `personas/`, `faults/`,
    `fixtures/`, `graders_local/`) are never cases.
    """
    root = Path(evals_dir)
    if not root.is_dir():
        return
    reserved = {"runner", "results", "mocks", "personas", "faults", "fixtures", "graders_local"}
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in reserved or child.name.startswith("."):
            continue
        if (child / PROMPT_NAME).is_file():
            yield load_case(child)


def stray_prompt_files(evals_dir: Path | str) -> list[str]:
    """`prompt.md` files that are not inside a case directory.

    A `prompt.md` at the top of `evals/`, or nested two levels down, is silently
    never run. `layout.scan_evals_dir` finds the top-level ones; this also
    catches the nested mistake of `evals/group/case/prompt.md`.
    """
    root = Path(evals_dir)
    if not root.is_dir():
        return []
    reserved = {"runner", "results", "mocks", "personas", "faults", "fixtures", "graders_local"}
    stray: list[str] = []
    if (root / PROMPT_NAME).is_file():
        stray.append(str(root / PROMPT_NAME))
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in reserved or child.name.startswith("."):
            continue
        if (child / PROMPT_NAME).is_file():
            continue                      # a real case
        for nested in sorted(child.rglob(PROMPT_NAME)):
            stray.append(str(nested))
    return stray


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate_case(
    case: LoadedCase,
    *,
    agent_tools: set[str] | None = None,
    mock_tools: set[str] | None = None,
    config: Any | None = None,
) -> list[Finding]:
    """Everything wrong with one case, as findings.

    `agent_tools` and `mock_tools` enable the cross-check (EVC020). Pass
    `agent_tools=None` when the agent's tool list could not be determined: an
    empty set means "the agent exposes nothing", and reporting every grader as
    unknown-tool because a parse failed would bury the real findings.

    `config` is a `LoadedConfig` (or anything with a `.data` dict). It is used
    only to resolve defaults the case inherits, never to validate the config.
    """
    out: list[Finding] = []
    path = case.prompt_path

    def add(fid: str, severity: str, message: str, *, fix: str = "",
            source: str = _SRC_CASE, locator: str | None = None,
            where: str | None = None) -> None:
        out.append(Finding(
            id=fid, severity=severity, area="case", message=message,
            path=where or path, locator=locator, fix=fix or None, source=source,
        ))

    for error in case.errors:
        add("EVC001", "error", error,
            fix="a case is a directory with a prompt.md; fix the header or delete the directory")
    if case.errors and not case.meta:
        return out

    meta = case.meta

    # -- the prompt itself ---------------------------------------------
    if not case.body.strip() and not case.turns and not case.is_simulated:
        add("EVC001", "error", "no prompt body, no `turns` and no `simulated_user`",
            fix="write the first user prompt under the frontmatter, or set `turns:` for a "
                "scripted conversation, or `simulated_user:` for a persona-driven one")
    if case.turns and case.is_simulated:
        add("EVC006", "error", "`turns` and `simulated_user` are mutually exclusive",
            fix="a scripted conversation and a persona-driven one are different cases: "
                "keep `turns` for a deterministic script, `simulated_user` for a persona",
            locator="turns")
    if case.body.strip() and (case.turns or case.is_simulated):
        add("EVC002", "info",
            "the body is ignored because `turns`/`simulated_user` is set",
            fix="move the first prompt into `turns[0]`, or delete the body so nobody "
                "edits text that never reaches the agent", locator="body")

    out.extend(_validate_keys(meta, add=add))
    out.extend(_validate_category(case, add=add))
    out.extend(_validate_env(meta, add=add))
    out.extend(_validate_overrides(meta, add=add))
    out.extend(_validate_paths(case, add=add))

    # -- graders -------------------------------------------------------
    if not case.graders:
        add("EVC060", "warn", "no graders: this case can never fail",
            fix="add at least one grader under graders/. A case with no assertion still "
                "runs and still costs tokens, and reports PASSED whatever the agent did.")
    for grader in case.graders:
        out.extend(graders_mod.validate_grader(
            grader.meta, grader.body, path=grader.path, name=grader.name))
        for error in grader.errors:
            out.append(Finding(
                id="EVC010", severity="error", area="grader",
                message=f"grader {grader.name!r}: {error}", path=grader.path,
                fix="the runner skips a grader it cannot parse, so the case silently "
                    "loses an assertion", source=_SRC_CASE,
            ))
        out.extend(_validate_criteria(grader, agent_tools=agent_tools, mock_tools=mock_tools))

    out.extend(_validate_tool_names(case, agent_tools=agent_tools, mock_tools=mock_tools))
    out.extend(_validate_case_shape(case, add=add))
    return out


def _validate_keys(meta: dict[str, Any], *, add) -> list[Finding]:
    """EVC002: a key the runner does not read is a silent no-op."""
    for key in meta:
        if key in CASE_KEYS:
            continue
        close = graders_mod._closest(key, sorted(CASE_KEYS))
        add("EVC002", "warn", f"unknown frontmatter key {key!r}",
            fix=(f"did you mean {close!r}?" if close
                 else "case keys: " + ", ".join(sorted(CASE_KEYS))),
            locator=key)
    for key in _LIST_KEYS:
        value = meta.get(key)
        if value is not None and not isinstance(value, list):
            add("EVC002", "error", f"`{key}` must be a list, got {type(value).__name__}",
                fix=f"{key}: [a, b]", locator=key)
    for key in _POSITIVE_INT_KEYS:
        value = meta.get(key)
        if value is None or isinstance(value, bool):
            if isinstance(value, bool):
                add("EVC002", "error", f"`{key}` must be an integer, got a boolean", locator=key)
            continue
        if not isinstance(value, int) or value < 1:
            add("EVC002", "error", f"`{key}` must be an integer >= 1, got {value!r}", locator=key)
    agent = meta.get("agent")
    if agent is not None:
        if not isinstance(agent, str) or not AGENT_ENTRY.match(agent.strip()):
            add("EVC002", "error", f"`agent` must be `module:function`, got {agent!r}",
                fix="e.g. `agent: agent:build_options`", locator="agent")
    return []


def _validate_category(case: LoadedCase, *, add) -> list[Finding]:
    """EVC030/EVC031: the category is what makes a suite's shape legible."""
    category = case.meta.get("category")
    if category in (None, ""):
        add("EVC030", "info", "no `category`",
            fix="set one of " + ", ".join(CATEGORIES) + ". The coverage matrix and the "
                "tier defaults are built from it, so an uncategorised case is invisible "
                "in every report about suite balance.", locator="category")
        return []
    if not isinstance(category, str) or category.strip() not in CATEGORIES:
        add("EVC031", "warn", f"unknown `category` {category!r}",
            fix="use one of: " + ", ".join(CATEGORIES), locator="category")
    return []


def _validate_env(meta: dict[str, Any], *, add) -> list[Finding]:
    """EVC007: an `env` key outside the `EVAL_` namespace."""
    env = meta.get("env")
    if env is None:
        return []
    if not isinstance(env, dict):
        add("EVC007", "error", f"`env` must be a mapping, got {type(env).__name__}", locator="env")
        return []
    for key in env:
        if not str(key).startswith(ENV_PREFIX):
            add("EVC007", "error", f"env key {key!r} does not start {ENV_PREFIX!r}",
                fix=f"rename it to {ENV_PREFIX}{str(key).lstrip('_')}. The prefix keeps a case "
                    "from reaching the credential chain or the model policy: a case that "
                    "could set ANTHROPIC_API_KEY or CLAUDE_MODEL would change what the run "
                    "bills and which model answered, invisibly.",
                source="this plugin's isolation rule (CONTRACTS §1)", locator=f"env.{key}")
    return []


def _validate_overrides(meta: dict[str, Any], *, add) -> list[Finding]:
    """EVC003 / EVC004 / EVC042: `overrides` against the real option list.

    Two lists, because "not an option" and "an option the runner owns" are
    different mistakes with different fixes. `max_turns: 12` in `overrides` is
    fine; `cwd: /tmp` is not, because the runner creates a fresh working
    directory per run and a case that moved it would break isolation.
    """
    overrides = meta.get("overrides")
    if overrides is None:
        return []
    if not isinstance(overrides, dict):
        add("EVC003", "error", f"`overrides` must be a mapping, got {type(overrides).__name__}",
            locator="overrides")
        return []

    for key, value in overrides.items():
        name = str(key)
        if name not in OPTION_NAMES:
            close = graders_mod._closest(name, list(OPTION_NAMES))
            add("EVC003", "error", f"`overrides.{name}` is not a ClaudeAgentOptions field",
                fix=(f"did you mean {close!r}?" if close else
                     "see the option list in skills/agent-review/references/options-reference.md"),
                source=_SRC_OPTIONS, locator=f"overrides.{name}")
            continue
        if name not in OVERRIDABLE_OPTIONS:
            add("EVC004", "error",
                f"`overrides.{name}` is a real option but the runner owns it",
                fix=f"{name} is set by the runner (fresh cwd, capture hooks, mock servers, "
                    "session handling) or is not JSON-expressible. Remove it; if the case "
                    "needs different behaviour there, it needs a different agent entry point.",
                source=_SRC_OPTIONS, locator=f"overrides.{name}")
            continue
        if name in DEPRECATED_OPTIONS:
            replacement = {"max_thinking_tokens": "`thinking`",
                           "debug_stderr": "nothing — the transport no longer reads it"}
            add("EVC042", "warn", f"`overrides.{name}` is deprecated",
                fix=f"use {replacement.get(name, 'the current option')}",
                source=_SRC_OPTIONS, locator=f"overrides.{name}")
        if name == "allowed_tools" and isinstance(value, list) and "Skill" in [str(v) for v in value]:
            add("EVC042", "warn", "`allowed_tools` contains \"Skill\"",
                fix="use the `skills` option instead; naming the Skill tool in allowed_tools "
                    "is the older form and does not load the skills themselves",
                source=_SRC_OPTIONS, locator="overrides.allowed_tools")
        if name in ("setting_sources", "strict_mcp_config"):
            add("EVC042", "info", f"`overrides.{name}` overrides the runner's isolation default",
                fix="results stop being portable between machines: with ambient settings and "
                    "MCP servers loaded, the same prompt was measured at 17x the cost. The "
                    "trace records the override so a reader can see why.",
                source=_SRC_ISOLATION, locator=f"overrides.{name}")
    return []


def _validate_paths(case: LoadedCase, *, add) -> list[Finding]:
    """`simulated_user`, `faults` and `mocks` must point at things that exist."""
    root = Path(case.dir)
    evals_dir = root.parent
    for key in ("simulated_user", "faults"):
        value = case.meta.get(key)
        if not value:
            continue
        if not isinstance(value, str):
            add("EVC002", "error", f"`{key}` must be a path, got {type(value).__name__}", locator=key)
            continue
        candidates = [root / value, evals_dir / value]
        if not any(c.is_file() for c in candidates):
            add("EVC002", "error", f"`{key}` points at a missing file: {value}",
                fix=f"relative to the case directory or to {evals_dir.name}/", locator=key)
    mocks = case.meta.get("mocks")
    if isinstance(mocks, list):
        for server in mocks:
            server_dir = evals_dir / "mocks" / str(server)
            if not server_dir.is_dir():
                add("EVC002", "error", f"`mocks` names {server!r}, which has no directory",
                    fix=f"create {evals_dir.name}/mocks/{server}/<tool>.md, one file per tool",
                    locator="mocks")
    script = case.meta.get("scaffold_script")
    if script is not None and not isinstance(script, str):
        add("EVC002", "error", "`scaffold_script` must be a string (a bash command line)",
            locator="scaffold_script")
    return []


def _validate_criteria(
    grader: LoadedGrader,
    *,
    agent_tools: set[str] | None,
    mock_tools: set[str] | None,
) -> list[Finding]:
    """EVC050: lint an `llm` grader's criteria through `rubrics.py`.

    One finding per grader, with every critique attached, because five findings
    about one paragraph read as five problems when they are one.
    """
    if grader.type != "llm":
        return []
    known = set(agent_tools or set()) | set(mock_tools or set())
    critiques = rubrics.lint_criteria(grader.body, known_tools=known or None)
    if not critiques:
        return []
    severity = rubrics.severity_of(critiques)
    return [Finding(
        id="EVC050", severity=severity, area="grader",
        message=f"grader {grader.name!r}: weak criteria — " + " | ".join(critiques),
        path=grader.path, locator="body",
        fix="a judge answers exactly the question it is asked; an unstable question "
            "produces an unstable verdict, and majority voting hides that instead of "
            "fixing it. See build_positive_rubric / build_restraint_rubric in rubrics.py.",
        source="this plugin's criteria-authoring rules",
    )]


def _validate_tool_names(
    case: LoadedCase,
    *,
    agent_tools: set[str] | None,
    mock_tools: set[str] | None,
) -> list[Finding]:
    """EVC020: a grader naming a tool nothing provides asserts nothing.

    The check is aware of three things that would otherwise produce false
    positives:

    * `Task` and `Agent` are the same tool under two names.
    * `StructuredOutput` is synthesized by the CLI, so no agent declares it.
    * an unqualified name (`reserve_book`) may be the tail of a qualified one
      (`mcp__library__reserve_book`); that is a warning about the *name*, not a
      missing tool, so it is reported once with the qualified form as the fix.
    """
    if agent_tools is None and mock_tools is None:
        return []
    known = {graders_mod.normalize_tool_name(t) for t in (agent_tools or set())}
    known |= {graders_mod.normalize_tool_name(t) for t in (mock_tools or set())}
    known |= {graders_mod.normalize_tool_name(t) for t in SUBAGENT_TOOL_NAMES}
    known |= set(SYNTHETIC_TOOLS)
    if not known:
        return []

    out: list[Finding] = []
    for grader in case.graders:
        spec = graders_mod.spec_for(grader.type)
        if spec is None or not spec.tool_shaped:
            continue
        for name in graders_mod.grader_tool_names(grader.meta):
            normalized = graders_mod.normalize_tool_name(name)
            if normalized in known:
                continue
            qualified = sorted(t for t in known if t.endswith(f"__{name}") or t.endswith(f"_{name}"))
            if qualified:
                out.append(Finding(
                    id="EVC020", severity="warn", area="grader",
                    message=f"grader {grader.name!r}: tool {name!r} is not a tool name; "
                            f"the agent exposes {qualified[0]!r}",
                    path=grader.path,
                    fix=f"use the qualified name `{qualified[0]}`. MCP tools reach the model "
                        "as `mcp__<server>__<tool>`, and the trace records that form, so an "
                        "unqualified name matches nothing.",
                    source=_SRC_MCP_NAMES,
                ))
                continue
            if name.startswith("mcp__"):
                server = name.split("__")[1] if len(name.split("__")) > 2 else "?"
                out.append(Finding(
                    id="EVC020", severity="warn", area="grader",
                    message=f"grader {grader.name!r}: no tool {name!r} "
                            f"(no server {server!r} among the agent's or the mocks')",
                    path=grader.path,
                    fix="add the server to the agent, add a mock under mocks/<server>/, or "
                        "fix the name — a grader naming a tool nothing provides passes "
                        "`no_tool` trivially and fails `tool_used` always.",
                    source=_SRC_MCP_NAMES,
                ))
                continue
            out.append(Finding(
                id="EVC020", severity="warn", area="grader",
                message=f"grader {grader.name!r}: tool {name!r} is neither an agent tool "
                        "nor a mock",
                path=grader.path,
                fix="known tools: " + ", ".join(sorted(known)[:8])
                    + ("…" if len(known) > 8 else ""),
                source=_SRC_MCP_NAMES,
            ))
    return out


def _validate_case_shape(case: LoadedCase, *, add) -> list[Finding]:
    """EVC040 / EVC041: does the scoring match the kind of case this is?"""
    # EVC040 — a persona drives the conversation, so its trajectory is not fixed.
    if case.is_simulated:
        for grader in case.graders:
            if grader.type in ("trajectory", "no_tool"):
                add("EVC040", "error",
                    f"grader {grader.name!r} is a {grader.type} check on a simulated-user case",
                    fix="a persona chooses what to ask, so the tool sequence is not this "
                        "case's to predict. Assert on the outcome instead (`llm` criteria on "
                        "the final text, `tool_used` with `min`/`max`, `final_text`), or drop "
                        "`simulated_user` and script the turns.",
                    where=grader.path)

    # EVC041 — a restraint case scored leniently is not scored.
    restraint = _looks_like_restraint(case)
    if restraint:
        has_restraint_check = any(g.type == "no_tool" for g in case.graders) or any(
            g.type == "tool_used" and _is_must_not(g.meta) for g in case.graders
        )
        for grader in case.graders:
            if grader.type != "trajectory":
                continue
            match = str(grader.meta.get("match") or "IN_ORDER").upper()
            if match in LENIENT_MATCHES:
                add("EVC041", "warn",
                    f"{restraint} case scored with `trajectory: match: {match}`",
                    fix=f"{match} allows calls the expectation does not name — including the "
                        "call this case exists to forbid. Use `match: EXACT`, or assert the "
                        "restraint directly with a `no_tool` grader.",
                    where=grader.path)
        if not has_restraint_check and case.graders:
            add("EVC041", "warn",
                f"{restraint} case has no restraint check",
                fix="add a `no_tool` grader naming the tool the agent must not call (or a "
                    "`tool_used` with `max: 0`). Without one, nothing distinguishes a "
                    "refusal from a compliant agent that happened to phrase it politely.")
    return []


def _looks_like_restraint(case: LoadedCase) -> str | None:
    """Is this a case about what the agent must NOT do?"""
    if case.category == "adversarial":
        return "adversarial"
    haystack = [case.name, *case.tags]
    if any(RESTRAINT_PATTERN.search(str(item)) for item in haystack):
        return "refusal-shaped"
    for grader in case.graders:
        if grader.type == "llm" and rubrics.is_restraint_criteria(grader.body):
            return "refusal-shaped"
    return None


def _is_must_not(meta: dict[str, Any]) -> bool:
    """`tool_used` with `max: 0` is the "must not" form."""
    return meta.get("max") == 0


def validate_suite(
    evals_dir: Path | str,
    *,
    agent_tools: set[str] | None = None,
    mock_tools: set[str] | None = None,
    config: Any | None = None,
) -> list[Finding]:
    """Every case in a suite, plus the suite-level checks (EVC005)."""
    out: list[Finding] = []
    for stray in stray_prompt_files(evals_dir):
        out.append(Finding(
            id="EVC005", severity="warn", area="case",
            message="a prompt.md that is not inside a case directory, so it never runs",
            path=stray,
            fix="a case is an immediate subdirectory of evals/ holding prompt.md. Move it "
                "into its own directory, or delete it.",
            source=_SRC_CASE,
        ))
    seen: dict[str, str] = {}
    for case in iter_cases(evals_dir):
        out.extend(validate_case(
            case, agent_tools=agent_tools, mock_tools=mock_tools, config=config))
        if case.name in seen:
            out.append(Finding(
                id="EVC002", severity="warn", area="case",
                message=f"two cases are both named {case.name!r}",
                path=case.prompt_path,
                fix=f"the other is {seen[case.name]}. Result files are keyed by name, so one "
                    "overwrites the other.", source=_SRC_CASE,
            ))
        else:
            seen[case.name] = case.dir
    return out


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------

def case_summary(case: LoadedCase) -> dict[str, Any]:
    """A one-line description of a case, for a report or a table.

    `tier` is the cheapest tier that can run it: `judge` when any grader is an
    `llm` check, `free` otherwise. That is what a per-PR gate filters on.
    """
    return {
        "name": case.name,
        "dir": case.dir,
        "category": case.category,
        "tags": case.tags,
        "grader_types": sorted(set(case.grader_types)),
        "grader_count": len(case.graders),
        "tier": case.tier,
        "turns": len(case.turns) or (None if not case.is_simulated else "simulated"),
        "simulated_user": case.meta.get("simulated_user") or None,
        "mocks": case.meta.get("mocks") or [],
        "runs": case.meta.get("runs"),
        "ok": case.ok,
    }


def suite_summary(evals_dir: Path | str) -> dict[str, Any]:
    """Shape of a whole suite: counts by category, by grader type, by tier."""
    cases = list(iter_cases(evals_dir))
    by_category: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for case in cases:
        by_category[case.category or "(none)"] = by_category.get(case.category or "(none)", 0) + 1
        by_tier[case.tier] = by_tier.get(case.tier, 0) + 1
        for grader_type in case.grader_types:
            by_type[grader_type] = by_type.get(grader_type, 0) + 1
    return {
        "cases": len(cases),
        "by_category": dict(sorted(by_category.items())),
        "by_grader_type": dict(sorted(by_type.items())),
        "by_tier": dict(sorted(by_tier.items())),
        "without_graders": [c.name for c in cases if not c.graders],
        "summaries": [case_summary(c) for c in cases],
    }
