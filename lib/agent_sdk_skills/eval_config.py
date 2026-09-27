"""`evals/eval_config.json`: one file deciding what a run costs and proves.

The config is small on purpose. It answers five questions, and nothing else:

1. **Which agent** — `agent: "module:function"`, the entry point the runner imports.
2. **Which model** — `model`, normally `"${CLAUDE_MODEL:-claude-sonnet-5-5}"` so a
   run never inherits the CLI's default. That matters more than it looks: the
   bare `claude -p` default was measured at `claude-fable-5-1` and cost **$0.34**
   for a prompt Sonnet answered for $0.09.
3. **Which checks, how many times** — `tiers`, each naming grader tiers
   (`free`, `judge`), a `runs` count and a `threshold`. A per-PR tier that
   includes `judge` turns every pull request into a token spend.
4. **How isolated** — `isolation: {setting_sources: [], strict_mcp_config: true}`.
   Measured: with the host's ambient settings and MCP servers loaded, the same
   prompt cost **17x** more (21 503 cache-creation tokens of someone's CLAUDE.md).
   Without this block, results are not portable between machines.
5. **What to stop for** — `budget` ceilings and `on_usage_limit`.

Findings, all in the ``CFG`` band:

======  ==========================================================  ========
id      what                                                        severity
======  ==========================================================  ========
CFG001  missing or unreadable                                       error
CFG002  invalid JSON                                                error
CFG003  unknown `schema` string                                     error
CFG010  judge model is retiring                                     warn
CFG011  judge model is retired                                      error
CFG012  `judge.samples` < 1                                         error
CFG013  judge model equals the agent model                          info
CFG020  a tier's name is not one this plugin knows                   warn
CFG021  a tier's `graders` are not a subset of {free, judge}         error
CFG022  a `threshold` outside [0, 1]                                error
CFG023  a tier's `runs` < 1                                         error
CFG030  the pr tier includes judge graders                          warn
CFG040  no `budget` block                                           info
CFG041  `concurrency` > 1 on a subscription                         warn
CFG042  `isolation` missing or disabled                             warn
CFG050  `runner_version` does not match the installed runner        warn
CFG060  `model` is retired/retiring, or unset with no expansion     warn
======  ==========================================================  ========
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import (
    DEFAULT_JUDGE_MODEL,
    DEFAULT_MODEL,
    ISOLATION_DEFAULTS,
    MODEL_ENV_VAR,
    RETIRED_MODELS,
    RETIRING_MODELS,
    RUNNER_VERSION,
)
from .env import classify_model_id
from .graders import TIERS
from .report import Finding

_SRC_CONFIG = "this plugin's config format (CONTRACTS §3)"
_SRC_ISOLATION = "measured: VERIFIED-FACTS §8.4 — 17x cost with ambient settings loaded"
_SRC_MODELS = "platform.claude.com/docs/en/about-claude/models/overview + .../model-deprecations"
_SRC_RATE = "measured: VERIFIED-FACTS §9 — a RateLimitEvent fired on every run at 83% of the 7-day window"
_SRC_JUDGE = "CONTRACTS §9 (judge call shape)"

SCHEMA = "agent-sdk-skills.eval-config/1"
#: Schema strings this plugin can read. A newer one is an error, not a warning:
#: the shapes are versioned so both sides can refuse rather than misread.
KNOWN_SCHEMAS = (SCHEMA,)

CONFIG_NAME = "eval_config.json"

#: Tier names the plugin's own reports, CI templates and defaults assume.
KNOWN_TIER_NAMES = ("pr", "nightly", "free", "run", "judge")
#: The tier a per-PR gate uses; it must stay free so a pull request costs nothing.
PR_TIER = "pr"

VOTE_MODES = ("majority", "unanimous", "any")
USAGE_LIMIT_MODES = ("not_evaluated", "fail", "stop")
NOT_EVALUATED_MODES = ("warn", "fail", "ignore")
CREDENTIAL_MODES = ("auto", "api_key", "oauth_token", "login")

#: `${CLAUDE_MODEL:-claude-sonnet-5-5}` / `${CLAUDE_MODEL}` / `$CLAUDE_MODEL`
EXPANSION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


@dataclass
class LoadedConfig:
    """A parsed `eval_config.json`. `errors` are load failures, not findings."""

    path: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    exists: bool = False

    @property
    def ok(self) -> bool:
        return self.exists and not self.errors

    @property
    def schema(self) -> str | None:
        value = self.data.get("schema")
        return value if isinstance(value, str) else None

    @property
    def model(self) -> str | None:
        value = self.data.get("model")
        return value if isinstance(value, str) else None

    @property
    def judge(self) -> dict[str, Any]:
        value = self.data.get("judge")
        return value if isinstance(value, dict) else {}

    @property
    def judge_model(self) -> str:
        value = self.judge.get("model")
        return value if isinstance(value, str) and value.strip() else DEFAULT_JUDGE_MODEL

    @property
    def tiers(self) -> dict[str, Any]:
        value = self.data.get("tiers")
        return value if isinstance(value, dict) else {}

    @property
    def budget(self) -> dict[str, Any]:
        value = self.data.get("budget")
        return value if isinstance(value, dict) else {}

    @property
    def isolation(self) -> dict[str, Any]:
        value = self.data.get("isolation")
        return value if isinstance(value, dict) else {}

    @property
    def results_dir(self) -> str:
        value = self.data.get("results_dir")
        return value if isinstance(value, str) and value.strip() else "evals/results"

    @property
    def runner_version(self) -> str | None:
        value = self.data.get("runner_version")
        return str(value) if value is not None else None

    @property
    def concurrency(self) -> int:
        value = self.data.get("concurrency")
        return value if isinstance(value, int) and not isinstance(value, bool) else 1

    def resolved_model(self, env: dict[str, str] | None = None) -> str | None:
        """The model after `${CLAUDE_MODEL:-…}` expansion."""
        return expand_model(self.model, env)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "exists": self.exists, "schema": self.schema,
            "model": self.model, "resolved_model": self.resolved_model(),
            "judge_model": self.judge_model, "tiers": sorted(self.tiers),
            "isolation": self.isolation or None, "runner_version": self.runner_version,
            "concurrency": self.concurrency, "errors": self.errors,
        }


def load_config(path: Path | str) -> LoadedConfig:
    """Read `eval_config.json`. Never raises.

    A directory is accepted as well as a file, so callers can pass `evals/`.
    """
    target = Path(path)
    if target.is_dir():
        target = target / CONFIG_NAME
    config = LoadedConfig(path=str(target))
    if not target.is_file():
        return config
    config.exists = True
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        config.errors.append(f"unreadable: {exc}")
        return config
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        config.errors.append(f"invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}")
        return config
    if not isinstance(data, dict):
        config.errors.append(f"the top level must be an object, got {type(data).__name__}")
        return config
    config.data = data
    return config


def expand_model(value: str | None, env: dict[str, str] | None = None) -> str | None:
    """Resolve `${CLAUDE_MODEL:-claude-sonnet-5-5}` against an environment.

    Only the two forms the scaffolds write are supported: `${NAME:-default}` and
    a bare `${NAME}` / `$NAME`. An unset variable with no default expands to the
    empty string, which is what `CFG060` reports — a run with no model inherits
    the CLI's default, and the CLI's default was measured at 4x Sonnet's cost.
    """
    if value is None:
        return None
    source = env if env is not None else os.environ

    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(3)
        default = match.group(2)
        resolved = source.get(name or "")
        if resolved:
            return resolved
        return default if default is not None else ""

    return EXPANSION.sub(replace, value)


def tier(config: LoadedConfig | dict[str, Any], name: str) -> dict[str, Any] | None:
    """One tier's settings by name, or None."""
    data = config.data if isinstance(config, LoadedConfig) else (config or {})
    tiers = data.get("tiers")
    if not isinstance(tiers, dict):
        return None
    value = tiers.get(name)
    return value if isinstance(value, dict) else None


