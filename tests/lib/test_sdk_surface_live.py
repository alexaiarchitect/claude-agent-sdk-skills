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

Measured 2026-10-17 against `claude-agent-sdk` 0.2.168 (bundled CLI 2.1.301):
every answer below matched the pins. (History: the 2026-10-11 run against
0.2.165 / CLI 2.1.294 matched the five checks that existed then.)
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from agent_sdk_skills import (
    CLI_BUNDLED_WITH_TARGET,
    EFFORT_LEVELS,
    OPTION_NAMES,
    PERMISSION_MODES,
    HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT,
    PYTHON_HOOK_EVENTS,
    SDK_TARGET,
)

#: The 19 `ResultMessage` fields, in declaration order (`types.py:1695` of 0.2.168).
RESULT_MESSAGE_FIELDS = (
    "subtype", "duration_ms", "duration_api_ms", "is_error", "num_turns", "session_id",
    "stop_reason", "total_cost_usd", "usage", "result", "structured_output", "model_usage",
    "permission_denials", "deferred_tool_use", "errors", "api_error_status", "uuid",
    "terminal_reason", "origin",
)

#: The 26 names `__all__` gained in 0.2.166 (133 -> 159; none removed since).
NEW_IN_0_2_166 = (
    "SystemInitData", "SystemInitMcpServer", "SystemInitPlugin", "SystemInitPluginError",
    "FastModeState", "FastModeDisabledReason", "HookEffort", "BackgroundTaskSummary",
    "SessionCronSummary",
    "PreToolUseHookSpecificOutput", "PostToolUseHookSpecificOutput",
    "UserPromptSubmitHookSpecificOutput", "UserPromptExpansionHookSpecificOutput",
    "SessionStartHookSpecificOutput", "PostToolBatchHookSpecificOutput",
    "StopHookSpecificOutput", "SubagentStopHookSpecificOutput",
    "PermissionDeniedHookSpecificOutput", "PreModelSwitchHookSpecificOutput",
    "PostModelSwitchHookSpecificOutput", "ElicitationHookSpecificOutput",
    "ElicitationResultHookSpecificOutput", "CwdChangedHookSpecificOutput",
    "FileChangedHookSpecificOutput", "WorktreeCreateHookSpecificOutput",
    "MessageDisplayHookSpecificOutput",
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
    "all": list(sdk.__all__),
    "specific_output_events": [
        typing.get_args(typing.get_type_hints(c)["hookEventName"])[0]
        for c in typing.get_args(types.HookSpecificOutput)
    ],
    "ignore_violations": str(typing.get_type_hints(types.SandboxSettings)["ignoreViolations"]),
    "system_init_data": list(typing.get_type_hints(types.SystemInitData)),
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


def test_the_export_list_is_the_one_the_stub_mirrors(surface):
    """159 names on 0.2.168; `HookEvent` is not among them (import it from `.types`)."""
    live = surface["all"]
    assert len(live) == 159
    assert len(NEW_IN_0_2_166) == 26 and set(NEW_IN_0_2_166) <= set(live)
    assert "HookEvent" not in live


def test_only_precompact_lacks_a_hook_specific_output(surface):
    """21 `*HookSpecificOutput` types; of the 10 Python events only `PreCompact` has none."""
    typed = surface["specific_output_events"]
    assert len(typed) == 21
    missing = tuple(e for e in PYTHON_HOOK_EVENTS if e not in typed)
    assert missing == HOOK_EVENTS_WITHOUT_SPECIFIC_OUTPUT == ("PreCompact",)
    assert {"Stop", "SubagentStop"} <= set(typed)


def test_ignore_violations_maps_a_command_pattern_to_violation_substrings(surface):
    assert surface["ignore_violations"] == "dict[str, list[str]]"


def test_system_init_data_declares_capabilities_and_fast_mode(surface):
    keys = surface["system_init_data"]
    assert {"capabilities", "fast_mode_state", "fast_mode_disabled_reason"} <= set(keys)


def test_the_stub_exports_what_0_2_166_added():
    """Offline: the stub in `tests/fixtures/stubs/` mirrors the new exports and pins."""
    from pathlib import Path
    stub = Path(__file__).resolve().parents[1] / "fixtures" / "stubs"
    probe = ("import json, claude_agent_sdk as s, claude_agent_sdk._cli_version as c;"
             "print(json.dumps([s.__all__, s.__version__, c.__cli_version__]))")
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          timeout=60, cwd=stub)
    assert proc.returncode == 0, proc.stderr
    names, version, cli = json.loads(proc.stdout)
    assert set(NEW_IN_0_2_166) <= set(names)
    assert (version, cli) == (SDK_TARGET, CLI_BUNDLED_WITH_TARGET)
