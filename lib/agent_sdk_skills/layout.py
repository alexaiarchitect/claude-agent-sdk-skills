"""Detect how a Claude Agent SDK project is laid out, without importing it.

The SDK prescribes no layout: an "agent" is any Python module that builds a
``ClaudeAgentOptions`` and calls ``query()`` or drives a ``ClaudeSDKClient``.
So discovery reads source with ``ast`` and looks for those three things. On
top of that, this plugin's eval scaffolding assumes one convention, which the
runner loads by default:

* ``agent.py`` exposing ``build_options() -> ClaudeAgentOptions`` and,
  optionally, ``run(prompt, options)``; any other entry point is named as
  ``module:function`` in ``evals/eval_config.json`` or ``AGENT_ENTRY``.
* ``evals/<case>/prompt.md`` + ``evals/<case>/graders/*.md`` (one case per
  directory), ``evals/eval_config.json``, ``evals/mocks/``, ``evals/personas/``,
  ``evals/faults/``, ``evals/runner/agent_sdk_evals/`` (the runner copy) and
  ``evals/results/<timestamp>/`` (gitignored output).

Claude Code's own files matter too, because the SDK loads them when
``setting_sources`` says so: ``.claude/settings*.json``, ``.claude/agents/``,
``.claude/skills/``, ``CLAUDE.md``, ``.mcp.json``.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".tox",
    "site-packages", ".idea", ".claude", ".dev",
}

SDK_MODULE = "claude_agent_sdk"
LEGACY_SDK_MODULE = "claude_code_sdk"
OPTIONS_CLASS = "ClaudeAgentOptions"
LEGACY_OPTIONS_CLASS = "ClaudeCodeOptions"
CLIENT_CLASS = "ClaudeSDKClient"
ENTRY_FUNCTION = "build_options"
RUN_FUNCTION = "run"
EVALS_DIR = "evals"
CONFIG_NAME = "eval_config.json"
CASE_PROMPT = "prompt.md"
CASE_GRADERS = "graders"
RUNNER_DIR = "runner"
RUNNER_PACKAGE = "agent_sdk_evals"


@dataclass
class SdkUsage:
    """What one Python file does with the SDK, read statically."""

    path: str
    imports_sdk: bool = False
    imports_legacy_sdk: bool = False
    builds_options: bool = False
    builds_legacy_options: bool = False
    calls_query: bool = False
    uses_client: bool = False
    has_build_options: bool = False
    has_run: bool = False
    #: `ClaudeAgentOptions(...)` constructed only inside `main()`/`__main__`,
    #: so nothing outside the module can obtain the options to override them.
    options_only_in_main: bool = False
    #: Names of top-level functions that construct options (entry candidates).
    option_builders: list[str] = field(default_factory=list)

    @property
    def is_agent(self) -> bool:
        return (self.imports_sdk or self.imports_legacy_sdk) and (
            self.builds_options or self.builds_legacy_options or self.calls_query or self.uses_client
        )

    @property
    def entry_style(self) -> str:
        if self.has_build_options:
            return "convention"
        if self.option_builders:
            return "custom"
        if self.is_agent:
            return "inline"
        return "none"

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if v not in (None, False, [])}
        data["path"] = self.path
        data["entry_style"] = self.entry_style
        return data


def scan_sdk_usage(path: Path | str) -> SdkUsage:
    """Read a Python file and report how it uses the SDK. Never executes it."""
    file = Path(path)
    info = SdkUsage(path=str(file))
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return info

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == SDK_MODULE:
                    info.imports_sdk = True
                elif alias.name.split(".")[0] == LEGACY_SDK_MODULE:
                    info.imports_legacy_sdk = True
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root == SDK_MODULE:
                info.imports_sdk = True
            elif root == LEGACY_SDK_MODULE:
                info.imports_legacy_sdk = True

    def call_name(node: ast.AST) -> str | None:
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    builders_inside: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == ENTRY_FUNCTION:
                info.has_build_options = True
            if node.name == RUN_FUNCTION:
                info.has_run = True
            constructs = any(
                call_name(inner) in (OPTIONS_CLASS, LEGACY_OPTIONS_CLASS)
                for inner in ast.walk(node) if isinstance(inner, ast.Call)
            )
            if constructs:
                builders_inside[node.name] = True

    for node in ast.walk(tree):
        name = call_name(node)
        if name == OPTIONS_CLASS:
            info.builds_options = True
        elif name == LEGACY_OPTIONS_CLASS:
            info.builds_legacy_options = True
        elif name == "query":
            info.calls_query = True
        elif name == CLIENT_CLASS:
            info.uses_client = True

    info.option_builders = sorted(
        name for name in builders_inside if name not in ("main", "__main__", "_main")
    )
    if (info.builds_options or info.builds_legacy_options) and not info.option_builders:
        if any(name in builders_inside for name in ("main", "_main")):
            info.options_only_in_main = True
    return info


def _walk_files(root: Path, *, max_depth: int = 6):
    root = root.resolve()
    stack = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.is_dir():
                if depth < max_depth and entry.name not in SKIP_DIRS:
                    stack.append((entry, depth + 1))
            else:
                yield entry


def find_agent_modules(root: Path | str, *, max_depth: int = 4) -> list[SdkUsage]:
    """Every Python file under `root` that uses the SDK (cheap textual filter first)."""
    found: list[SdkUsage] = []
    for file in _walk_files(Path(root), max_depth=max_depth):
        if file.suffix != ".py":
            continue
        # The runner copy imports the SDK too but is not the agent.
        if RUNNER_PACKAGE in file.parts:
            continue
        try:
            with file.open(encoding="utf-8", errors="ignore") as handle:
                text = handle.read(65536)
        except OSError:
            continue
        if SDK_MODULE not in text and LEGACY_SDK_MODULE not in text:
            continue
        usage = scan_sdk_usage(file)
        if usage.is_agent or usage.has_build_options:
            found.append(usage)
    return sorted(found, key=lambda u: u.path)


@dataclass
class EvalsInfo:
    """What the project's `evals/` directory holds."""

    dir: str
    config: str | None = None
    cases: list[str] = field(default_factory=list)
    case_dirs_without_graders: list[str] = field(default_factory=list)
    stray_prompt_files: list[str] = field(default_factory=list)
    mocks: list[str] = field(default_factory=list)
    personas: list[str] = field(default_factory=list)
    faults: list[str] = field(default_factory=list)
    runner_dir: str | None = None
    results_dir: str | None = None
    result_runs: list[str] = field(default_factory=list)

    @property
    def case_count(self) -> int:
        return len(self.cases)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["case_count"] = self.case_count
        return data