def tier_graders(config: LoadedConfig | dict[str, Any], name: str) -> list[str]:
    """The grader tiers a named tier runs, defaulting to free-only."""
    settings = tier(config, name) or {}
    value = settings.get("graders")
    if isinstance(value, list):
        return [str(v) for v in value]
    return ["free"]


def default_config(
    *,
    model: str | None = None,
    judge_model: str | None = None,
    runner_version: str | None = None,
    agent: str = "agent:build_options",
) -> dict[str, Any]:
    """The document CONTRACTS §3 specifies, ready to write.

    `model` defaults to the env-driven form rather than a literal id, so the
    config never goes stale when a model retires and never silently inherits the
    CLI's (expensive) default.
    """
    return {
        "schema": SCHEMA,
        "runner_version": runner_version or RUNNER_VERSION,
        "agent": agent,
        "model": model or f"${{{MODEL_ENV_VAR}:-{DEFAULT_MODEL}}}",
        "credential": "auto",
        "concurrency": 1,
        "on_usage_limit": "not_evaluated",
        "isolation": dict(ISOLATION_DEFAULTS),
        "judge": {
            "model": judge_model or DEFAULT_JUDGE_MODEL,
            "samples": 3,
            "vote": "majority",
            "effort": "low",
        },
        "tiers": {
            "pr": {"graders": ["free"], "runs": 1, "threshold": 1.0},
            "nightly": {"graders": ["free", "judge"], "runs": 3, "threshold": 0.8, "pass_k": 3},
        },
        "budget": {
            "max_cost_usd_per_run": 1.0,
            "max_cost_usd_total": 25.0,
            "on_not_evaluated": "warn",
        },
        "results_dir": "evals/results",
        "trace": {"include_thinking": False, "redact_env": ["ANTHROPIC_API_KEY"]},
    }


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate_config(
    config: LoadedConfig,
    *,
    runner_copy_version: str | None = None,
    sdk_version: str | None = None,
    credential_kind: str | None = None,
    env: dict[str, str] | None = None,
) -> list[Finding]:
    """Everything wrong with one `eval_config.json`.

    `credential_kind` (`api_key` | `oauth_token` | `login` | `provider` | `none`)
    turns on the subscription-specific check: concurrency above 1 draws on one
    person's usage window, so parallel runs race each other into a rate limit
    that looks like a flaky agent.
    """
    out: list[Finding] = []
    path = config.path

    def add(fid: str, severity: str, message: str, *, fix: str = "",
            source: str = _SRC_CONFIG, locator: str | None = None) -> None:
        out.append(Finding(
            id=fid, severity=severity, area="config", message=message,
            path=path, locator=locator, fix=fix or None, source=source,
        ))

    if not config.exists:
        add("CFG001", "error", "no eval_config.json",
            fix="run `/agent-sdk:eval-criteria` and choose 'write a config', or copy the "
                "default: it pins the model, the isolation defaults and the tier thresholds")
        return out
    for error in config.errors:
        fid = "CFG002" if "JSON" in error else "CFG001"
        add(fid, "error", error, fix="fix the file; nothing else can be validated until it parses")
    if config.errors:
        return out

    out.extend(_validate_schema(config, add=add))
    out.extend(_validate_models(config, add=add, env=env))
    out.extend(_validate_judge(config, add=add))
    out.extend(_validate_tiers(config, add=add))
    out.extend(_validate_budget_and_isolation(config, add=add, credential_kind=credential_kind))
    out.extend(_validate_runner_version(config, add=add, runner_copy_version=runner_copy_version))
    out.extend(_validate_misc(config, add=add))
    del sdk_version                      # reserved: no CFG rule depends on it yet
    return out


