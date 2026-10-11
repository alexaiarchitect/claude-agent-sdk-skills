"""Message -> trace event mapping, checked against the measured runs.

The scripts here are the shapes P-1 actually observed, so a change in the SDK
that breaks the mapping breaks these tests rather than a user's suite.
"""

from __future__ import annotations

import json

import claude_agent_sdk as sdk
import pytest

from agent_sdk_evals.capture import (
    Capture,
    flatten_usage,
    looks_like_usage_limit,
    rate_limit_payload,
)

INIT_DATA = {
    "type": "system", "subtype": "init", "cwd": "/tmp/run",
    "session_id": "s-1", "tools": ["Read", "StructuredOutput"],
    "mcp_servers": [{"name": "library", "status": "connected"}],
    "model": "claude-sonnet-5-5", "permissionMode": "dontAsk",
    "apiKeySource": "none", "claude_code_version": "2.1.294",
    "agents": ["Explore"], "skills": [], "plugins": [],
}

RATE_LIMIT_MEASURED = {
    "status": "allowed_warning", "resets_at": 1790784000, "rate_limit_type": "seven_day",
    "utilization": 0.83, "overage_status": None, "overage_resets_at": None,
    "overage_disabled_reason": None,
    "raw": {"status": "allowed_warning", "resetsAt": 1790784000, "rateLimitType": "seven_day",
            "utilization": 0.83, "isUsingOverage": False, "surpassedThreshold": 0.75,
            "unifiedWindows": {"five_hour": {"utilization": 0.55, "resetsAt": 1790773800},
                               "seven_day": {"utilization": 0.83, "resetsAt": 1790784000}}},
}

MEASURED_USAGE = {
    "input_tokens": 2, "cache_creation_input_tokens": 21503, "cache_read_input_tokens": 0,
    "output_tokens": 4, "output_tokens_details": {"thinking_tokens": 0},
    "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
    "service_tier": "standard",
    "cache_creation": {"ephemeral_1h_input_tokens": 21503, "ephemeral_5m_input_tokens": 0},
    "inference_geo": "not_available", "iterations": [], "speed": "standard",
    "fallback_credit": None,
}


def result_message(**overrides):
    payload = dict(
        subtype="success", duration_ms=1207, duration_api_ms=1780, is_error=False,
        num_turns=1, session_id="s-1", stop_reason="end_turn", total_cost_usd=0.086993,
        usage=MEASURED_USAGE, result="ready", structured_output=None,
        model_usage={"claude-sonnet-5-5": {"inputTokens": 2, "thinkingTokens": 0,
                                           "costBasis": "list"}},
        permission_denials=[], terminal_reason="completed",
    )
    payload.update(overrides)
    return sdk.ResultMessage(**payload)


def events_of(capture: Capture, type_: str):
    return [e for e in capture.events if e["type"] == type_]


def test_init_records_the_cli_version_and_the_api_key_source():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.SystemMessage(subtype="init", data=INIT_DATA))
    init = events_of(cap, "init")[0]
    assert init["cli_version"] == "2.1.294", "the measured field is the CLI version, not the SDK's"
    assert init["api_key_source"] == "none", "the in-band credential proof"
    assert init["permission_mode"] == "dontAsk"
    assert init["occurrence"] == 1
    assert init["tools"] == ["Read", "StructuredOutput"]


def test_init_can_arrive_more_than_once_and_is_numbered():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.SystemMessage(subtype="init", data=INIT_DATA))
    cap.add(sdk.SystemMessage(subtype="init", data=INIT_DATA))
    assert [e["occurrence"] for e in events_of(cap, "init")] == [1, 2]


def test_other_system_subtypes_are_kept_never_dropped():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.SystemMessage(subtype="commands_changed", data={"commands": []}))
    cap.add(sdk.TaskUpdatedMessage(subtype="task_updated", data={"status": "running"}))
    assert [e["subtype"] for e in events_of(cap, "system")] == ["commands_changed", "task_updated"]


def test_assistant_text_thinking_and_tool_use_map_to_their_own_events():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.AssistantMessage(
        content=[sdk.ThinkingBlock(thinking="a" * 40, signature="sig"),
                 sdk.TextBlock(text="hello"),
                 sdk.ToolUseBlock(id="t1", name="Read", input={"file_path": "/x"})],
        model="claude-sonnet-5-5", message_id="msg_1", uuid="u1", stop_reason="tool_use",
    ))
    thinking = events_of(cap, "thinking")[0]
    assert thinking["chars"] == 40 and "text" not in thinking, "thinking text is off by default"
    text = events_of(cap, "assistant_text")[0]
    assert (text["text"], text["model"], text["message_id"]) == ("hello", "claude-sonnet-5-5", "msg_1")
    use = events_of(cap, "tool_use")[0]
    assert (use["tool"], use["id"], use["synthetic"]) == ("Read", "t1", False)
    assert cap.last_message == "hello"


