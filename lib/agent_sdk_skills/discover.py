"""One pass over a project: what exists, what is missing, what to do next.

Every skill starts here. Guessing a project's entry point, its credential or
which eval cases already exist produces confident wrong advice, so each skill
runs a discovery script first and reports what it found before proposing
anything.

The output is a `GapReport`: `discovered` facts, `findings` (things that are
wrong), `gaps` (things that are absent) and `options` (what the user can choose
to do). The `focus` argument keeps a skill from paying for analysis it will not
show; `probe_runner=False` skips the interpreter check and `ask_cli=False`
skips `claude auth status`.

Deep validation of cases, config and results lives in the eval-review,
eval-criteria and eval-analyze libraries; discovery only counts and locates
them, and imports those modules lazily so it keeps working while they are
being built or when a project has none of those files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from . import DEFAULT_MODEL, MODEL_ENV_VAR, RUNNER_VERSION
from .env import (
    CREDENTIAL_REQUIREMENT, CredentialInfo, RunnerSpec, classify_model_id,
    detect_credential, resolve_runner, version_is_supported,
)
from .layout import LayoutInfo, detect_layout
from .report import Finding, GapReport, Option
from .runner_version import RunnerCopy, findings_for, inspect_runner_copy
from .sdk_subprocess import describe_runner

ALL_FOCUS = ("layout", "env", "claude", "evals", "runner", "results", "ci")

_DOCS = "https://code.claude.com/docs/en"


def _rel(path: str | None, base: Path | str) -> str | None:
    if not path:
        return path
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve())) or "."
    except (ValueError, OSError):
        return Path(path).name


class Discovery:
    """Lazily computed view of one Agent SDK project."""

    def __init__(
        self,
        target: Path | str,
        *,
        focus: Sequence[str] = ALL_FOCUS,
        probe_runner: bool = True,
        ask_cli: bool = True,
        skill: str = "agent-sdk",
    ) -> None:
        self.target = Path(target)
        self.focus = set(focus or ALL_FOCUS)
        self.skill = skill
        self.layout: LayoutInfo = detect_layout(self.target)
        self.project_root = Path(self.layout.project_root or self.target)
        self.credential: CredentialInfo | None = None
        self.runner: RunnerSpec | None = None
        self.runner_copy: RunnerCopy | None = None
        self.config_doc: dict[str, Any] | None = None
        self.config_error: str | None = None
        self.latest_aggregate: dict[str, Any] | None = None

        if "env" in self.focus:
            self.credential = detect_credential(self.project_root, ask_cli=ask_cli)
            self.runner = resolve_runner(self.project_root, probe=probe_runner)
        if "runner" in self.focus:
            self.runner_copy = inspect_runner_copy(self.project_root / "evals" / "runner")
        if "evals" in self.focus and self.layout.evals and self.layout.evals.config:
            self._load_config(self.layout.evals.config)
        if "results" in self.focus and self.layout.evals and self.layout.evals.result_runs:
            self._load_latest_aggregate(self.layout.evals.result_runs[-1])

    # -- lazy loaders -----------------------------------------------------
    def _load_config(self, path: str) -> None:
        import json

        try:
            self.config_doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.config_error = str(exc)

    def _load_latest_aggregate(self, run_dir: str) -> None:
        import json

        aggregate = Path(run_dir) / "aggregate.json"
        if aggregate.is_file():
            try:
                self.latest_aggregate = json.loads(aggregate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.latest_aggregate = None

    # -- derived facts ----------------------------------------------------
    @property
    def sdk_version(self) -> str | None:
        return self.runner.sdk_version if self.runner else None

    @property
    def configured_model(self) -> str | None:
        if self.config_doc and isinstance(self.config_doc.get("model"), str):
            return self.config_doc["model"]
        return None

    def case_count(self) -> int:
        return self.layout.evals.case_count if self.layout.evals else 0

    # -- report -----------------------------------------------------------
    def discovered(self) -> dict[str, Any]:
        root = self.project_root
        data: dict[str, Any] = {}
        lay = self.layout

        if "layout" in self.focus:
            data["layout"] = {
                "project_root": str(root),
                "style": lay.style,
                "entry_point": lay.entry_spec,
                "entry_module": _rel(lay.entry_module, root),
                "agent_modules": [_rel(m.path, root) for m in lay.agent_modules],
                "legacy_sdk_modules": [_rel(p, root) for p in lay.legacy_modules],
                "requirements": lay.requirements,
                "env_files": [_rel(p, root) for p in lay.env_files],
                "env_examples": [_rel(p, root) for p in lay.example_files],
            }

        if "env" in self.focus and self.credential and self.runner:
            data["environment"] = {
                "credential": self.credential.describe(),
                "cost_basis": self.credential.cost_basis,
                "plan": self.credential.plan,
                "provider": self.credential.provider,
                "base_url": self.credential.base_url,
                "model_env": self.credential.model_env,
                "entry_env": self.credential.entry_env,
                "runner": describe_runner(self.runner),
                "sdk_version": self.sdk_version,
                "sdk_supported": version_is_supported(self.sdk_version) if self.sdk_version else None,
            }

        if "claude" in self.focus and lay.claude:
            data["claude_code_files"] = {
                "claude_md": [_rel(p, root) for p in lay.claude.claude_md],
                "settings": [_rel(p, root) for p in lay.claude.settings],
                "hooks_in_settings": lay.claude.hooks_in_settings,
                "agents": [_rel(p, root) for p in lay.claude.agents],
                "skills": [_rel(p, root) for p in lay.claude.skills],
                "mcp_json": _rel(lay.claude.mcp_json, root),
            }

        if "evals" in self.focus:
            if lay.evals:
                data["evals"] = {
                    "dir": _rel(lay.evals.dir, root),
                    "config": _rel(lay.evals.config, root),
                    "configured_model": self.configured_model,
                    "cases": [Path(c).name for c in lay.evals.cases],
                    "case_count": lay.evals.case_count,
                    "mocks": [Path(m).name for m in lay.evals.mocks],
                    "personas": [Path(p).name for p in lay.evals.personas],
                    "faults": [Path(f).name for f in lay.evals.faults],
                }
            else:
                data["evals"] = {"dir": None, "case_count": 0}

        if "runner" in self.focus and self.runner_copy:
            data["runner_copy"] = {
                "present": self.runner_copy.present,
                "version": self.runner_copy.version,
                "plugin_version": RUNNER_VERSION,
                "status": self.runner_copy.status,
                "modified": self.runner_copy.modified,
            }

        if "results" in self.focus:
            runs = lay.evals.result_runs if lay.evals else []
            data["results"] = {
                "runs": len(runs),
                "latest": _rel(runs[-1], root) if runs else None,
                "latest_totals": (self.latest_aggregate or {}).get("totals"),
                "latest_tier": (self.latest_aggregate or {}).get("tier"),
            }

        if "ci" in self.focus:
            data["ci"] = {
                "workflows": [_rel(p, root) for p in lay.workflow_files],
                "pytest_gate": _rel(lay.pytest_gate, root),
            }
        return data

    def findings(self) -> list[Finding]:
        out: list[Finding] = []
        lay = self.layout
        root = str(self.project_root)

        if "env" in self.focus and self.credential and self.runner:
            cred = self.credential
            if not self.runner.available:
                out.append(Finding("ENV001", "error", "environment",
                                   "no interpreter with claude_agent_sdk", path=root,
                                   fix=self.runner.note, source=f"{_DOCS}/agent-sdk/quickstart"))
            elif self.sdk_version and not version_is_supported(self.sdk_version):
                out.append(Finding("ENV002", "warn", "environment",
                                   f"claude-agent-sdk {self.sdk_version} is older than this plugin's minimum",
                                   path=root, fix="upgrade: pip install -U claude-agent-sdk",
                                   source="this plugin's SDK_MIN_SUPPORTED"))
            if cred.kind == "none":
                out.append(Finding("ENV010", "error", "credentials",
                                   "no credential found; the SDK subprocess would fail with 'Not logged in'",
                                   path=root, fix=CREDENTIAL_REQUIREMENT,
                                   source=f"{_DOCS}/env-vars, {_DOCS}/errors#authentication-errors"))
            elif cred.kind == "unknown":
                out.append(Finding("ENV010", "warn", "credentials",
                                   "credential could not be determined: " + "; ".join(cred.notes),
                                   path=root, fix=CREDENTIAL_REQUIREMENT, source=f"{_DOCS}/env-vars"))
            if any("more than one provider" in n for n in cred.notes):
                out.append(Finding("ENV011", "error", "credentials",
                                   "more than one provider switch is set; the CLI honours one and the rest mislead",
                                   path=root, fix="keep exactly one of CLAUDE_CODE_USE_BEDROCK / _VERTEX / _FOUNDRY",
                                   source=f"{_DOCS}/agent-sdk/quickstart"))
            if cred.kind == "api_key":
                out.append(Finding("ENV012", "info", "credentials",
                                   f"ANTHROPIC_API_KEY is set ({cred.source}); runs and judges are billed to the API "
                                   "even if you are also logged in", path=root,
                                   fix="unset it to use your subscription instead", source=f"{_DOCS}/env-vars"))
            if cred.kind in ("login", "oauth_token"):
                out.append(Finding("ENV013", "info", "credentials",
                                   "runs use a Claude subscription: `total_cost_usd` is an estimate and the real "
                                   "ceiling is the plan's session and weekly usage limits", path=root,
                                   source=f"{_DOCS}/agent-sdk/cost-tracking"))
            if lay.env_files and not _gitignore_covers(self.project_root, ".env"):
                out.append(Finding("ENV020", "warn", "credentials",
                                   ".env exists but .gitignore does not exclude it", path=root,
                                   fix="add `.env` to .gitignore; keep secrets out of the repository",
                                   source=f"{_DOCS}/agent-sdk/secure-deployment"))
            if not cred.model_env and not self.configured_model:
                out.append(Finding("ENV030", "info", "model",
                                   f"{MODEL_ENV_VAR} is not set; the SDK falls back to Claude Code's default model, "
                                   f"and this plugin's scaffolds use {DEFAULT_MODEL}", path=root,
                                   fix=f"set {MODEL_ENV_VAR} in .env so runs and evals pin the same model",
                                   source=f"{_DOCS}/agent-sdk/configuration#choose-a-model"))
            grade = classify_model_id(cred.model_env)
            if grade == "retired":
                out.append(Finding("AGT012", "error", "model", f"{MODEL_ENV_VAR}={cred.model_env} is retired",
                                   path=root, fix=f"use {DEFAULT_MODEL}",
                                   source="platform.claude.com/docs/en/about-claude/model-deprecations"))
            elif grade == "retiring":
                out.append(Finding("AGT011", "warn", "model", f"{MODEL_ENV_VAR}={cred.model_env} is retiring",
                                   path=root, fix=f"plan the move to {DEFAULT_MODEL}",
                                   source="platform.claude.com/docs/en/about-claude/model-deprecations"))

        if "layout" in self.focus:
            for legacy in lay.legacy_modules:
                out.append(Finding("AGT030", "error", "agent",
                                   "imports the retired `claude_code_sdk` package or `ClaudeCodeOptions`",
                                   path=legacy, fix="rename to claude_agent_sdk / ClaudeAgentOptions and review "
                                   "the migration guide (system prompt and settings defaults changed)",
                                   source=f"{_DOCS}/agent-sdk/migration-guide"))
            if lay.style == "inline":
                out.append(Finding("AGT003", "warn", "agent",
                                   "options are built inline; the eval runner cannot obtain them to apply overrides",
                                   path=lay.entry_module, fix="expose `build_options() -> ClaudeAgentOptions` "
                                   "(or name a builder as module:function in evals/eval_config.json)",
                                   source="this plugin's entry-point convention"))
            if lay.style == "collection":
                out.append(Finding("AGT002", "warn", "agent",
                                   f"{len(lay.agent_modules)} agent modules and no build_options() entry",
                                   path=root, fix="name the entry point in evals/eval_config.json (`agent`)",
                                   source="this plugin's entry-point convention"))

        if "evals" in self.focus and lay.evals:
            for case in lay.evals.case_dirs_without_graders:
                out.append(Finding("EVC004", "warn", "evals", "case has a prompt.md but no graders/ directory",
                                   path=case, fix="add at least one grader; a case without graders never fails",
                                   source="this plugin's case format"))
            for stray in lay.evals.stray_prompt_files:
                out.append(Finding("EVC005", "warn", "evals", "prompt.md at the evals root is not a case",
                                   path=stray, fix="move it into evals/<case-name>/prompt.md",
                                   source="this plugin's case format"))
            if self.config_error:
                out.append(Finding("CFG002", "error", "config", f"eval_config.json is not valid JSON: {self.config_error}",
                                   path=lay.evals.config, fix="fix the JSON, or regenerate with /agent-sdk:eval-criteria",
                                   source="this plugin's config format"))

        if "runner" in self.focus and self.runner_copy and lay.evals:
            out.extend(findings_for(self.runner_copy, path=lay.evals.dir))
        return out

    def gaps(self) -> list[tuple[str, str, str, str]]:
        lay = self.layout
        out: list[tuple[str, str, str, str]] = []
        if not lay.is_agent and lay.style != "collection":
            out.append(("GAP-AGENT", "no Agent SDK agent",
                        "nothing here builds ClaudeAgentOptions or calls query()",
                        "scaffold one with /agent-sdk-dev:new-sdk-app (if installed) or write agent.py with build_options()"))
            return out
        if not lay.evals or lay.evals.case_count == 0:
            out.append(("GAP-EVALS", "no eval cases",
                        "the agent's behaviour exists only as a system prompt and whatever was tried by hand",
                        "run /agent-sdk:agent-create to scaffold evals/, then /agent-sdk:eval-create for the first cases"))
        if lay.evals and not lay.evals.config:
            out.append(("GAP-CONFIG", "no evals/eval_config.json",
                        "the runner falls back to defaults: no tiers, no budgets, no judge settings",
                        "run /agent-sdk:eval-criteria to write one"))
        if lay.evals and self.runner_copy and not self.runner_copy.present:
            out.append(("GAP-RUNNER", "no runner copy in evals/runner/",
                        "nothing can execute the cases",
                        "run /agent-sdk:agent-create and choose 'install the runner'"))
        if lay.is_agent and not lay.example_files:
            out.append(("GAP-ENV-EXAMPLE", "no .env.example",
                        "the next person cannot tell which variables the agent reads",
                        "/agent-sdk:agent-create writes one (CLAUDE_MODEL, optional ANTHROPIC_API_KEY)"))
        if lay.evals and lay.evals.case_count and not lay.pytest_gate and not lay.workflow_files:
            out.append(("GAP-CI", "no pytest gate and no workflow",
                        "cases exist but nothing runs them where a failure is noticed",
                        "run /agent-sdk:eval-ci"))
        if lay.evals and lay.evals.case_count and not lay.evals.result_runs:
            out.append(("GAP-RUN", "cases have never been run",
                        "an unrun case proves nothing",
                        "run /agent-sdk:eval-run --tier pr (run tier: spends model turns)"))
        return out

    def options(self) -> list[Option]:
        lay = self.layout
        opts: list[Option] = []
        if not lay.is_agent and lay.style != "collection":
            opts.append(Option("1", "Scaffold an eval-ready agent", "hand off to /agent-sdk:agent-create",
                               recommended=True, cost="free"))
            return opts
        if lay.legacy_modules or lay.style in ("inline", "collection"):
            opts.append(Option(str(len(opts) + 1), "Review the agent", "/agent-sdk:agent-review reports drift and "
                               "eval-readiness; nothing is edited", recommended=True, cost="free"))
        if not lay.evals or lay.evals.case_count == 0:
            opts.append(Option(str(len(opts) + 1), "Add eval scaffolding and first cases",
                               "/agent-sdk:agent-create then /agent-sdk:eval-create",
                               recommended=not opts, cost="free",
                               writes=["evals/", "evals/eval_config.json", "evals/runner/"]))
        elif not lay.evals.result_runs:
            opts.append(Option(str(len(opts) + 1), "Validate then run the suite",
                               "/agent-sdk:eval-review (free) then /agent-sdk:eval-run --tier pr",
                               recommended=not opts, cost="run"))
        else:
            opts.append(Option(str(len(opts) + 1), "Analyze the latest results",
                               "/agent-sdk:eval-analyze explains failures by quadrant and reliability",
                               recommended=not opts, cost="free"))
            opts.append(Option(str(len(opts) + 1), "Measure coverage and close gaps",
                               "/agent-sdk:eval-review then /agent-sdk:eval-create", cost="free"))
        if lay.is_agent and not opts:
            opts.append(Option("1", "Review the agent", "/agent-sdk:agent-review", recommended=True, cost="free"))
        return opts

    def report(self) -> GapReport:
        report = GapReport(subject=str(self.target), skill=self.skill, discovered=self.discovered())
        report.extend(self.findings())
        for gap in self.gaps():
            report.add_gap(*gap)
        for option in self.options():
            report.add_option(option)
        return report


def _gitignore_covers(project_root: Path, name: str) -> bool:
    """A cheap check: does any .gitignore at or above the project mention `name`?"""
    for folder in (project_root, *project_root.parents):
        gitignore = folder / ".gitignore"
        if gitignore.is_file():
            try:
                lines = [l.strip() for l in gitignore.read_text(encoding="utf-8").splitlines()]
            except OSError:
                continue
            if any(l in (name, f"/{name}", f"{name}*", f"{name}.*", f"**/{name}") for l in lines):
                return True
        if (folder / ".git").exists():
            break
    return False


def discover(
    target: Path | str,
    *,
    focus: Sequence[str] = ALL_FOCUS,
    probe_runner: bool = True,
    ask_cli: bool = True,
    skill: str = "agent-sdk",
) -> GapReport:
    return Discovery(target, focus=focus, probe_runner=probe_runner, ask_cli=ask_cli, skill=skill).report()