def _validate_schema(config: LoadedConfig, *, add) -> list[Finding]:
    schema = config.schema
    if schema is None:
        add("CFG003", "error", "no `schema` string",
            fix=f'add "schema": "{SCHEMA}". The schema is what lets this plugin and the '
                "runner copy refuse a file they cannot read, instead of misreading it.",
            locator="schema")
    elif schema not in KNOWN_SCHEMAS:
        add("CFG003", "error", f"unknown schema {schema!r}",
            fix=f"this plugin reads {', '.join(KNOWN_SCHEMAS)}. A higher version means the "
                "config was written by a newer runner: upgrade the plugin rather than "
                "editing the string.", locator="schema")
    return []


def _validate_models(config: LoadedConfig, *, add, env: dict[str, str] | None) -> list[Finding]:
    """CFG060: the agent model, before anything is spent on it."""
    raw = config.data.get("model")
    if raw is None:
        add("CFG060", "warn", "no `model`",
            fix=f'set "model": "${{{MODEL_ENV_VAR}:-{DEFAULT_MODEL}}}". With no model the run '
                "inherits the CLI's default, which was measured at claude-fable-5-1 and cost "
                "4x Sonnet for the same trivial prompt.",
            source=_SRC_MODELS, locator="model")
        return []
    if not isinstance(raw, str):
        add("CFG060", "error", f"`model` must be a string, got {type(raw).__name__}", locator="model")
        return []

    resolved = expand_model(raw, env)
    has_expansion = bool(EXPANSION.search(raw))
    if not resolved:
        add("CFG060", "warn",
            f"`model` is {raw!r}, which resolves to nothing"
            + (f" ({MODEL_ENV_VAR} is unset and there is no `:-default`)" if has_expansion else ""),
            fix=f'use the defaulted form: "${{{MODEL_ENV_VAR}:-{DEFAULT_MODEL}}}"',
            source=_SRC_MODELS, locator="model")
        return []

    grade = classify_model_id(resolved)
    if grade == "retired":
        add("CFG060", "warn", f"`model` resolves to {resolved!r}, which is retired",
            fix=f"use {DEFAULT_MODEL}. A retired id is refused by the API, so every run "
                "would be an error result rather than a failing eval.",
            source=_SRC_MODELS, locator="model")
    elif grade == "retiring":
        add("CFG060", "warn", f"`model` resolves to {resolved!r}, which is retiring",
            fix=f"move to {DEFAULT_MODEL} before the retirement date, and re-baseline: a "
                "model change moves pass rates, so do it deliberately rather than on the "
                "day the old id stops answering.", source=_SRC_MODELS, locator="model")
    elif not has_expansion and grade in ("pinned", "alias"):
        add("CFG060", "info", f"`model` is hardcoded as {resolved!r}",
            fix=f'prefer "${{{MODEL_ENV_VAR}:-{resolved}}}" so CI and a local run can differ '
                "without editing the config", source=_SRC_MODELS, locator="model")
    elif grade == "unknown":
        add("CFG060", "warn", f"`model` resolves to {resolved!r}, which this plugin does not know",
            fix="check the id against the model overview; a typo becomes a run-time API error",
            source=_SRC_MODELS, locator="model")
    return []