def test_thinking_text_is_recorded_when_the_config_allows_it():
    cap = Capture(run_id="r", case="c", include_thinking=True)
    cap.add(sdk.AssistantMessage(content=[sdk.ThinkingBlock(thinking="secret plan")],
                                 model="m"))
    assert events_of(cap, "thinking")[0]["text"] == "secret plan"


def test_structured_output_arrives_as_a_synthetic_tool_use():
    """Measured run 3: `output_format` results come through a `StructuredOutput` call."""
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.AssistantMessage(
        content=[sdk.ToolUseBlock(id="t1", name="StructuredOutput", input={"answer": "Paris"})],
        model="claude-sonnet-5-5", stop_reason="tool_use"))
    use = events_of(cap, "tool_use")[0]
    assert use["synthetic"] is True
    assert cap.tool_uses() == [], "synthetic calls are hidden from the default view"
    assert len(cap.tool_uses(include_synthetic=True)) == 1


def test_tool_result_keeps_is_error_null_and_the_rich_payload():
    """Measured: `is_error` is `null` on success, not `False`."""
    cap = Capture(run_id="r", case="c")
    rich = {"type": "text", "file": {"filePath": "/x/notes.txt", "content": "Ledger opens at 09:00.",
                                     "numLines": 1, "startLine": 1, "totalLines": 3}}
    cap.add(sdk.UserMessage(
        content=[sdk.ToolResultBlock(tool_use_id="t1", content="1\tLedger opens at 09:00.",
                                     is_error=None)],
        uuid="u", tool_use_result=rich))
    event = events_of(cap, "tool_result")[0]
    assert event["is_error"] is None
    assert event["content_chars"] == len("1\tLedger opens at 09:00.")
    assert event["tool_use_result"]["file"]["numLines"] == 1


def test_a_long_tool_result_is_truncated_but_its_length_is_kept():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.UserMessage(content=[sdk.ToolResultBlock(tool_use_id="t1", content="x" * 5000)]))
    event = events_of(cap, "tool_result")[0]
    assert event["content_chars"] == 5000
    assert len(event["content"]) < 5000 and "+2952 chars" in event["content"]


def test_server_tool_blocks_get_their_own_event_types():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.AssistantMessage(
        content=[sdk.ServerToolUseBlock(id="s1", name="web_search", input={"query": "x"}),
                 sdk.ServerToolResultBlock(tool_use_id="s1", content={"results": []})],
        model="m"))
    assert events_of(cap, "server_tool_use")[0]["tool"] == "web_search"
    assert events_of(cap, "server_tool_result")[0]["tool_use_id"] == "s1"
    assert cap.tool_uses() == [], "a server tool is not an agent tool call"


def test_the_result_event_flattens_usage_and_keeps_the_raw_dict():
    cap = Capture(run_id="r", case="c")
    cap.add(result_message())
    event = events_of(cap, "result")[0]
    assert event["usage"] == {
        "input_tokens": 2, "output_tokens": 4, "cache_creation_input_tokens": 21503,
        "cache_read_input_tokens": 0, "thinking_tokens": 0,
        "web_search_requests": 0, "web_fetch_requests": 0,
        "service_tier": "standard", "speed": "standard",
    }
    assert isinstance(event["usage_raw"]["cache_creation"], dict), \
        "cache_creation is a nested dict of TTL buckets, never a count"
    assert event["result_text"] == "ready", "renamed so it cannot collide with the event type"
    assert event["terminal_reason"] == "completed"


def test_cost_delta_is_the_diff_because_the_total_is_cumulative():
    """Measured run 3: turn 1 reported 0.004991, turn 2 reported 0.0061734."""
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(total_cost_usd=0.004991))
    cap.add(result_message(total_cost_usd=0.0061734))
    deltas = [e["cost_delta_usd"] for e in events_of(cap, "result")]
    assert deltas[0] == pytest.approx(0.004991)
    assert deltas[1] == pytest.approx(0.0011824)
    assert cap.total_cost_usd == pytest.approx(0.0061734), "the case cost is the last total"


def test_a_missing_total_cost_does_not_invent_a_delta():
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(total_cost_usd=None))
    assert events_of(cap, "result")[0]["cost_delta_usd"] == 0.0


