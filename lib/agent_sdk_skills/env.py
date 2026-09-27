"""Credentials, `.env`, model policy and interpreter resolution.

The Agent SDK spawns a bundled `claude` binary, and that process decides how to
authenticate (docs: `env-vars`, `authentication`, `agent-sdk/quickstart`):

* ``ANTHROPIC_API_KEY`` — billed to the API. When set it is used instead of a
  subscription, even for a logged-in user (always, in non-interactive mode).
* ``CLAUDE_CODE_OAUTH_TOKEN`` — a long-lived subscription token from
  ``claude setup-token``, "the alternative to /login for SDK and automated
  environments"; takes precedence over keychain credentials.
* a stored claude.ai login (``claude auth status`` reports it) — used when
  neither variable is set. Runs then draw on the plan's usage limits, and the
  SDK's ``total_cost_usd`` is an estimate, not a bill.
* provider switches ``CLAUDE_CODE_USE_BEDROCK`` / ``_VERTEX`` / ``_FOUNDRY`` /
  ``_ANTHROPIC_AWS`` route inference elsewhere with that cloud's credentials.

The SDK does **not** load `.env` files itself; the application must. So this
module reads both the process environment and the nearest `.env` above the
project, and says which one it found a value in.

Scripts that need `claude_agent_sdk` never assume it is importable in the
interpreter running this plugin. `resolve_runner` finds one that has it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import (
    ALIAS_MODELS, DEFAULT_MODEL, MODEL_ENV_VAR, RETIRED_MODELS, RETIRING_MODELS,
    SDK_MIN_SUPPORTED,
)

#: Pin used when the runner has to install the SDK on the fly.
SDK_REQUIREMENT = f"claude-agent-sdk>={SDK_MIN_SUPPORTED}"

_ENV_LINE = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$""")

PROVIDER_SWITCHES = {
    "CLAUDE_CODE_USE_BEDROCK": "bedrock",
    "CLAUDE_CODE_USE_VERTEX": "vertex",
    "CLAUDE_CODE_USE_FOUNDRY": "foundry",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS": "anthropic-aws",
}

CREDENTIAL_KEYS = (
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", MODEL_ENV_VAR, "AGENT_ENTRY",
    "CLAUDE_CONFIG_DIR", *PROVIDER_SWITCHES,
)

SECRET_KEYS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")


def read_dotenv(path: Path | str) -> dict[str, str]:
    """Parse a `.env` file. Deliberately small: no interpolation, no plugins."""
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value and value[0] in "\"'" and value[-1:] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class LoginStatus:
    """What `claude auth status` reports, or why it could not be asked."""

    checked: bool = False
    logged_in: bool = False
    auth_method: str | None = None      # claude.ai | console | ...
    subscription: str | None = None     # max | pro | team | enterprise
    api_provider: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def query_login_status(*, timeout: float = 15.0) -> LoginStatus:
    """Ask the installed `claude` CLI who is logged in. Read-only, no network."""
    status = LoginStatus()
    cli = shutil.which("claude")
    if not cli:
        status.error = "no `claude` CLI on PATH to ask"
        return status
    try:
        proc = subprocess.run(
            [cli, "auth", "status"], capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        status.error = f"`claude auth status` failed: {exc}"
        return status
    status.checked = True
    text = proc.stdout.strip()
    try:
        doc = json.loads(text[text.index("{"):])
    except (ValueError, json.JSONDecodeError):
        status.error = (proc.stderr.strip() or text or "no output")[:200]
        return status
    status.logged_in = bool(doc.get("loggedIn"))
    status.auth_method = doc.get("authMethod")
    status.subscription = doc.get("subscriptionType")
    status.api_provider = doc.get("apiProvider")
    return status


@dataclass
class CredentialInfo:
    """Which credential the SDK subprocess would use, and what it means for cost."""

    kind: str = "none"          # api_key | oauth_token | login | provider | none | unknown
    provider: str | None = None
    source: str | None = None   # env var name, .env path, or "claude auth status"
    plan: str | None = None
    login: LoginStatus | None = None
    model_env: str | None = None
    base_url: str | None = None
    entry_env: str | None = None
    #: `.env` files that would be loaded (nearest first) and the examples beside them.
    env_files: list[str] = field(default_factory=list)
    example_files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)

    @property
    def cost_basis(self) -> str:
        """How a run is paid for: what `total_cost_usd` means."""
        if self.kind == "api_key":
            return "api_key"
        if self.kind in ("oauth_token", "login"):
            return "subscription"
        if self.kind == "provider":
            return "provider"
        return "unknown"

    @property
    def ready(self) -> bool:
        return self.kind in ("api_key", "oauth_token", "login", "provider")

    def describe(self) -> str:
        if self.kind == "api_key":
            return f"API key ({self.source}); runs are billed to the API"
        if self.kind == "oauth_token":
            return f"subscription OAuth token ({self.source}); runs draw on plan usage limits"
        if self.kind == "login":
            plan = f" ({self.plan} plan)" if self.plan else ""
            return f"stored claude.ai login{plan}, a subscription; runs draw on plan usage limits, costs are estimates"
        if self.kind == "provider":
            return f"{self.provider} via {self.source}; billed by that provider"
        if self.kind == "unknown":
            return "could not be determined: " + "; ".join(self.notes)
        return "none found: " + ", ".join(self.missing)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("values", None)
        data["login"] = self.login.to_dict() if self.login else None
        data["cost_basis"] = self.cost_basis
        data["ready"] = self.ready
        data["description"] = self.describe()
        return data