def _validate_judge(config: LoadedConfig, *, add) -> list[Finding]:
    """CFG010–CFG013: the judge is a model too, and its cost is real."""
    judge = config.data.get("judge")
    if judge is None:
        add("CFG012", "info", "no `judge` block; judge graders will use the defaults",
            fix=f'add "judge": {{"model": "{DEFAULT_JUDGE_MODEL}", "samples": 3, '
                '"vote": "majority", "effort": "low"}', locator="judge")
        return []
    if not isinstance(judge, dict):
        add("CFG012", "error", f"`judge` must be an object, got {type(judge).__name__}",
            locator="judge")
        return []

    model = judge.get("model")
    if isinstance(model, str) and model.strip():
        name = model.strip()
        if name in RETIRED_MODELS or classify_model_id(name) == "retired":
            add("CFG011", "error", f"judge model {name!r} is retired",
                fix=f"use {DEFAULT_JUDGE_MODEL}. Every judge grader would return an error "
                    "result, which the runner reports as NOT_EVALUATED — so the suite would "
                    "go quiet rather than fail.", source=_SRC_MODELS, locator="judge.model")
        elif name in RETIRING_MODELS:
            add("CFG010", "warn", f"judge model {name!r} is retiring",
                fix=f"move to {DEFAULT_JUDGE_MODEL} and re-run your calibration set: a judge "
                    "change moves verdicts, so the old and new judge should be compared on "
                    "labelled examples before the switch.", source=_SRC_MODELS, locator="judge.model")
        agent_model = expand_model(config.model) or config.model
        if agent_model and name == agent_model:
            add("CFG013", "info", f"the judge and the agent both use {name!r}",
                fix="a model grading its own output shares its blind spots, and a failure "
                    "mode it cannot see it also cannot mark. Use a different judge model "
                    "when comparability matters more than cost.", source=_SRC_JUDGE,
                locator="judge.model")

    samples = judge.get("samples")
    if samples is not None:
        if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
            add("CFG012", "error", f"`judge.samples` must be an integer >= 1, got {samples!r}",
                fix="3 is the usual choice: one sample is a coin flip on a borderline case, "
                    "and majority voting needs an odd number", locator="judge.samples")
        elif samples % 2 == 0:
            add("CFG012", "info", f"`judge.samples` is {samples}, an even number",
                fix="majority voting has no majority on a tie; use an odd count",
                locator="judge.samples")

    vote = judge.get("vote")
    if vote is not None and str(vote) not in VOTE_MODES:
        add("CFG012", "error", f"unknown `judge.vote` {vote!r}",
            fix="use one of: " + ", ".join(VOTE_MODES), locator="judge.vote")
    return []


