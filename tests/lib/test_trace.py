"""The event model, both loaders, and the project-directory encoding."""

from __future__ import annotations

import json
import subprocess

import pytest
from agent_sdk_skills.trace import (
    MAX_SANITIZED_LENGTH,
    SCHEMA,
    TraceEvent,
    events_of,
    final_text,
    hook_events,
    init_event,
    is_imported,
    known_tool_names,
    load_session,
    load_trace,
    project_key_for_directory,
    rate_limit_events,
    result_event,
    to_summary,
    tool_calls,
    tool_errors,
    tool_names,
    write_trace,
)

@pytest.fixture
def traces(fixtures):
    return fixtures / "traces"


@pytest.fixture
def happy(traces):
    return load_trace(traces / "happy.trace.jsonl")


# -- the trace loader ------------------------------------------------------

def test_a_trace_loads_in_order_with_its_envelope(happy):
    assert happy[0].type == "init"
    assert happy[-1].type == "result"
    assert [e.i for e in happy] == list(range(len(happy)))
    assert all(e.case == "reserve-available" for e in happy)
    assert all(e.session_id for e in happy)


def test_the_schema_is_stamped_on_the_first_line_only(traces):
    lines = [json.loads(line) for line in
             (traces / "happy.trace.jsonl").read_text().splitlines()]
    assert lines[0]["schema"] == SCHEMA
    assert all("schema" not in line for line in lines[1:])


def test_an_unknown_event_type_is_kept_as_system_not_dropped(tmp_path):
    """A newer runner's event must survive a loader that has never seen it."""
    path = tmp_path / "x.trace.jsonl"
    path.write_text(json.dumps({"schema": SCHEMA, "i": 0, "type": "quantum_flux",
                                "payload": 1}) + "\n")
    events = load_trace(path)
    assert len(events) == 1
    assert events[0].type == "system"
    assert events[0].get("unknown_type") == "quantum_flux"
    assert events[0].get("payload") == 1


def test_a_malformed_line_never_loses_the_rest_of_the_file(tmp_path):
    """A truncated trace is the normal outcome of a killed run, and still useful."""
    path = tmp_path / "x.trace.jsonl"
    path.write_text(json.dumps({"i": 0, "type": "user", "text": "hi"}) + "\n"
                    + "{not json\n"
                    + json.dumps({"i": 2, "type": "assistant_text", "text": "bye"}) + "\n")
    events = load_trace(path)
    assert [e.type for e in events] == ["user", "system", "assistant_text"]
    assert events[1].get("subtype") == "parse_error"


def test_a_missing_file_returns_a_load_error_event(tmp_path):
    events = load_trace(tmp_path / "absent.trace.jsonl")
    assert len(events) == 1 and events[0].get("subtype") == "load_error"


def test_a_trace_round_trips_through_write_trace(tmp_path, happy):
    path = tmp_path / "out.trace.jsonl"
    write_trace(path, happy)
    again = load_trace(path)
    assert [e.type for e in again] == [e.type for e in happy]
    assert json.loads(path.read_text().splitlines()[0])["schema"] == SCHEMA


# -- readers ---------------------------------------------------------------

def test_tool_calls_skip_synthetic_ones_by_default(traces):
    """`StructuredOutput` is fabricated by the CLI; counting it invents a call."""
    events = load_trace(traces / "structured_output.trace.jsonl")
    assert tool_calls(events) == []
    visible = tool_calls(events, include_synthetic=True)
    assert [c.tool for c in visible] == ["StructuredOutput"]
    assert visible[0].synthetic


def test_a_synthetic_flag_is_recomputed_when_an_old_trace_omits_it(tmp_path):
    path = tmp_path / "x.trace.jsonl"
    path.write_text(json.dumps({"i": 0, "type": "tool_use", "tool": "StructuredOutput",
                                "input": {}}) + "\n")
    assert load_trace(path)[0].synthetic
    assert tool_calls(load_trace(path)) == []


def test_tool_names_reads_the_real_trajectory(happy):
    assert tool_names(happy) == ["mcp__library__lookup_book", "mcp__library__reserve_book"]


def test_tool_errors_test_truthiness_because_is_error_is_null_on_success(happy, traces):
    """`is_error` is `null` on success, not `False`."""
    assert tool_errors(happy) == []
    results = events_of(happy, "tool_result")
    assert results and all(r.get("is_error") is None for r in results)
    assert len(tool_errors(load_trace(traces / "loop.trace.jsonl"))) == 4


def test_final_text_prefers_the_result_events_own_text(happy):
    assert final_text(happy).startswith("I looked up Dune")