def scan_evals_dir(evals_dir: Path | str) -> EvalsInfo:
    root = Path(evals_dir)
    info = EvalsInfo(dir=str(root))
    config = root / CONFIG_NAME
    if config.is_file():
        info.config = str(config)
    runner = root / RUNNER_DIR / RUNNER_PACKAGE
    if runner.is_dir():
        info.runner_dir = str(root / RUNNER_DIR)
    results = root / "results"
    if results.is_dir():
        info.results_dir = str(results)
        info.result_runs = sorted(str(p) for p in results.iterdir() if p.is_dir())
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in SKIP_DIRS:
            continue
        if child.name == "mocks":
            info.mocks = sorted(str(p) for p in child.iterdir() if p.is_dir())
        elif child.name == "personas":
            info.personas = sorted(str(p) for p in child.glob("*.json"))
        elif child.name == "faults":
            info.faults = sorted(str(p) for p in child.glob("*.json"))
        elif child.name in (RUNNER_DIR, "results", "graders_local", "fixtures"):
            continue
        elif (child / CASE_PROMPT).is_file():
            info.cases.append(str(child))
            if not (child / CASE_GRADERS).is_dir():
                info.case_dirs_without_graders.append(str(child))
    for stray in root.glob("*.md"):
        if stray.name == CASE_PROMPT:
            info.stray_prompt_files.append(str(stray))
    return info


@dataclass
class ClaudeFiles:
    """Claude Code configuration the SDK may load through `setting_sources`."""

    claude_md: list[str] = field(default_factory=list)
    settings: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    mcp_json: str | None = None
    hooks_in_settings: bool = False

    @property
    def any(self) -> bool:
        return bool(self.claude_md or self.settings or self.agents or self.skills or self.mcp_json)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["any"] = self.any
        return data


def scan_claude_files(project_root: Path | str) -> ClaudeFiles:
    root = Path(project_root)
    info = ClaudeFiles()
    for name in ("CLAUDE.md", "CLAUDE.local.md"):
        if (root / name).is_file():
            info.claude_md.append(str(root / name))
    claude_dir = root / ".claude"
    if claude_dir.is_dir():
        if (claude_dir / "CLAUDE.md").is_file():
            info.claude_md.append(str(claude_dir / "CLAUDE.md"))
        for name in ("settings.json", "settings.local.json"):
            path = claude_dir / name
            if path.is_file():
                info.settings.append(str(path))
                try:
                    if '"hooks"' in path.read_text(encoding="utf-8"):
                        info.hooks_in_settings = True
                except OSError:
                    pass
        agents = claude_dir / "agents"
        if agents.is_dir():
            info.agents = sorted(str(p) for p in agents.glob("*.md"))
        skills = claude_dir / "skills"
        if skills.is_dir():
            info.skills = sorted(str(p) for p in skills.iterdir() if (p / "SKILL.md").is_file())
    if (root / ".mcp.json").is_file():
        info.mcp_json = str(root / ".mcp.json")
    return info