def _validate_tiers(config: LoadedConfig, *, add) -> list[Finding]:
    """CFG020–CFG023 and CFG030."""
    tiers = config.data.get("tiers")
    if tiers is None:
        add("CFG020", "warn", "no `tiers` block",
            fix='add at least {"pr": {"graders": ["free"], "runs": 1, "threshold": 1.0}}. '
                "Without tiers every run is a judge run.", locator="tiers")
        return []
    if not isinstance(tiers, dict):
        add("CFG020", "error", f"`tiers` must be an object, got {type(tiers).__name__}",
            locator="tiers")
        return []
    if not tiers:
        add("CFG020", "warn", "`tiers` is empty", fix="define at least a free `pr` tier",
            locator="tiers")

    for name, settings in tiers.items():
        where = f"tiers.{name}"
        if name not in KNOWN_TIER_NAMES:
            add("CFG020", "warn", f"tier {name!r} is not a name this plugin's reports know",
                fix="known names: " + ", ".join(KNOWN_TIER_NAMES)
                    + ". A custom name works, but `--tier` suggestions and the CI templates "
                      "will not mention it.", locator=where)
        if not isinstance(settings, dict):
            add("CFG020", "error", f"tier {name!r} must be an object, got {type(settings).__name__}",
                locator=where)
            continue

        graders = settings.get("graders")
        if graders is None:
            add("CFG021", "warn", f"tier {name!r} does not say which grader tiers it runs",
                fix='add "graders": ["free"] (or ["free", "judge"])', locator=f"{where}.graders")
        elif not isinstance(graders, list):
            add("CFG021", "error", f"tier {name!r}: `graders` must be a list", locator=f"{where}.graders")
        else:
            unknown = [str(g) for g in graders if str(g) not in TIERS]
            if unknown:
                add("CFG021", "error",
                    f"tier {name!r}: {', '.join(repr(u) for u in unknown)} is not a grader tier",
                    fix="grader tiers are exactly " + ", ".join(TIERS)
                        + " — tier is derived from a grader's `type`, never declared, so "
                          "naming a grader *type* here filters nothing",
                    locator=f"{where}.graders")
            if name == PR_TIER and "judge" in [str(g) for g in graders]:
                add("CFG030", "warn", "the `pr` tier includes judge graders",
                    fix="a per-PR gate should cost nothing: keep judge graders in `nightly`. "
                        "Judge calls spend tokens on every push, and their verdicts are a "
                        "distribution, so a borderline case will flap the gate.",
                    locator=f"{where}.graders")

        runs = settings.get("runs")
        if runs is not None and (isinstance(runs, bool) or not isinstance(runs, int) or runs < 1):
            add("CFG023", "error", f"tier {name!r}: `runs` must be an integer >= 1, got {runs!r}",
                locator=f"{where}.runs")

        for key in ("threshold",):
            value = settings.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not 0.0 <= float(value) <= 1.0:
                add("CFG022", "error",
                    f"tier {name!r}: `{key}` must be a number in [0, 1], got {value!r}",
                    fix="a threshold is a pass rate, so 0.8 means four runs in five",
                    locator=f"{where}.{key}")

        pass_k = settings.get("pass_k")
        if pass_k is not None:
            if isinstance(pass_k, bool) or not isinstance(pass_k, int) or pass_k < 1:
                add("CFG023", "error", f"tier {name!r}: `pass_k` must be an integer >= 1, got {pass_k!r}",
                    locator=f"{where}.pass_k")
            elif isinstance(runs, int) and not isinstance(runs, bool) and pass_k > runs:
                add("CFG023", "error",
                    f"tier {name!r}: `pass_k` is {pass_k} but only {runs} run(s) happen",
                    fix=f"pass@{pass_k} cannot be measured from {runs} run(s); raise `runs` "
                        "or lower `pass_k`", locator=f"{where}.pass_k")
    return []


