"""Runner behaviour pinned by the 2026-10-29 sync (Claude Code 2.1.311/2.1.312 docs).

1. A run the turn limit ended carries the documented "+1" sizing rule in the
   `terminal` grader's reason (docs agent-loop, read 2026-10-29), without
   changing any verdict. The fixture is the measured shape: one tool call under
   `max_turns=1` → `error_max_turns`, `stop_reason "tool_use"`, `num_turns 2`.
2. Claude Code 2.1.311 escapes DEL, C1 and Unicode format characters as
   `\\uXXXX` in `--output-format json`/`stream-json`. The SDK parses the line
   with `json.loads`, so the runner sees the decoded characters; the capture and
   the replay loader must keep them through a trace round trip.
"""

from __future__ import annotations

import json
from pathlib import Path

import claude_agent_sdk as sdk

import agent_sdk_skills.budget as plugin_budget
from agent_sdk_evals import FAILED, PASSED
from agent_sdk_evals.capture import Capture
from agent_sdk_evals.cli import evidence_from_trace, load_trace
from agent_sdk_evals.graders import grade_free
from agent_sdk_evals.graders import terminal as terminal_grader

TRACES = Path(__file__).resolve().parents[1] / "fixtures" / "traces"
PLUS_ONE = "plus one for the final text-only response"


def max_turns_one_evidence():
    return evidence_from_trace(load_trace(TRACES / "max_turns_one.trace.jsonl"), None)


def test_the_runner_copy_of_the_plus_one_sentence_matches_the_library():
    assert terminal_grader.MAX_TURNS_PLUS_ONE == plugin_budget.MAX_TURNS_PLUS_ONE


def test_the_terminal_grader_names_the_plus_one_rule_for_a_turn_limit_run(grader):
    ev = max_turns_one_evidence()
    assert ev.result["subtype"] == "error_max_turns" and ev.result["stop_reason"] == "tool_use"
    got = grade_free(grader("terminal", subtype="error_max_turns", allow_error=True), ev)
    assert got.status == PASSED
    assert PLUS_ONE in got.reason


def test_the_plus_one_note_does_not_change_a_failing_verdict(grader):
    ev = max_turns_one_evidence()
    got = grade_free(grader("terminal", subtype="success"), ev)
    assert got.status == FAILED
    assert "is not one of ['success']" in got.reason and PLUS_ONE in got.reason


def test_a_run_that_completed_gets_no_plus_one_note(grader, evidence):
    ev = evidence(result={"type": "result", "subtype": "success", "is_error": False,
                          "terminal_reason": "completed", "num_turns": 2})
    got = grade_free(grader("terminal", subtype="success"), ev)
    assert got.status == PASSED and PLUS_ONE not in got.reason


# The text of a stream-json `assistant` line as Claude Code 2.1.311+ writes it.
STREAM_LINE = ('{"type": "assistant", "message": {"role": "assistant", "content": '
               '[{"type": "text", "text": "bell\\u0007 zwsp\\u200b del\\u007f nel\\u0085 done"}]}}')
DECODED = "bell\x07 zwsp​ del\x7f nel\x85 done"


def test_escaped_characters_survive_the_capture_and_the_replay_loader(tmp_path):
    line = json.loads(STREAM_LINE)
    text = line["message"]["content"][0]["text"]
    assert text == DECODED
    cap = Capture(run_id="r", case="c")
    cap.add(sdk.AssistantMessage(content=[sdk.TextBlock(text=text)], model="claude-haiku-5-5"))
    assert cap.last_message == DECODED
    trace = tmp_path / "c.trace.jsonl"
    trace.write_text(cap.to_jsonl(), encoding="utf-8")
    events = load_trace(trace)
    assert [e["text"] for e in events if e.get("type") == "assistant_text"] == [DECODED]
    assert evidence_from_trace(events, None).last_message == DECODED
