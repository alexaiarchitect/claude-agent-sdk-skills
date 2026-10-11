"""The pinned SDK facts, checked against the installed wheel.

Every other test in this suite runs against the stub in `tests/fixtures/stubs/`,
which is a copy of the wheel's surface — so a test that compares a pinned tuple
with the stub proves only that two files in this repository agree. This module
is the one that can be wrong: it starts the interpreter the `sdk_python` fixture
resolved, asks the *real* `claude_agent_sdk` what it has, and compares.

It skips when no such interpreter exists, so a clone with no virtualenv still
has a green suite. At a sync it must **run**: that is how the option names, the
literals, the `ResultMessage` fields and the version pin get re-verified rather
than re-asserted.

Measured 2026-10-11 against `claude-agent-sdk` 0.2.165 (bundled CLI 2.1.294):
all five answers below matched the pins.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agent_sdk_skills import (
    CLI_BUNDLED_WITH_TARGET,
    EFFORT_LEVELS,
    OPTION_NAMES,
    PERMISSION_MODES,
    PYTHON_HOOK_EVENTS,
    SDK_TARGET,
)

#: The 19 `ResultMessage` fields, in declaration order (`types.py:1340`).
RESULT_MESSAGE_FIELDS = (
    "subtype", "duration_ms", "duration_api_ms", "is_error", "num_turns", "session_id",
    "stop_reason", "total_cost_usd", "usage", "result", "structured_output", "model_usage",
    "permission_denials", "deferred_tool_use", "errors", "api_error_status", "uuid",
    "terminal_reason", "origin",
)

#: One probe, one subprocess: starting the interpreter is the slow part, and a
#: single JSON answer keeps the comparison in this file rather than in the probe.
PROBE = r"""
import json, typing
import claude_agent_sdk as sdk
from claude_agent_sdk import types

def literal(name):
    # `HookEvent` is a union of Literals, not one Literal, so the args are
    # flattened one level before the strings are collected (order preserved).
    out = []
    for arg in typing.get_args(getattr(types, name)):
        if isinstance(arg, str):
            out.append(arg)
        else:
            out.extend(a for a in typing.get_args(arg) if isinstance(a, str))
    return out

def fields(cls):
    return list(cls.__dataclass_fields__)

print(json.dumps({
    "version": sdk.__version__,
    "cli_version": __import__(
        "claude_agent_sdk._cli_version", fromlist=["__cli_version__"]
    ).__cli_version__,
    "option_names": fields(sdk.ClaudeAgentOptions),
    "permission_modes": literal("PermissionMode"),
    "effort_levels": literal("EffortLevel"),
    "hook_events": literal("HookEvent"),
    "result_message": fields(sdk.ResultMessage),
}))
"""


@pytest.fixture(scope="module")
def surface(sdk_python) -> dict:
    proc = subprocess.run([sdk_python, "-c", PROBE], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        pytest.skip(f"the SDK probe did not run: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout)


def test_the_installed_wheel_is_the_release_the_plugin_was_checked_against(surface):
    """Not an equality the plugin controls: it is the fact every other pin rests on."""
    assert surface["version"] == SDK_TARGET
    assert surface["cli_version"] == CLI_BUNDLED_WITH_TARGET, (
        "the SDK bundles its own CLI; CLI_BUNDLED_WITH_TARGET records which one"
    )


def test_the_option_names_and_their_order_match_the_installed_dataclass(surface):
    live = surface["option_names"]
    assert len(live) == 49, f"the SDK now has {len(live)} options, the plugin pins 49"
    assert list(OPTION_NAMES) == live, (
        "OPTION_NAMES is order-sensitive: it is what EVC003 reports and what the "
        "references cite by line number"
    )


def test_the_permission_modes_are_the_six_the_plugin_knows(surface):
    assert list(PERMISSION_MODES) == surface["permission_modes"]


def test_the_effort_levels_are_the_five_the_plugin_knows(surface):
    assert list(EFFORT_LEVELS) == surface["effort_levels"]


def test_the_hook_events_are_the_ten_python_accepts(surface):
    """`SessionStart` has a `*HookSpecificOutput` type and is still not registrable."""
    live = surface["hook_events"]
    assert list(PYTHON_HOOK_EVENTS) == live
    assert "SessionStart" not in live and "SessionEnd" not in live, "HOK020's whole point"


def test_the_result_message_fields_are_the_nineteen_the_graders_read(surface):
    assert list(RESULT_MESSAGE_FIELDS) == surface["result_message"]