def _validate_budget_and_isolation(
    config: LoadedConfig, *, add, credential_kind: str | None
) -> list[Finding]:
    """CFG040, CFG041, CFG042: cost ceilings, concurrency, isolation."""
    budget = config.data.get("budget")
    if budget is None:
        add("CFG040", "info", "no `budget` block",
            fix='add {"max_cost_usd_per_run": 1.0, "max_cost_usd_total": 25.0, '
                '"on_not_evaluated": "warn"}. Nothing stops a looping agent from spending '
                "the whole session window otherwise.", locator="budget")
    elif not isinstance(budget, dict):
        add("CFG040", "error", f"`budget` must be an object, got {type(budget).__name__}",
            locator="budget")
    else:
        for key in ("max_cost_usd_per_run", "max_cost_usd_total"):
            value = budget.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                add("CFG040", "error", f"`budget.{key}` must be a positive number, got {value!r}",
                    locator=f"budget.{key}")
        mode = budget.get("on_not_evaluated")
        if mode is not None and str(mode) not in NOT_EVALUATED_MODES:
            add("CFG040", "error", f"unknown `budget.on_not_evaluated` {mode!r}",
                fix="use one of: " + ", ".join(NOT_EVALUATED_MODES), locator="budget.on_not_evaluated")
        if isinstance(budget.get("max_cost_usd_per_run"), (int, float)) \
                and isinstance(budget.get("max_cost_usd_total"), (int, float)) \
                and budget["max_cost_usd_per_run"] > budget["max_cost_usd_total"]:
            add("CFG040", "warn", "`max_cost_usd_per_run` is above `max_cost_usd_total`",
                fix="the total ceiling would trip before any single run could reach its own",
                locator="budget")

    concurrency = config.data.get("concurrency")
    if concurrency is not None:
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            add("CFG041", "error", f"`concurrency` must be an integer >= 1, got {concurrency!r}",
                locator="concurrency")
        elif concurrency > 1:
            subscription = credential_kind in ("oauth_token", "login") \
                or str(config.data.get("credential", "")) in ("oauth_token", "login")
            if subscription or credential_kind is None:
                add("CFG041", "warn",
                    f"`concurrency` is {concurrency}"
                    + (" on a subscription credential" if subscription else
                       " and the credential is a subscription unless an API key is set"),
                    fix="parallel runs draw on one person's usage window, so they race each "
                        "other into a rate limit that reads as a flaky agent. A RateLimitEvent "
                        "fired on every measured run at 83% of the 7-day window. Keep "
                        "concurrency at 1 unless the credential is an API key.",
                    source=_SRC_RATE, locator="concurrency")

    isolation = config.data.get("isolation")
    if isolation is None:
        add("CFG042", "warn", "no `isolation` block",
            fix='add {"setting_sources": [], "strict_mcp_config": true}. Without it every run '
                "loads the host's user/project/local settings and CLAUDE.md plus any ambient "
                "MCP servers: the same prompt was measured at $0.087 with them and ~$0.005 "
                "without — 17x — and the results stop being portable between machines.",
            source=_SRC_ISOLATION, locator="isolation")
    elif not isinstance(isolation, dict):
        add("CFG042", "error", f"`isolation` must be an object, got {type(isolation).__name__}",
            locator="isolation")
    else:
        sources = isolation.get("setting_sources")
        if sources is None:
            add("CFG042", "warn", "`isolation.setting_sources` is not set",
                fix="set it to [] so the host's settings and CLAUDE.md do not load "
                    "(measured 17x cost difference)", source=_SRC_ISOLATION,
                locator="isolation.setting_sources")
        elif not isinstance(sources, list):
            add("CFG042", "error", "`isolation.setting_sources` must be a list",
                locator="isolation.setting_sources")
        elif sources:
            add("CFG042", "warn",
                f"`isolation.setting_sources` loads {', '.join(str(s) for s in sources)}",
                fix="ambient settings and CLAUDE.md become part of every prompt: cost rises "
                    "(17x measured) and the same suite scores differently on another machine. "
                    "Use [] unless the case is specifically about settings loading.",
                source=_SRC_ISOLATION, locator="isolation.setting_sources")
        strict = isolation.get("strict_mcp_config")
        if strict is None:
            add("CFG042", "warn", "`isolation.strict_mcp_config` is not set",
                fix="set it to true; otherwise managed and ambient MCP servers are mounted "
                    "into every run, including into tool-free judge calls",
                source=_SRC_ISOLATION, locator="isolation.strict_mcp_config")
        elif strict is False:
            add("CFG042", "warn", "`isolation.strict_mcp_config` is false",
                fix="ambient MCP servers reach the agent (and the judge). `setting_sources: []` "
                    "alone does not drop them — that was measured.",
                source=_SRC_ISOLATION, locator="isolation.strict_mcp_config")
    return []