def test_the_rate_limit_event_reads_the_windows_out_of_raw():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.RateLimitEvent(rate_limit_info=sdk.RateLimitInfo(**RATE_LIMIT_MEASURED),
                               uuid="u", session_id="s"))
    event = events_of(cap, "rate_limit")[0]
    assert event["status"] == "allowed_warning"
    assert event["surpassed_threshold"] == 0.75, "not modelled on the dataclass; read from raw"
    assert event["windows"]["five_hour"] == {"utilization": 0.55, "resets_at": 1790773800}
    assert event["kind"] == "rate_limit"
    assert cap.rejected_rate_limit is None, "allowed_warning is not a rejection"


def test_only_a_rejected_status_marks_the_run_as_rejected():
    cap = Capture(run_id="r", case="c")
    info = dict(RATE_LIMIT_MEASURED, status="rejected")
    info["raw"] = dict(info["raw"], status="rejected")
    cap.add(sdk.RateLimitEvent(rate_limit_info=sdk.RateLimitInfo(**info)))
    assert cap.rejected_rate_limit is not None
    assert cap.rate_limit["status"] == "rejected"


def test_a_usage_limit_error_result_is_classified_without_an_sdk_message_type():
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(subtype="error_during_execution", is_error=True,
                           result="Claude usage limit reached; resets at 6pm",
                           api_error_status=429, terminal_reason="api_error"))
    limit = events_of(cap, "rate_limit")[0]
    assert limit["kind"] == "usage_limit"
    assert limit["status"] == "rejected"
    assert cap.rejected_rate_limit is not None


def test_a_plain_error_result_is_not_a_usage_limit():
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(subtype="error_during_execution", is_error=True,
                           result="the tool crashed", terminal_reason="api_error"))
    assert events_of(cap, "rate_limit") == []
    assert cap.rejected_rate_limit is None


@pytest.mark.parametrize("text,status,expected", [
    ("Claude usage limit reached", None, True),
    ("too many requests", None, True),
    (None, 429, True),
    ("the tool crashed", None, False),
    ("", None, False),
])
def test_usage_limit_detection(text, status, expected):
    assert looks_like_usage_limit(text, status) is expected


def test_conversation_reset_gets_its_own_event():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.ConversationResetMessage(new_conversation_id="c-2", uuid="u", session_id="s"))
    assert events_of(cap, "conversation_reset")[0]["new_conversation_id"] == "c-2"


def test_a_hook_event_message_becomes_a_hook_event():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.HookEventMessage(subtype="hook_response", hook_event_name="PreToolUse",
                                 data={"tool_name": "Read", "decision": "deny"}))
    event = events_of(cap, "hook")[0]
    assert (event["event"], event["phase"], event["decision"]) == ("PreToolUse", "hook_response", "deny")


def test_an_unknown_message_type_is_kept_as_a_system_event():
    class SomethingNew:
        def __init__(self) -> None:
            self.whatever = "value"

    cap = Capture(run_id="r", case="c")
    cap.add(SomethingNew())
    event = events_of(cap, "system")[0]
    assert event["subtype"] == "SomethingNew"
    assert event["data"]["whatever"] == "value"


def test_the_session_id_is_picked_up_from_the_first_message_that_has_one():
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(session_id="s-42"))
    assert cap.session_id == "s-42"


def test_the_trace_round_trips_as_jsonl():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.SystemMessage(subtype="init", data=INIT_DATA))
    cap.add(result_message())
    lines = cap.to_jsonl().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["type"] for line in lines] == ["init", "result"]


def test_flatten_usage_tolerates_nothing_at_all():
    assert flatten_usage(None)["input_tokens"] == 0


def test_rate_limit_payload_accepts_a_plain_dict():
    payload = rate_limit_payload(RATE_LIMIT_MEASURED)
    assert payload["utilization"] == 0.83


def test_the_measured_runs_replay_through_the_capture(measured):
    """The real thing: every line of every measured run maps to an event."""
    for name in ("run1.jsonl", "run2.jsonl", "run3.jsonl"):
        script = measured(name)
        cap = Capture(run_id="r", case=name)
        for entry in script:
            cap.add(sdk.build_message(entry))
        assert len(cap.events) >= len(script) - 1, f"{name}: events were dropped"
        assert events_of(cap, "init"), f"{name}: no init event"
    # run2 read a file: one real tool call, one result with the rich payload.
    cap = Capture(run_id="r", case="run2")
    for entry in measured("run2.jsonl"):
        cap.add(sdk.build_message(entry))
    assert [e["tool"] for e in cap.tool_uses()] == ["Read"]
    assert cap.tool_results()[0]["tool_use_result"]["file"]["filePath"].endswith("notes.txt")
    # run3 used output_format: the only call is the synthetic one.
    cap = Capture(run_id="r", case="run3")
    for entry in measured("run3.jsonl"):
        cap.add(sdk.build_message(entry))
    assert cap.tool_uses() == []
    assert all(e["synthetic"] for e in cap.tool_uses(include_synthetic=True))
    assert cap.result["structured_output"] == {"answer": "Tokyo"}
    assert cap.total_cost_usd == pytest.approx(0.0061734)


