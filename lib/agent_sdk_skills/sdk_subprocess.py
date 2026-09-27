"""Run the project's eval runner (and other SDK-needing code) through a resolved
interpreter, and read back what it printed.

The plugin's own scripts never import `claude_agent_sdk`. Anything that must —
running an agent, judging a transcript, importing `agent.py` to see what it
builds — happens in the project's interpreter, inside the runner package the
plugin copied into ``<project>/evals/runner/``. This module builds that
invocation, runs it, and parses the single JSON document the runner prints as
its last stdout line. The runner's own exit code is the honest one: 0 passed,
1 below threshold, 2 usage or import error, 3 inconclusive.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .env import RunnerSpec, resolve_runner

DEFAULT_TIMEOUT = 1800.0
RUNNER_MODULE = "agent_sdk_evals"


@dataclass
class CommandOutcome:
    """One subprocess invocation."""

    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    cwd: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def combined(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()

    def tail(self, lines: int = 20) -> str:
        return "\n".join(self.combined.splitlines()[-lines:])

    def last_json(self) -> dict[str, Any] | None:
        """The last stdout line that parses as a JSON object, if any."""
        return parse_last_json(self.stdout)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.argv),
            "returncode": self.returncode,
            "duration_seconds": round(self.duration, 2),
            "timed_out": self.timed_out,
            "cwd": self.cwd,
            "stdout_tail": "\n".join(self.stdout.splitlines()[-30:]),
            "stderr_tail": "\n".join(self.stderr.splitlines()[-15:]),
        }


def parse_last_json(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                return doc
    return None


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> CommandOutcome:
    started = time.monotonic()
    merged = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            list(argv), cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, timeout=timeout, env=merged,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandOutcome(
            argv=list(argv), returncode=124,
            stdout=exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=f"timed out after {timeout:g}s",
            duration=time.monotonic() - started, timed_out=True,
            cwd=str(cwd) if cwd else None,
        )
    except OSError as exc:
        return CommandOutcome(argv=list(argv), returncode=127, stderr=str(exc),
                              duration=time.monotonic() - started,
                              cwd=str(cwd) if cwd else None)
    return CommandOutcome(
        argv=list(argv), returncode=proc.returncode, stdout=proc.stdout or "",
        stderr=proc.stderr or "", duration=time.monotonic() - started,
        cwd=str(cwd) if cwd else None,
    )


def runner_dir(project_dir: Path | str) -> Path:
    """Where the project keeps its copy of the runner package."""
    return Path(project_dir).resolve() / "evals" / "runner"


def build_runner_cmd(runner: RunnerSpec, args: Sequence[str]) -> list[str]:
    """`python -m agent_sdk_evals <args>` through the resolved interpreter."""
    return [*runner.python_argv(), "-m", RUNNER_MODULE, *args]


def runner_env(project_dir: Path | str, env: dict[str, str] | None = None) -> dict[str, str]:
    """PYTHONPATH that makes both the runner copy and the project importable."""
    project = Path(project_dir).resolve()
    paths = [str(runner_dir(project)), str(project)]
    existing = (env or {}).get("PYTHONPATH") or os.environ.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    return {**(env or {}), "PYTHONPATH": os.pathsep.join(paths)}


def run_project_runner(
    project_dir: Path | str,
    args: Sequence[str],
    *,
    runner: RunnerSpec | None = None,
    cwd: Path | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> CommandOutcome:
    """Run the project's `agent_sdk_evals` copy with `args`."""
    project = Path(project_dir).resolve()
    runner = runner or resolve_runner(project)
    return run_command(
        build_runner_cmd(runner, args), cwd=cwd or project, timeout=timeout,
        env=runner_env(project, env),
    )


def run_probe(
    runner: RunnerSpec,
    source: str,
    args: Sequence[str] = (),
    *,
    cwd: Path | str | None = None,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
) -> CommandOutcome:
    """Execute probe source in the resolved interpreter (`python -c <source>`).

    The source lives in the calling script as a string, so the plugin never
    imports the SDK itself; the probe prints one JSON line the caller reads.
    """
    return run_command([*runner.python_argv(), "-c", source, *args], cwd=cwd, timeout=timeout, env=env)


def run_pytest(
    args: Sequence[str],
    *,
    runner: RunnerSpec | None = None,
    cwd: Path | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> CommandOutcome:
    """Run pytest through the resolved interpreter; its exit code is a real gate."""
    runner = runner or resolve_runner(cwd)
    project = Path(cwd).resolve() if cwd else None
    merged = runner_env(project, env) if project else env
    return run_command([*runner.python_argv(), "-m", "pytest", *args], cwd=cwd, timeout=timeout, env=merged)


def describe_runner(runner: RunnerSpec) -> str:
    if not runner.available:
        return runner.note or "no interpreter with claude_agent_sdk"
    if runner.sdk_version:
        return f"{runner.kind}: {runner.source} (claude-agent-sdk {runner.sdk_version})"
    if not runner.verified:
        return f"{runner.kind}: {runner.source} (unverified - claude_agent_sdk not checked)"
    return f"{runner.kind}: {runner.source}"