def test_final_text_falls_back_to_the_last_assistant_message(tmp_path):
    path = tmp_path / "x.trace.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [
        {"i": 0, "type": "assistant_text", "text": "first"},
        {"i": 1, "type": "assistant_text", "text": "last"},
    ]) + "\n")
    assert final_text(load_trace(path)) == "last"


def test_result_event_returns_none_when_there_is_none(tmp_path):
    path = tmp_path / "x.trace.jsonl"
    path.write_text(json.dumps({"i": 0, "type": "user", "text": "hi"}) + "\n")
    assert result_event(load_trace(path)) is None


def test_rate_limit_events_are_found_but_are_not_themselves_a_problem(happy):
    """One fired on every measured run at `allowed_warning`."""
    limits = rate_limit_events(happy)
    assert len(limits) == 1
    assert limits[0].get("status") == "allowed_warning"
    assert limits[0].get("windows")["seven_day"]["utilization"] == 0.83


def test_known_tool_names_come_from_init(happy):
    names = known_tool_names(happy)
    assert "mcp__library__lookup_book" in names


def test_hook_events_can_be_filtered_by_event_name(tmp_path):
    path = tmp_path / "x.trace.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [
        {"i": 0, "type": "hook", "event": "PreToolUse", "tool": "Bash"},
        {"i": 1, "type": "hook", "event": "Stop"},
    ]) + "\n")
    events = load_trace(path)
    assert len(hook_events(events)) == 2
    assert len(hook_events(events, event="Stop")) == 1


# -- the summary -----------------------------------------------------------

def test_a_summary_reports_what_happened(happy):
    summary = to_summary(happy)
    assert summary["tool_calls"] == 2
    assert summary["turns"] == 1
    assert summary["has_result"] is True
    assert summary["result"]["terminal_reason"] == "completed"
    assert summary["result"]["cost_basis"] == "subscription"
    assert summary["init"]["cli_version"] == "2.1.301"
    assert summary["init"]["api_key_source"] == "none"
    assert summary["rate_limit"]["status"] == "allowed_warning"


def test_a_summary_says_plainly_what_it_could_not_measure(fixtures):
    """No result event is the difference between 'under budget' and 'nobody knows'."""
    summary = to_summary(load_session(fixtures / "sessions" / "one_turn.jsonl"))
    assert summary["has_result"] is False
    assert set(summary["not_evaluated"]) == {"budget", "terminal", "structured_output"}
    assert "no result event" in summary["not_evaluated_reason"]


def test_a_summary_counts_synthetic_calls_separately(traces):
    summary = to_summary(load_trace(traces / "structured_output.trace.jsonl"))
    assert summary["tool_calls"] == 0
    assert summary["synthetic_tool_calls"] == 1


# -- the session loader ----------------------------------------------------

@pytest.fixture
def session(fixtures):
    return load_session(fixtures / "sessions" / "one_turn.jsonl")


def test_a_session_keeps_every_bookkeeping_line(session, fixtures):
    """5 of the 7 measured line types are undocumented bookkeeping."""
    raw = (fixtures / "sessions" / "one_turn.jsonl").read_text().splitlines()
    assert len(session) == len(raw) + 1, "every line, plus the synthesized init"
    subtypes = {e.get("subtype") for e in events_of(session, "system")}
    assert {"attachment", "ai-title", "queue-operation", "atis-latch",
            "last-prompt"} <= subtypes


def test_a_session_has_no_result_event(session):
    assert result_event(session) is None
    assert is_imported(session)


def test_the_synthesized_init_carries_the_cli_version_not_the_sdks(session):
    """`version` was measured as the CLI version; claiming it is the SDK's is wrong."""
    init = init_event(session)
    assert init.get("cli_version") == "2.1.274"
    assert init.get("sdk_version") is None
    assert init.get("entrypoint") == "sdk-cli"
    assert init.get("source") == "session_jsonl"


def test_the_message_content_becomes_the_same_events(session):
    assert [e.text for e in events_of(session, "user")] == ["Reply with exactly: ready"]
    assert [e.text for e in events_of(session, "assistant_text")] == ["ready"]
    assert final_text(session) == "ready"


def test_the_parent_chain_runs_through_attachment_lines(fixtures, session):
    """The measured assistant line's parent was an attachment, not the user turn.

    A loader assuming user->assistant adjacency mis-orders any real session.
    """
    raw = [json.loads(line) for line in
           (fixtures / "sessions" / "one_turn.jsonl").read_text().splitlines()]
    assistant = next(r for r in raw if r["type"] == "assistant")
    parent = next(r for r in raw if r.get("uuid") == assistant["parentUuid"])
    assert parent["type"] == "attachment", "the fixture must keep this shape"
    # The user event still precedes the assistant event after the walk.
    order = [e.type for e in session]
    assert order.index("user") < order.index("assistant_text")