def detect_credential(
    project_dir: Path | str | None,
    *,
    include_os_environ: bool = True,
    ask_cli: bool = True,
) -> CredentialInfo:
    """Work out how the SDK subprocess would authenticate for this project.

    Precedence follows the CLI docs: an API key beats a subscription token,
    which beats a stored login. A provider switch changes where inference goes
    and what pays for it.
    """
    info = CredentialInfo()
    merged: dict[str, str] = {}
    sources: dict[str, str] = {}

    if project_dir:
        directory = Path(project_dir).resolve()
        for folder in (directory, *directory.parents):
            example = folder / ".env.example"
            if example.is_file():
                info.example_files.append(str(example))
            candidate = folder / ".env"
            if candidate.is_file():
                info.env_files.append(str(candidate))
                # Nearest .env wins for a value not already seen; most apps
                # load exactly one, from their own directory.
                for key, value in read_dotenv(candidate).items():
                    if key in CREDENTIAL_KEYS and key not in merged and value:
                        merged[key] = value
                        sources[key] = str(candidate)
            if len(info.env_files) >= 2:
                break

    if include_os_environ:
        # The process environment wins over a .env the app may or may not load.
        for key in CREDENTIAL_KEYS:
            if os.environ.get(key):
                merged[key] = os.environ[key]
                sources[key] = f"${key}"

    info.values = {k: ("<set>" if k in SECRET_KEYS else v) for k, v in merged.items()}
    info.model_env = merged.get(MODEL_ENV_VAR) or merged.get("ANTHROPIC_MODEL") or None
    info.base_url = merged.get("ANTHROPIC_BASE_URL") or None
    info.entry_env = merged.get("AGENT_ENTRY") or None

    switches = [name for name, _ in PROVIDER_SWITCHES.items() if _truthy(merged.get(name))]
    if len(switches) > 1:
        info.notes.append("more than one provider switch is set: " + ", ".join(switches))
    if switches:
        info.kind = "provider"
        info.provider = PROVIDER_SWITCHES[switches[0]]
        info.source = sources.get(switches[0], switches[0])
        return info

    if merged.get("ANTHROPIC_API_KEY"):
        info.kind = "api_key"
        info.source = sources["ANTHROPIC_API_KEY"]
        if merged.get("CLAUDE_CODE_OAUTH_TOKEN"):
            info.notes.append("CLAUDE_CODE_OAUTH_TOKEN is also set but the API key wins")
        return info

    if merged.get("CLAUDE_CODE_OAUTH_TOKEN"):
        info.kind = "oauth_token"
        info.source = sources["CLAUDE_CODE_OAUTH_TOKEN"]
        return info

    if ask_cli:
        login = query_login_status()
        info.login = login
        if login.logged_in:
            info.kind = "login"
            info.source = "claude auth status"
            info.plan = login.subscription
            return info
        if not login.checked:
            info.kind = "unknown"
            info.notes.append(login.error or "login status unavailable")
            info.missing.append("ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN, or `claude login`")
            return info

    info.kind = "none"
    info.missing.append("ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`), or `claude login`")
    return info


#: One sentence every script uses when it has to say what is missing.
CREDENTIAL_REQUIREMENT = (
    "needs a stored `claude login`, a CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`, "
    "or an ANTHROPIC_API_KEY"
)


def classify_model_id(model: str | None) -> str:
    """Grade a model id against this plugin's model policy.

    ``alias`` resolved by the CLI (``sonnet``, ``opus``), ``env`` resolved at
    run time, ``retired`` no longer served, ``retiring`` past or within 60 days
    of its retirement date, ``pinned`` a current dateless or dated id,
    ``unknown`` anything else (a typo, or a model newer than this plugin).
    """
    if model is None or model == "":
        return "unknown"
    text = model.strip()
    if text in ALIAS_MODELS:
        return "alias"
    if text.startswith("${") or text.startswith("$") or "environ" in text or "getenv" in text:
        return "env"
    if text in RETIRED_MODELS or text.startswith("claude-3") or text.startswith("claude-2"):
        return "retired"
    if text in RETIRING_MODELS:
        return "retiring"
    if text.startswith(("claude-", "anthropic.claude-", "us.anthropic.claude-", "eu.anthropic.claude-")):
        return "pinned"
    return "unknown"