def _validate_runner_version(
    config: LoadedConfig, *, add, runner_copy_version: str | None
) -> list[Finding]:
    """CFG050: the config names a runner version; does anything match it?"""
    declared = config.runner_version
    if declared is None:
        add("CFG050", "warn", "no `runner_version`",
            fix=f'add "runner_version": "{RUNNER_VERSION}". It is what makes a stale runner '
                "copy visible instead of producing result files this plugin cannot read.",
            locator="runner_version")
        return []
    expected = runner_copy_version or RUNNER_VERSION
    if str(declared) != str(expected):
        which = "the project's runner copy" if runner_copy_version else "this plugin"
        add("CFG050", "warn",
            f"`runner_version` is {declared!r} but {which} is {expected!r}",
            fix="run `install_runner.py --upgrade` (it shows a diff first), then update this "
                "field. A mismatch means the config and the runner disagree about the result "
                "schema.", locator="runner_version")
    elif runner_copy_version and str(declared) != RUNNER_VERSION:
        # Config and copy agree with each other, and both are behind the plugin:
        # the "both stale" case, which comparing against the copy alone hides.
        add("CFG050", "warn",
            f"`runner_version` {declared!r} matches the project's runner copy, but this "
            f"plugin ships {RUNNER_VERSION!r}",
            fix="run `install_runner.py --upgrade` (it shows a diff first), then update this "
                "field so results are written in the schema this plugin reads.",
            locator="runner_version")
    return []


def _validate_misc(config: LoadedConfig, *, add) -> list[Finding]:
    """The small enums and the agent entry point."""
    data = config.data
    agent = data.get("agent")
    if agent is None:
        add("CFG001", "warn", "no `agent` entry point",
            fix='add "agent": "agent:build_options" (module:function), or the runner falls '
                "back to the convention and fails on any other layout", locator="agent")
    elif not isinstance(agent, str) or ":" not in agent:
        add("CFG001", "error", f"`agent` must be `module:function`, got {agent!r}",
            fix='e.g. "agent:build_options"', locator="agent")

    credential = data.get("credential")
    if credential is not None and str(credential) not in CREDENTIAL_MODES:
        add("CFG001", "error", f"unknown `credential` {credential!r}",
            fix="use one of: " + ", ".join(CREDENTIAL_MODES) + " (`auto` resolves "
                "ANTHROPIC_API_KEY -> CLAUDE_CODE_OAUTH_TOKEN -> stored login -> apiKeyHelper)",
            locator="credential")

    on_limit = data.get("on_usage_limit")
    if on_limit is not None and str(on_limit) not in USAGE_LIMIT_MODES:
        add("CFG001", "error", f"unknown `on_usage_limit` {on_limit!r}",
            fix="use one of: " + ", ".join(USAGE_LIMIT_MODES) + ". `not_evaluated` is the "
                "honest default: a run stopped by a usage limit proves nothing about the "
                "agent, so recording it as a FAIL would be a lie.",
            source=_SRC_RATE, locator="on_usage_limit")

    trace = data.get("trace")
    if trace is not None and not isinstance(trace, dict):
        add("CFG001", "error", f"`trace` must be an object, got {type(trace).__name__}",
            locator="trace")
    elif isinstance(trace, dict):
        redact = trace.get("redact_env")
        if redact is not None and not isinstance(redact, list):
            add("CFG001", "error", "`trace.redact_env` must be a list of variable names",
                locator="trace.redact_env")
        if trace.get("include_thinking") is True:
            add("CFG001", "info", "`trace.include_thinking` is true",
                fix="thinking text is written to the trace files verbatim. Fine locally; "
                    "check what you are committing before turning it on in CI.",
                locator="trace.include_thinking")
    return []


def config_summary(config: LoadedConfig, env: dict[str, str] | None = None) -> dict[str, Any]:
    """What a discovery report shows about a config."""
    return {
        "path": config.path,
        "exists": config.exists,
        "schema": config.schema,
        "agent": config.data.get("agent"),
        "model": config.model,
        "resolved_model": config.resolved_model(env),
        "judge_model": config.judge_model if config.judge else None,
        "judge_samples": config.judge.get("samples") if config.judge else None,
        "tiers": {
            name: {
                "graders": tier_graders(config, name),
                "runs": (tier(config, name) or {}).get("runs"),
                "threshold": (tier(config, name) or {}).get("threshold"),
            }
            for name in sorted(config.tiers)
        },
        "isolation": config.isolation or None,
        "concurrency": config.concurrency,
        "results_dir": config.results_dir,
        "runner_version": config.runner_version,
    }
