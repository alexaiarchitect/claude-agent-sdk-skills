"""Read `eval_config.json`, the cases and their graders; build the options.

Nothing here spends anything. Every refusal this module raises happens before a
session starts, which is the point: an `overrides` typo or a missing model must
cost nothing. Grader and case files are read with the shared frontmatter reader
(`frontmatter.py`, byte-identical to the plugin's copy), never a YAML library.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import (
    DEFAULT_JUDGE_MODEL,
    DEFAULT_MODEL,
    DEPRECATED_OPTIONS,
    ISOLATION_DEFAULTS,
    MODEL_ENV_VAR,
    OPTION_NAMES,
    OVERRIDABLE_OPTIONS,
    SCHEMA_EVAL_CONFIG,
    EvalError,
)
from . import frontmatter

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

#: Keys a `prompt.md` header may carry (CONTRACTS section 1).
CASE_KEYS = frozenset({
    "name", "tags", "category", "runs", "max_turns", "timeout_seconds", "agent", "turns",
    "simulated_user", "overrides", "mocks", "faults", "env", "scaffold_script",
})

CATEGORIES = ("happy", "edge", "adversarial", "memory", "regression")

#: type -> (tier, required field names). `llm` takes its criteria from the body.
GRADER_SPEC: dict[str, tuple[str, tuple[str, ...]]] = {
    "llm": ("judge", ()),
    "regex": ("free", ("pattern",)),
    "tool_used": ("free", ("tool",)),
    "tool_order": ("free", ("before", "after")),
    "file_exists": ("free", ("path",)),
    "trajectory": ("free", ("expected",)),
    "structured_output": ("free", ()),
    "budget": ("free", ()),
    "hook_event": ("free", ("event",)),
    "final_text": ("free", ("reference",)),
    "no_tool": ("free", ("tools",)),
    "terminal": ("free", ()),
}

BUDGET_CEILINGS = (
    "max_cost_usd", "max_turns", "max_input_tokens", "max_output_tokens", "max_duration_ms",
    "max_cache_read_tokens", "max_cache_creation_tokens",
)


def expand_env(value: Any) -> Any:
    """Expand `${VAR}` and `${VAR:-default}` in strings, recursively in containers."""
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name) or (default if default is not None else "")
        return _ENV_REF.sub(_sub, value)
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    return value


# -- config -----------------------------------------------------------------

@dataclass
class TierSpec:
    name: str
    graders: list[str] = field(default_factory=lambda: ["free"])
    runs: int = 1
    threshold: float = 1.0
    pass_k: int | None = None


@dataclass
class Config:
    """`evals/eval_config.json`, with `${VAR:-default}` already expanded."""

    evals_dir: Path
    schema: str = SCHEMA_EVAL_CONFIG
    runner_version: str = ""
    agent: str = "agent:build_options"
    model: str | None = None
    credential: str = "auto"
    concurrency: int = 1
    on_usage_limit: str = "not_evaluated"
    isolation: dict[str, Any] = field(default_factory=lambda: dict(ISOLATION_DEFAULTS))
    judge: dict[str, Any] = field(default_factory=lambda: {
        "model": DEFAULT_JUDGE_MODEL, "samples": 3, "vote": "majority", "effort": "low",
    })
    tiers: dict[str, TierSpec] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    results_dir: str = "evals/results"
    trace: dict[str, Any] = field(default_factory=lambda: {"include_thinking": False, "redact_env": []})
    raw: dict[str, Any] = field(default_factory=dict)

    def tier(self, name: str) -> TierSpec:
        if name in self.tiers:
            return self.tiers[name]
        # The grader-tier names double as ad-hoc tiers: `--tier free` runs only
        # the free graders, `--tier judge` only the judge ones, `--tier run`
        # executes the agent and grades everything free.
        if name == "free":
            return TierSpec("free", graders=["free"], runs=1, threshold=1.0)
        if name == "run":
            return TierSpec("run", graders=["free"], runs=1, threshold=1.0)
        if name == "judge":
            return TierSpec("judge", graders=["judge"], runs=1, threshold=1.0)
        raise EvalError(
            f"unknown tier {name!r}; eval_config.json defines {sorted(self.tiers) or 'none'}",
            code="CFG020",
        )


DEFAULT_TIERS = {
    "pr": TierSpec("pr", graders=["free"], runs=1, threshold=1.0),
    "nightly": TierSpec("nightly", graders=["free", "judge"], runs=3, threshold=0.8, pass_k=3),
}


def load_config(evals_dir: Path) -> Config:
    path = Path(evals_dir) / "eval_config.json"
    if not path.is_file():
        raise EvalError(
            f"no eval config at {path}",
            code="CFG001",
            fix="run the plugin's eval scaffold, or write evals/eval_config.json by hand",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"{path}: {exc}", code="CFG001") from exc
    if not isinstance(raw, dict):
        raise EvalError(f"{path}: expected a JSON object", code="CFG001")

    expanded = expand_env(raw)
    tiers: dict[str, TierSpec] = dict(DEFAULT_TIERS) if "tiers" not in expanded else {}
    for name, spec in (expanded.get("tiers") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        tiers[name] = TierSpec(
            name=name,
            graders=list(spec.get("graders") or ["free"]),
            runs=int(spec.get("runs", 1)),
            threshold=float(spec.get("threshold", 1.0)),
            pass_k=spec.get("pass_k"),
        )

    isolation = dict(ISOLATION_DEFAULTS)
    isolation.update(expanded.get("isolation") or {})
    judge = {"model": DEFAULT_JUDGE_MODEL, "samples": 3, "vote": "majority", "effort": "low"}
    judge.update(expanded.get("judge") or {})

    config = Config(
        evals_dir=Path(evals_dir),
        schema=expanded.get("schema", SCHEMA_EVAL_CONFIG),
        runner_version=str(expanded.get("runner_version") or ""),
        agent=expanded.get("agent") or "agent:build_options",
        model=(expanded.get("model") or None),
        credential=expanded.get("credential", "auto"),
        concurrency=int(expanded.get("concurrency", 1) or 1),
        on_usage_limit=expanded.get("on_usage_limit", "not_evaluated"),
        isolation=isolation,
        judge=judge,
        tiers=tiers,
        budget=expanded.get("budget") or {},
        results_dir=expanded.get("results_dir") or "evals/results",
        trace=expanded.get("trace") or {"include_thinking": False, "redact_env": []},
        raw=raw,
    )
    if int(judge.get("samples", 3)) < 1:
        raise EvalError("judge.samples must be at least 1", code="CFG012")
    return config


# -- graders and cases ------------------------------------------------------

@dataclass
class Grader:
    """One `graders/<slug>.md`: its frontmatter, its prose and its tier."""

    name: str
    type: str
    fields: dict[str, Any]
    body: str
    path: Path
    tier: str = "free"

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)


@dataclass
class Case:
    """One `evals/<case>/` directory."""

    name: str
    dir: Path
    prompt: str
    tags: list[str] = field(default_factory=list)
    category: str | None = None
    runs: int | None = None
    max_turns: int | None = None
    timeout_seconds: int = 180
    agent: str | None = None
    turns: list[str] = field(default_factory=list)
    simulated_user: str | None = None
    overrides: dict[str, Any] = field(default_factory=dict)
    mocks: list[str] = field(default_factory=list)
    faults: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    scaffold_script: str | None = None
    graders: list[Grader] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def graders_for(self, tiers: list[str]) -> list[Grader]:
        wanted = set(tiers)
        return [g for g in self.graders if g.tier in wanted]


def load_graders(case_dir: Path) -> list[Grader]:
    graders_dir = Path(case_dir) / "graders"
    if not graders_dir.is_dir():
        return []
    out: list[Grader] = []
    for path in sorted(graders_dir.glob("*.md")):
        try:
            doc = frontmatter.parse(path.read_text(encoding="utf-8"))
        except (OSError, frontmatter.FrontmatterError) as exc:
            raise EvalError(f"{path}: {exc}", code="EVC010") from exc
        meta = doc.meta or {}
        gtype = meta.get("type")
        if gtype not in GRADER_SPEC:
            raise EvalError(
                f"{path}: unknown grader type {gtype!r}; known types are "
                + ", ".join(sorted(GRADER_SPEC)),
                code="EVC010",
            )
        tier, required = GRADER_SPEC[gtype]
        fields_ = {k: v for k, v in meta.items() if k != "type"}
        missing = [name for name in required if fields_.get(name) in (None, "", [], {})]
        if gtype == "structured_output" and not (fields_.get("schema") or fields_.get("schema_file")):
            missing.append("schema or schema_file")
        if gtype == "budget" and not any(fields_.get(name) is not None for name in BUDGET_CEILINGS):
            missing.append("at least one of " + ", ".join(BUDGET_CEILINGS))
        if gtype == "terminal" and not (fields_.get("subtype") or fields_.get("terminal_reason")):
            missing.append("subtype or terminal_reason")
        if gtype == "llm" and not (doc.body.strip() or fields_.get("criteria")):
            missing.append("criteria (the grader body)")
        if missing:
            raise EvalError(
                f"{path}: grader type {gtype!r} is missing " + ", ".join(missing),
                code="EVC011",
            )
        out.append(Grader(
            name=meta.get("name") or path.stem, type=gtype, fields=fields_,
            body=doc.body, path=path, tier=tier,
        ))
    return out


def load_case(case_dir: Path) -> Case:
    path = Path(case_dir) / "prompt.md"
    if not path.is_file():
        raise EvalError(f"{case_dir}: no prompt.md", code="EVC001")
    try:
        doc = frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, frontmatter.FrontmatterError) as exc:
        raise EvalError(f"{path}: {exc}", code="EVC002") from exc
    meta = doc.meta or {}
    unknown = sorted(set(meta) - CASE_KEYS)
    if unknown:
        raise EvalError(
            f"{path}: unknown frontmatter key(s) {', '.join(unknown)}; known keys are "
            + ", ".join(sorted(CASE_KEYS)),
            code="EVC002",
        )
    turns = [str(t) for t in (meta.get("turns") or [])]
    simulated = meta.get("simulated_user")
    if turns and simulated:
        raise EvalError(f"{path}: `turns` and `simulated_user` are mutually exclusive", code="EVC001")
    body = doc.body.strip()
    if not body and not turns and not simulated:
        raise EvalError(f"{path}: no prompt body, no `turns` and no `simulated_user`", code="EVC001")

    env = {str(k): str(v) for k, v in (meta.get("env") or {}).items()}
    bad_env = sorted(k for k in env if not k.startswith("EVAL_"))
    if bad_env:
        raise EvalError(f"{path}: env keys must start with EVAL_ ({', '.join(bad_env)})", code="EVC002")

    case = Case(
        name=str(meta.get("name") or Path(case_dir).name),
        dir=Path(case_dir),
        prompt=body,
        tags=[str(t) for t in (meta.get("tags") or [])],
        category=meta.get("category"),
        runs=meta.get("runs"),
        max_turns=meta.get("max_turns"),
        timeout_seconds=int(meta.get("timeout_seconds") or 180),
        agent=meta.get("agent"),
        turns=turns,
        simulated_user=simulated,
        overrides=dict(meta.get("overrides") or {}),
        mocks=[str(m) for m in (meta.get("mocks") or [])],
        faults=meta.get("faults"),
        env=env,
        scaffold_script=meta.get("scaffold_script"),
        graders=load_graders(case_dir),
    )
    if case.category is None:
        case.notes.append("EVC030: no `category`; the suite cannot report coverage by category")
    elif case.category not in CATEGORIES:
        raise EvalError(
            f"{path}: category {case.category!r} is not one of " + ", ".join(CATEGORIES),
            code="EVC002",
        )
    return case


def discover_cases(evals_dir: Path, *, case_glob: str | None = None,
                   tag: str | None = None) -> list[Case]:
    root = Path(evals_dir)
    if not root.is_dir():
        raise EvalError(f"no evals directory at {root}", code="CFG001")
    reserved = {"mocks", "results", "runner", "personas", "faults", "fixtures", "__pycache__"}
    cases: list[Case] = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if child.name in reserved or child.name.startswith("."):
            continue
        if not (child / "prompt.md").is_file():
            continue
        if case_glob and not (fnmatch.fnmatch(child.name, case_glob)):
            continue
        case = load_case(child)
        if tag and tag not in case.tags:
            continue
        cases.append(case)
    return cases


# -- overrides --------------------------------------------------------------

@dataclass
class OverrideCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_overrides(overrides: dict[str, Any], live_fields: Any = None) -> OverrideCheck:
    """Check `overrides` names against the embedded lists and the live dataclass.

    `live_fields` is `ClaudeAgentOptions.__dataclass_fields__`; when it is given,
    a name the installed SDK does not have is EVC003 even if the embedded list
    knows it, and a name the SDK has that the embedded list does not is reported
    as a warning so an SDK upgrade is visible rather than silent.
    """
    check = OverrideCheck()
    known_live = set(live_fields) if live_fields is not None else None
    for name, value in (overrides or {}).items():
        in_embedded = name in OPTION_NAMES
        in_live = True if known_live is None else name in known_live
        if not in_live:
            check.errors.append(
                f"EVC003: `overrides.{name}` is not a ClaudeAgentOptions field in the installed SDK"
            )
            continue
        if not in_embedded and known_live is None:
            # Nothing to check against but the pinned list, so an unknown name is
            # a typo, not evidence of a newer SDK.
            check.errors.append(
                f"EVC003: `overrides.{name}` is not a ClaudeAgentOptions field"
            )
            continue
        if not in_embedded:
            check.warnings.append(
                f"EVC003: `overrides.{name}` exists in the installed SDK but not in the runner's "
                "pinned option list; the runner copy is older than the SDK"
            )
        elif name not in OVERRIDABLE_OPTIONS:
            check.errors.append(
                f"EVC004: `overrides.{name}` exists but is runner-owned or not JSON-expressible; "
                "the runner sets it itself"
            )
            continue
        if name in DEPRECATED_OPTIONS:
            replacement = {"max_thinking_tokens": "thinking", "debug_stderr": "the stderr callback"}
            check.warnings.append(
                f"EVC003: `overrides.{name}` is deprecated upstream; use {replacement[name]}"
            )
        if name == "allowed_tools" and isinstance(value, list) and "Skill" in value:
            check.warnings.append(
                "EVC003: `allowed_tools` containing \"Skill\" is deprecated; use `skills` instead"
            )
    return check


#: The mode the runner resolves when nobody else does (CONTRACTS section 13.1).
#: With `permission_mode` unset the CLI picks the mode, and which one depends on
#: its version and environment. Documented
#: (`permission-modes#which-mode-a-non-interactive-run-starts-in`, read at
#: 2.1.312): "In Claude Code v2.1.302 or later, `claude -p` and Agent SDK runs
#: with no permission mode set start in Manual mode" (`default`; measured on
#: 2.1.310), and "Before v2.1.302, these runs could start in auto mode if they
#: didn't fetch feature flags". Measured on CLI 2.1.285-2.1.301: a headless
#: session that fetches feature flags starts in `default` (CLI 2.1.292 and
#: 2.1.301); one that does not (third-party provider, telemetry off, first run
#: after an install or upgrade) starts in `auto`, where a classifier reviews each
#: tool call and a bare allow rule no longer settles it. An eval has to know
#: which rules were in force, so the runner decides: `dontAsk` for unattended
#: runs either way.
PERMISSION_MODE_DEFAULT = "dontAsk"


def resolve_permission_mode(options: Any) -> tuple[Any, str]:
    """Return (options with a mode set, `"agent"` or `"runner-default"`).

    `"agent"` means the mode came from the options as handed over — the agent's
    `build_options()` or a case's `overrides` — and the runner left it alone.
    """
    if getattr(options, "permission_mode", None):
        return options, "agent"
    return dataclasses.replace(options, permission_mode=PERMISSION_MODE_DEFAULT), "runner-default"


def apply_overrides(
    options: Any, overrides: dict[str, Any], isolation: dict[str, Any],
) -> tuple[Any, dict[str, Any], str]:
    """Return (new options, the isolation actually applied, the mode's source).

    The isolation defaults win over whatever the agent built, and the case's own
    `overrides` win over the isolation defaults — a case that opts out is
    recorded in the trace `init` event so the loss of portability is visible.
    `permission_mode` is resolved last, and only when it is still unset, so an
    explicit mode from either side always wins.
    """
    applied = dict(isolation)
    changes: dict[str, Any] = dict(applied)
    for name, value in (overrides or {}).items():
        changes[name] = value
        if name in applied:
            applied[name] = value
    built, source = resolve_permission_mode(dataclasses.replace(options, **changes))
    return built, applied, source


# -- the agent under test ---------------------------------------------------

def import_entry(entry: str, project_dir: Path | None = None) -> Callable[[], Any]:
    """Import `module:function` and return it, without calling it."""
    if ":" not in entry:
        raise EvalError(
            f"agent entry {entry!r} must be `module:function` (e.g. agent:build_options)",
            code="EVC002",
        )
    module_name, _, func_name = entry.partition(":")
    root = str(Path(project_dir).resolve()) if project_dir else None
    if root and root not in sys.path:
        sys.path.insert(0, root)
    try:
        module = __import__(module_name, fromlist=["*"])
    except BaseException as exc:  # an agent's import-time code can raise anything
        raise EvalError(
            f"importing {module_name!r} failed: {type(exc).__name__}: {exc}",
            code="AGT001",
            fix="run the module by hand in the project's interpreter to see the traceback",
        ) from exc
    func = getattr(module, func_name, None)
    if func is None or not callable(func):
        raise EvalError(
            f"{module_name!r} has no callable {func_name!r}; the convention is "
            "`agent.py:build_options() -> ClaudeAgentOptions`",
            code="AGT002",
        )
    return func


def resolve_agent_entry(case: Case, config: Config) -> str:
    return case.agent or config.agent or os.environ.get("AGENT_ENTRY") or "agent:build_options"


def resolve_model(case: Case, config: Config, agent_model: str | None) -> str:
    """Case override, then config, then what the agent itself chose. Never the CLI default.

    Measured: the CLI's own default model billed 4x what Sonnet did on the same
    trivial prompt, so inheriting it is never acceptable in an eval.
    """
    override = (case.overrides or {}).get("model")
    if override:
        return str(override)
    if config.model:
        return str(config.model)
    if agent_model:
        return str(agent_model)
    raise EvalError(
        "no model resolved: the case sets no `overrides.model`, eval_config.json has no `model`, "
        "and the agent's own options leave `model` unset. A run would inherit the CLI's default "
        f"model, which is not comparable and measured far more expensive. Set {MODEL_ENV_VAR} "
        f"(eval_config.json's model reads ${{{MODEL_ENV_VAR}:-{DEFAULT_MODEL}}}) or add "
        "`overrides.model` to the case.",
        code="CFG060",
        fix=f"export {MODEL_ENV_VAR}={DEFAULT_MODEL}",
    )


def read_persona(case: Case, evals_dir: Path) -> dict[str, Any]:
    """Load a case's `simulated_user` persona JSON, relative to the case then the suite."""
    if not case.simulated_user:
        return {}
    for base in (case.dir, Path(evals_dir)):
        path = base / case.simulated_user
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EvalError(f"{path}: {exc}", code="SIM001") from exc
    raise EvalError(f"{case.name}: no persona file {case.simulated_user!r}", code="SIM001")


def read_faults(case: Case, evals_dir: Path) -> dict[str, Any]:
    if not case.faults:
        return {}
    for base in (case.dir, Path(evals_dir)):
        path = base / case.faults
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EvalError(f"{path}: {exc}", code="SIM002") from exc
    raise EvalError(f"{case.name}: no faults file {case.faults!r}", code="SIM002")