@dataclass
class RunnerSpec:
    """How to invoke a Python that can import `claude_agent_sdk`."""

    kind: str                      # explicit | venv | system | uv | missing
    argv: list[str] = field(default_factory=list)
    source: str | None = None
    sdk_version: str | None = None
    note: str | None = None
    #: True when we actually imported the SDK with this interpreter.
    verified: bool = False

    @property
    def available(self) -> bool:
        return self.kind != "missing"

    def python_argv(self) -> list[str]:
        return list(self.argv)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["available"] = self.available
        return data


def _has_sdk(argv: list[str], *, timeout: float = 90.0) -> str | None:
    """Return the SDK version importable by `argv`, else None."""
    code = "import claude_agent_sdk as s; print(getattr(s, '__version__', 'unknown'))"
    try:
        proc = subprocess.run([*argv, "-c", code], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None


def candidate_pythons(
    project_dir: Path | str | None, extra_root: Path | str | None = None,
) -> list[tuple[str, list[str], str]]:
    """Interpreters worth probing, most specific first."""
    candidates: list[tuple[str, list[str], str]] = []

    explicit = os.environ.get("AGENT_SDK_PYTHON")
    if explicit:
        candidates.append(("explicit", [explicit], "$AGENT_SDK_PYTHON"))

    roots: list[Path] = []
    for base in (project_dir, extra_root):
        if not base:
            continue
        path = Path(base).resolve()
        roots.extend([path, *path.parents][:4])
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        for venv in (".venv", "venv", ".env"):
            python = root / venv / "bin" / "python"
            if python.is_file():
                candidates.append(("venv", [str(python)], str(python)))
            win = root / venv / "Scripts" / "python.exe"
            if win.is_file():
                candidates.append(("venv", [str(win)], str(win)))

    for name in (os.environ.get("PYTHON"), "python3", "python3.12", "python3.11", "python3.10"):
        if name and shutil.which(name):
            candidates.append(("system", [name], f"PATH ({shutil.which(name)})"))
    return candidates


def resolve_runner(
    project_dir: Path | str | None = None,
    extra_root: Path | str | None = None,
    *,
    probe: bool = True,
    allow_uv: bool = True,
) -> RunnerSpec:
    """Find a Python that can import the SDK, or say how to get one.

    Order: ``$AGENT_SDK_PYTHON`` → a virtualenv at or above the project → a
    ``python3`` on PATH that imports it → ``uv run --with`` → missing.
    """
    for kind, argv, source in candidate_pythons(project_dir, extra_root):
        if not probe:
            return RunnerSpec(
                kind=kind, argv=argv, source=source, verified=False,
                note="not verified: run without --no-probe to confirm claude_agent_sdk imports",
            )
        version = _has_sdk(argv)
        if version:
            return RunnerSpec(kind=kind, argv=argv, source=source, sdk_version=version, verified=True)

    uv = shutil.which("uv")
    if allow_uv and uv:
        argv = [uv, "run", "--with", SDK_REQUIREMENT, "python"]
        return RunnerSpec(
            kind="uv", argv=argv, source=f"{uv} run --with {SDK_REQUIREMENT}", verified=True,
            note="first run downloads the SDK into a temporary environment",
        )

    return RunnerSpec(
        kind="missing", argv=[], source=None,
        note=(
            "No interpreter with claude_agent_sdk. Create a venv: "
            f'`python3 -m venv .venv && .venv/bin/pip install "{SDK_REQUIREMENT}"`, '
            "then re-run with AGENT_SDK_PYTHON=.venv/bin/python (or install uv for "
            f'`uv run --with "{SDK_REQUIREMENT}"`).'
        ),
    )


def sdk_version(runner: RunnerSpec) -> str | None:
    if runner.sdk_version:
        return runner.sdk_version
    if not runner.available:
        return None
    return _has_sdk(runner.argv)


def _version_tuple(version: str) -> tuple[int, ...]:
    """`"0.2.162rc1"` -> `(0, 2, 162)`. Non-numeric tails are dropped."""
    parts: list[int] = []
    for chunk in version.strip().lstrip("v").split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def version_at_least(version: str | None, minimum: str = SDK_MIN_SUPPORTED) -> bool:
    """Numeric per-component comparison: `"0.2.99"` is older than `"0.2.100"`,
    which a string comparison gets wrong. Unknown is not assumed new enough."""
    if not version:
        return False
    return _version_tuple(version) >= _version_tuple(minimum)


def version_is_supported(version: str | None) -> bool:
    return version_at_least(version, SDK_MIN_SUPPORTED)


def default_model(credential: CredentialInfo | None = None) -> str:
    """The model generated configs and scaffolds should name explicitly."""
    if credential and credential.model_env:
        return credential.model_env
    return DEFAULT_MODEL