@dataclass
class LayoutInfo:
    """Everything a skill needs to know about where things are."""

    root: str
    project_root: str | None = None
    style: str = "none"                # convention | custom | inline | collection | none
    entry_module: str | None = None
    entry_spec: str | None = None      # "agent:build_options"
    agent_modules: list[SdkUsage] = field(default_factory=list)
    legacy_modules: list[str] = field(default_factory=list)
    evals: EvalsInfo | None = None
    claude: ClaudeFiles | None = None
    env_files: list[str] = field(default_factory=list)
    example_files: list[str] = field(default_factory=list)
    workflow_files: list[str] = field(default_factory=list)
    pytest_gate: str | None = None
    requirements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_agent(self) -> bool:
        return self.style in ("convention", "custom", "inline")

    @property
    def has_evals(self) -> bool:
        return self.evals is not None and self.evals.case_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "project_root": self.project_root,
            "style": self.style,
            "entry_module": self.entry_module,
            "entry_spec": self.entry_spec,
            "agent_modules": [m.to_dict() for m in self.agent_modules],
            "legacy_modules": self.legacy_modules,
            "evals": self.evals.to_dict() if self.evals else None,
            "claude": self.claude.to_dict() if self.claude else None,
            "env_files": self.env_files,
            "example_files": self.example_files,
            "workflow_files": self.workflow_files,
            "pytest_gate": self.pytest_gate,
            "requirements": self.requirements,
            "notes": self.notes,
            "is_agent": self.is_agent,
            "has_evals": self.has_evals,
        }


def _module_spec(project_root: Path, module_file: Path, function: str) -> str:
    try:
        rel = module_file.resolve().relative_to(project_root.resolve()).with_suffix("")
    except ValueError:
        rel = Path(module_file.stem)
    return ".".join(rel.parts) + f":{function}"


def detect_layout(path: Path | str) -> LayoutInfo:
    """Work out what `path` is and where its agent and eval files live.

    `path` may be the project root, the agent module itself, or the `evals/`
    directory; the project root is what the runner and every script are
    pointed at afterwards.
    """
    target = Path(path).expanduser()
    info = LayoutInfo(root=str(target.resolve()) if target.exists() else str(target))
    if not target.exists():
        info.notes.append("target does not exist")
        return info
    resolved = target.resolve()

    if resolved.is_file():
        if resolved.suffix != ".py":
            info.notes.append("target is a file, not a Python module or a directory")
            return info
        project_root = resolved.parent
        usage = scan_sdk_usage(resolved)
        info.agent_modules = [usage] if (usage.is_agent or usage.has_build_options) else []
    else:
        project_root = resolved
        if resolved.name == EVALS_DIR and (resolved / CONFIG_NAME).is_file():
            project_root = resolved.parent
        info.agent_modules = find_agent_modules(project_root)

    info.project_root = str(project_root)
    info.legacy_modules = [m.path for m in info.agent_modules if m.imports_legacy_sdk or m.builds_legacy_options]

    agents = [m for m in info.agent_modules if m.is_agent or m.has_build_options]
    convention = [m for m in agents if m.has_build_options]
    if convention:
        preferred = next((m for m in convention if Path(m.path).name == "agent.py"), convention[0])
        info.style = "convention"
        info.entry_module = preferred.path
        info.entry_spec = _module_spec(project_root, Path(preferred.path), ENTRY_FUNCTION)
        if len(convention) > 1:
            info.notes.append(f"{len(convention)} modules define build_options(); using {Path(preferred.path).name}")
    elif len(agents) == 1:
        only = agents[0]
        info.entry_module = only.path
        if only.option_builders:
            info.style = "custom"
            info.entry_spec = _module_spec(project_root, Path(only.path), only.option_builders[0])
        else:
            info.style = "inline"
            info.notes.append(
                "options are built inline (inside main() or at module level): the runner cannot "
                "obtain them; expose a build_options() or name a builder in eval_config.json"
            )
    elif len(agents) > 1:
        info.style = "collection"
        info.notes.append(f"{len(agents)} agent modules found; name the entry point in eval_config.json")
    else:
        info.style = "none"
        info.notes.append("no Claude Agent SDK usage found (no module imports claude_agent_sdk)")

    evals_dir = project_root / EVALS_DIR
    if evals_dir.is_dir():
        info.evals = scan_evals_dir(evals_dir)
    info.claude = scan_claude_files(project_root)

    for name in (".env", ".env.local"):
        if (project_root / name).is_file():
            info.env_files.append(str(project_root / name))
    for name in (".env.example", ".env.sample", ".env.template"):
        if (project_root / name).is_file():
            info.example_files.append(str(project_root / name))
    workflows = project_root / ".github" / "workflows"
    if workflows.is_dir():
        info.workflow_files = sorted(str(p) for p in workflows.glob("*.y*ml"))
    gate = project_root / "tests" / "test_evals.py"
    if gate.is_file():
        info.pytest_gate = str(gate)
    for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "uv.lock", "setup.py"):
        if (project_root / name).is_file():
            info.requirements.append(name)
    return info