def test_a_session_with_a_tool_call_maps_it_like_a_trace(tmp_path):
    """The session-side `toolUseResult` key is UNMEASURED: read it, never require it."""
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in [
        {"type": "user", "uuid": "u1", "parentUuid": None, "cwd": "/w", "version": "2.1.0",
         "sessionId": "s", "message": {"role": "user", "content": "read it"}},
        {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": "s",
         "message": {"role": "assistant", "model": "claude-sonnet-5-5", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/w/x"}}]}},
        {"type": "user", "uuid": "u2", "parentUuid": "a1", "sessionId": "s",
         "toolUseResult": {"type": "text", "file": {"filePath": "/w/x", "numLines": 1}},
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": "line one",
              "is_error": None}]}},
    ]) + "\n")
    events = load_session(path)
    assert tool_names(events) == ["Read"]
    result = events_of(events, "tool_result")[0]
    assert result.get("content") == "line one"
    assert result.get("tool_use_result")["file"]["filePath"] == "/w/x"
    assert tool_errors(events) == []


# -- an imported session's own cost (CONTRACTS section 13.2) ---------------

@pytest.fixture
def sdk_session(fixtures):
    """A real `entrypoint: "sdk-py"` session, scrubbed: it has a `cost-state` line."""
    return load_session(fixtures / "sessions" / "sdk_with_tool.jsonl")


def test_a_cost_state_line_becomes_a_result_event_marked_imported(sdk_session):
    result = result_event(sdk_session)
    assert result is not None, "an SDK-produced session reports its own cost"
    assert result.get("imported_cost") is True
    assert result.get("total_cost_usd") == pytest.approx(0.0300306)
    assert result.get("duration_ms") == 5625, "from totalDuration"


def test_the_fields_a_cost_state_line_does_not_carry_stay_null(sdk_session):
    """Guessing a terminal state from a cost line is how a FAILED verdict gets invented."""
    result = result_event(sdk_session)
    assert result.get("subtype") is None
    assert result.get("terminal_reason") is None
    assert result.get("num_turns") is None


def test_the_per_model_cost_survives_the_import(sdk_session):
    result = result_event(sdk_session)
    assert result.get("models_billed") == ["claude-haiku-4-5-20251001", "claude-sonnet-5-5"]
    assert result.get("cost_basis_list") is True, "a session cost-state line reports no basis"
    assert set(result.get("model_usage")) == set(result.get("models_billed"))


def test_an_imported_session_with_a_cost_is_still_imported(sdk_session):
    """`is_imported` reads the init's source, not whether a result exists."""
    assert is_imported(sdk_session)
    summary = to_summary(sdk_session)
    assert summary["imported"] is True and summary["has_result"] is True
    assert summary["result"]["imported_cost"] is True


def test_budget_becomes_decidable_while_terminal_does_not(sdk_session):
    summary = to_summary(sdk_session)
    assert "budget" not in summary["not_evaluated"], "the cost is now known"
    assert set(summary["not_evaluated"]) == {"terminal", "structured_output"}
    assert "cost-state" in summary["not_evaluated_reason"]


def test_the_system_and_stop_hook_summary_lines_stay_system_events(sdk_session, fixtures):
    subtypes = {e.get("subtype") for e in events_of(sdk_session, "system")}
    assert "system" in subtypes, "the stop_hook_summary line is kept, not dropped"
    assert {"attachment", "ai-title", "queue-operation", "atis-latch",
            "last-prompt"} <= subtypes
    raw = (fixtures / "sessions" / "sdk_with_tool.jsonl").read_text().splitlines()
    assert len(sdk_session) >= len(raw), "nothing is dropped; blocks can add events"


def test_a_session_without_a_cost_state_line_still_has_no_result(session):
    """`claude -p` writes no cost-state line, so section 5.3 still holds for it."""
    assert result_event(session) is None


def test_a_session_line_that_is_not_json_is_kept_as_a_system_event(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text('{"type": "ai-title", "aiTitle": "x"}\nnot json\n')
    events = load_session(path)
    assert any(e.get("subtype") == "_parse_error" for e in events)


# -- the project directory encoding ----------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("/a/b c", "-a-b-c"),
    ("/tmp/my_app.v2", "-tmp-my-app-v2"),
    ("/Users/x/Café", "-Users-x-Caf-"),
])
def test_every_non_alphanumeric_character_becomes_a_hyphen(path, expected):
    """Not just the separators: dots and underscores are replaced too."""
    assert project_key_for_directory(path, canonicalize=False) == expected


def test_a_long_path_is_truncated_and_hashed():
    long_path = "/" + ("x" * 300)
    key = project_key_for_directory(long_path, canonicalize=False)
    assert len(key) > MAX_SANITIZED_LENGTH
    prefix, _, suffix = key.rpartition("-")
    assert len(prefix) == MAX_SANITIZED_LENGTH
    assert suffix.isalnum(), "a base36 hash of the full path"