def test_the_measured_session_carries_a_tool_use_result(measured):
    """Closes the shape CONTRACTS could not pin: `toolUseResult` on a session
    line, measured from a session this runner produced.

    It is **tool-dependent**, not one shape: an in-process MCP tool's result is
    the raw content list, while a built-in's is a dict of that tool's own fields.
    Anything reading it must branch on the type, never index it blindly.
    """
    lines = measured("session_with_tool.jsonl")
    with_result = [line for line in lines if "toolUseResult" in line]
    assert with_result, "the measured session made no tool call"
    shapes = {type(line["toolUseResult"]).__name__ for line in with_result}
    assert shapes <= {"list", "dict", "str"}
    mcp = [line["toolUseResult"] for line in with_result
           if isinstance(line["toolUseResult"], list)]
    assert mcp and mcp[0][0]["type"] == "text", \
        "an in-process MCP tool's result is the content list verbatim"


def test_the_measured_session_carries_cost_after_all(measured):
    """A correction to the earlier measurement: a session produced through the
    SDK (`entrypoint: sdk-py`) has a `cost-state` line with `totalCostUSD`, so a
    `budget` grader on an imported session is not always inconclusive."""
    lines = measured("session_with_tool.jsonl")
    cost = [line for line in lines if line.get("type") == "cost-state"]
    assert cost, "no cost-state line"
    assert cost[0]["totalCostUSD"] > 0
    assert {line.get("entrypoint") for line in lines if line.get("entrypoint")} == {"sdk-py"}


def test_the_measured_session_keeps_line_types_the_loader_must_not_drop(measured):
    lines = measured("session_with_tool.jsonl")
    types = {line.get("type") for line in lines}
    assert {"user", "assistant", "attachment"} <= types
    # Two types the first measured session did not have at all.
    assert {"system", "cost-state"} <= types


# -- who chose the permission mode, and what the cost was billed to --------

def test_init_records_who_decided_the_permission_mode():
    """The mode the CLI reports does not say whether anyone chose it (CONTRACTS 13.1)."""
    cap = Capture(run_id="r", case="c", permission_mode_source="runner-default")
    cap.add(sdk.SystemMessage(subtype="init", data=INIT_DATA))
    init = events_of(cap, "init")[0]
    assert init["permission_mode"] == "dontAsk", "what the CLI reported"
    assert init["permission_mode_source"] == "runner-default", "who decided it"


def test_an_unsourced_capture_still_emits_the_key_as_null():
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.SystemMessage(subtype="init", data=INIT_DATA))
    assert events_of(cap, "init")[0]["permission_mode_source"] is None


def test_the_result_names_every_model_billed_and_whether_it_was_list_priced():
    """Measured 2026-10-11: CLI 2.1.294 bills background work to Haiku 5.5 unasked."""
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(model_usage={
        "claude-sonnet-5-5": {"inputTokens": 8, "costUSD": 0.0452374,
                              "thinkingTokens": 0, "costBasis": "list"},
        "claude-haiku-5-5": {"inputTokens": 1192, "costUSD": 0.0001322,
                             "thinkingTokens": 0, "costBasis": "list"},
    }))
    result = events_of(cap, "result")[0]
    assert result["models_billed"] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert result["cost_basis_list"] is True


def test_a_managed_rate_on_any_model_clears_the_list_price_flag():
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(model_usage={
        "claude-sonnet-5-5": {"costBasis": "list"},
        "claude-haiku-5-5": {"costBasis": "managed"},
    }))
    assert events_of(cap, "result")[0]["cost_basis_list"] is False


def test_an_absent_cost_basis_counts_as_list_and_never_raises():
    """`costBasis` is not on the 0.2.165 `ModelUsage` TypedDict, so it is read with `.get()`."""
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(model_usage={"claude-sonnet-5-5": {"inputTokens": 2}}))
    result = events_of(cap, "result")[0]
    assert result["cost_basis_list"] is True
    assert result["models_billed"] == ["claude-sonnet-5-5"]


def test_no_model_usage_at_all_is_vacuously_list_priced():
    cap = Capture(run_id="r", case="c")
    cap.add(result_message(model_usage={}))
    result = events_of(cap, "result")[0]
    assert result["models_billed"] == [] and result["cost_basis_list"] is True
