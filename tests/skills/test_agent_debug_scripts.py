"""agent-debug reads evidence and never starts a session."""

import json


def test_loop_trace_is_named_with_its_layer(run_script, fixtures):
    result = run_script("skills/agent-debug/scripts/analyze_trace.py", "--trace",
                        fixtures / "traces" / "loop.trace.jsonl", "--json")
    doc = result.json()
    assert result.returncode == 1
    kinds = {s["kind"]: s["layer"] for s in doc["signatures"]}
    assert "loop" in kinds and kinds["loop"] == "tool"
    assert "max_turns" in kinds
    assert "subscription" in doc["cost"]


def test_happy_trace_has_no_signature(run_script, fixtures):
    result = run_script("skills/agent-debug/scripts/analyze_trace.py", "--trace",
                        fixtures / "traces" / "happy.trace.jsonl", "--json")
    assert result.returncode == 0 and result.json()["signatures"] == []


def test_structured_output_call_is_excluded_from_the_path(run_script, fixtures):
    result = run_script("skills/agent-debug/scripts/analyze_trace.py", "--trace",
                        fixtures / "traces" / "structured_output.trace.jsonl", "--json")
    doc = result.json()
    assert "StructuredOutput" in doc["synthetic_calls"]
    assert not any("StructuredOutput" in c for c in doc["calls"])


def test_divergence_is_computed_against_the_case_grader(run_script, fixtures, tmp_path):
    case = tmp_path / "case"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text("---\ncategory: happy\n---\nhi")
    (case / "graders" / "path.md").write_text(
        "---\ntype: trajectory\nmatch: EXACT\nexpected:\n  - tool: mcp__library__lookup_book\n"
        "  - tool: mcp__library__reserve_book\n---\n")
    result = run_script("skills/agent-debug/scripts/analyze_trace.py", "--trace",
                        fixtures / "traces" / "loop.trace.jsonl", "--case-dir", case, "--json")
    doc = result.json()
    assert doc["divergence"]["match"] is False and doc["divergence"]["first_divergence"] == 0
    assert doc["divergence"]["divergence_kind"] in ("wrong_tool", "missing", "extra", "arg_mismatch")


def test_session_import_then_analysis_reports_missing_cost(run_script, fixtures, tmp_path):
    imported = run_script("skills/agent-debug/scripts/import_session.py",
                          fixtures / "sessions" / "one_turn.jsonl", "--out", tmp_path, "--json")
    assert imported.returncode == 0, imported.stderr
    trace = imported.json()["trace"]
    analysed = run_script("skills/agent-debug/scripts/analyze_trace.py", "--trace", trace, "--json").json()
    assert analysed["imported"] is True and analysed["terminal"] is None
    assert "no result event" in analysed["cost"]
    direct = run_script("skills/agent-debug/scripts/analyze_trace.py", "--session",
                        fixtures / "sessions" / "one_turn.jsonl", "--json")
    assert direct.returncode in (0, 1)


def test_unknown_session_id_exits_two(run_script, tmp_path):
    result = run_script("skills/agent-debug/scripts/import_session.py", "no-such-session", "--cwd", tmp_path)
    assert result.returncode == 2 and "looked in" in result.stderr


def test_results_directory_analyses_every_trace(run_script, fixtures, tmp_path):
    results = tmp_path / "evals" / "results" / "20260930T120000"
    results.mkdir(parents=True)
    for name in ("loop", "happy"):
        (results / f"{name}.1.trace.jsonl").write_bytes((fixtures / "traces" / f"{name}.trace.jsonl").read_bytes())
    result = run_script("skills/agent-debug/scripts/analyze_trace.py", "--results", results, "--json")
    docs = result.json()
    assert isinstance(docs, list) and len(docs) == 2 and result.returncode == 1