def test_the_encoding_agrees_with_the_sdks_own_answer(sdk_python):
    """A reimplemented encoding nobody checks is a way to read the wrong directory.

    The interpreter comes from the `sdk_python` fixture, which resolves the
    0.2.168 venv first and the older paths as fallbacks.
    """
    cases = ["/a/b c", "/tmp/my_app.v2", "/", "/Users/x/Café", "/" + "x" * 300]
    probe = (
        "import json,sys,unicodedata\n"
        "from claude_agent_sdk._internal.sessions import _sanitize_path\n"
        "print(json.dumps([_sanitize_path(unicodedata.normalize('NFC', c))"
        " for c in json.loads(sys.argv[1])]))\n"
    )
    proc = subprocess.run([sdk_python, "-c", probe, json.dumps(cases)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        pytest.skip(f"the SDK probe did not run: {proc.stderr.strip()[:200]}")
    theirs = json.loads(proc.stdout)
    ours = [project_key_for_directory(c, canonicalize=False) for c in cases]
    assert ours == theirs


def test_an_event_renders_back_to_its_wire_shape():
    event = TraceEvent(type="tool_use", i=3, t="2026-09-30T10:00:00Z", case="c",
                       data={"tool": "Bash", "input": {"command": "ls"}})
    assert event.to_dict() == {
        "i": 3, "type": "tool_use", "t": "2026-09-30T10:00:00Z", "case": "c",
        "tool": "Bash", "input": {"command": "ls"},
    }


# -- 0.2.166+ fields (measured on CLI 2.1.301, 2026-10-17) -------------------

#: The hook-input fields SDK 0.2.166 added: two on every event, one on the tool
#: events, three on `Stop`/`SubagentStop`.
NEW_HOOK_INPUT = {
    "prompt_id": "p-1", "effort": {"level": "high"}, "duration_ms": 41,
    "last_assistant_message": "Done.",
    "background_tasks": [{"id": "b1", "type": "bash", "status": "running", "description": "x"}],
    "session_crons": [{"id": "c1", "schedule": "*/5 * * * *", "recurring": True, "prompt": "p"}],
}


def test_a_2_1_301_trace_summarizes_capabilities_and_fast_mode(traces):
    events = load_trace(traces / "init_2_1_301.trace.jsonl")
    summary = to_summary(events)
    assert summary["init"]["cli_version"] == "2.1.301"
    assert len(summary["init"]["capabilities"]) == 11
    assert summary["init"]["fast_mode_state"] == "off"
    assert summary["init"]["fast_mode_disabled_reason"] == "sdk_opt_in_required"
    assert [e.get("subtype") for e in events_of(events, "system")] == ["commands_changed"]
    assert summary["has_result"] is True


def test_an_older_trace_has_no_capabilities_and_that_is_fine(happy):
    assert "capabilities" not in to_summary(happy)["init"]


def test_new_hook_input_fields_ride_along_in_a_trace(tmp_path):
    path = tmp_path / "t.trace.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [
        {"i": 0, "type": "hook", "event": "Stop", "phase": "hook_response",
         "data": {"hook_event_name": "Stop", "stop_hook_active": False, **NEW_HOOK_INPUT}},
        {"i": 1, "type": "hook", "event": "PostToolUse", "tool": "Bash",
         "data": {"tool_name": "Bash", "duration_ms": 41, "prompt_id": "p-1"}},
    ]) + "\n")
    events = load_trace(path)
    stop = hook_events(events, event="Stop")[0]
    assert stop.get("data")["session_crons"][0]["schedule"] == "*/5 * * * *"
    assert to_summary(events)["hooks"] == {"Stop": 1, "PostToolUse": 1}


def test_new_hook_input_fields_ride_along_in_an_imported_session(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in [
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "s", "cwd": "/w",
         "version": "2.1.301", "message": {"role": "user", "content": "hi"}},
        {"type": "attachment", "uuid": "a1", "parentUuid": "u1", "sessionId": "s",
         "attachment": {"type": "hook_success", "hookEvent": "Stop", **NEW_HOOK_INPUT}},
        {"type": "system", "subtype": "stop_hook_summary", "uuid": "y1", "parentUuid": "a1",
         "sessionId": "s", **NEW_HOOK_INPUT},
    ]) + "\n")
    events = load_session(path)
    assert init_event(events).get("cli_version") == "2.1.301"
    kinds = [e.get("subtype") for e in events_of(events, "system")]
    assert kinds == ["attachment", "system"]
    attachment, summary_line = events_of(events, "system")
    assert "session_crons" in attachment.get("data")["attachment_keys"]
    assert summary_line.get("data")["prompt_id"] == "p-1"
