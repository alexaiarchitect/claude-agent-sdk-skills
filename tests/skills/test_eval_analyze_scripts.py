"""eval-analyze reads result directories and never re-runs anything."""

import json
from pathlib import Path


def write_run_dir(root: Path, name: str, cases: dict, *, cost=0.01) -> Path:
    """cases: {name: [(status, graders)]} where graders is a list of (name, type, status, reason)."""
    directory = root / "evals" / "results" / name
    directory.mkdir(parents=True)
    totals = {"passed": 0, "failed": 0, "not_evaluated": 0, "cost_usd": 0.0, "cost_basis": "subscription"}
    for case, runs in cases.items():
        records = []
        for index, (status, graders) in enumerate(runs, start=1):
            totals[status.lower()] += 1
            totals["cost_usd"] += cost
            records.append({"run": index, "trace": f"{case}.{index}.trace.jsonl", "status": status,
                            "graders": [{"name": n, "type": t, "status": s, "score": 1.0 if s == "PASSED" else 0.0,
                                         "reason": r} for n, t, s, r in graders],
                            "result": {"subtype": "success", "terminal_reason": "completed", "num_turns": 2,
                                       "duration_ms": 3000, "total_cost_usd": cost,
                                       "usage": {"input_tokens": 5, "output_tokens": 50, "cache_read_input_tokens": 100}}})
        (directory / f"{case}.result.json").write_text(json.dumps({
            "schema": "agent-sdk-skills.result/1", "case": case, "category": "edge",
            "config": {"tier": "nightly", "cost_basis": "subscription"}, "runs": records,
            "summary": {"passed": 0, "failed": 0, "not_evaluated": 0, "pass_rate": 0, "cost_usd": 0}}))
    (directory / "aggregate.json").write_text(json.dumps({
        "schema": "agent-sdk-skills.aggregate/1", "tier": "nightly", "cases": [], "totals": totals,
        "exit_code": 0, "runner_version": "0.1.1", "sdk_version": "0.2.165", "cli_version": "2.1.294",
        "credential": {"kind": "subscription"}}))
    return directory


Q3 = [("path", "no_tool", "FAILED", "reserve_book was called"), ("answer", "llm", "PASSED", "polite refusal")]


def test_summary_places_failures_in_the_quadrant_and_names_causes(run_script, tmp_path):
    write_run_dir(tmp_path, "20260930T120000", {
        "refuse": [("FAILED", Q3)],
        "never": [("NOT_EVALUATED", [("judge", "llm", "NOT_EVALUATED", None)])],
        "fine": [("PASSED", [("ok", "regex", "PASSED", None)])],
    })
    result = run_script("skills/eval-analyze/scripts/summarize_results.py", tmp_path, "--json")
    doc = result.json()
    assert result.returncode == 1
    cases = {c["case"]: c for c in doc["directories"][0]["cases"]}
    assert cases["refuse"]["quadrant"].startswith("Q3")
    assert cases["refuse"]["failed_graders"][0]["reason"] == "reserve_book was called"
    assert "judge" in cases["never"]["not_evaluated_cause"]
    assert doc["efficiency"][0]["cost_basis"] == "subscription"
    text = run_script("skills/eval-analyze/scripts/summarize_results.py", tmp_path)
    assert "estimate" in text.stdout and "Q3" in text.stdout


def test_summary_exit_codes_follow_the_contract(run_script, tmp_path):
    write_run_dir(tmp_path, "20260930T120000", {"a": [("PASSED", [("ok", "regex", "PASSED", None)])]})
    assert run_script("skills/eval-analyze/scripts/summarize_results.py", tmp_path).returncode == 0
    write_run_dir(tmp_path / "n", "20260930T120000", {"a": [("NOT_EVALUATED", [("j", "llm", "NOT_EVALUATED", None)])]})
    assert run_script("skills/eval-analyze/scripts/summarize_results.py", tmp_path / "n").returncode == 3
    assert run_script("skills/eval-analyze/scripts/summarize_results.py", tmp_path / "nothing").returncode == 2


def test_pass_at_k_across_directories_and_inner_runs(run_script, tmp_path):
    ok = [("ok", "regex", "PASSED", None)]
    bad = [("ok", "regex", "FAILED", "no match")]
    write_run_dir(tmp_path, "20260930T120000", {"a": [("PASSED", ok), ("FAILED", bad), ("PASSED", ok)]})
    write_run_dir(tmp_path, "20260930T130000", {"a": [("PASSED", ok)], "b": [("PASSED", ok)]})
    result = run_script("skills/eval-analyze/scripts/pass_at_k.py", tmp_path, "--json")
    doc = result.json()
    a = next(c for c in doc["cases"] if c["case"] == "a")
    assert a["runs"] == 4 and a["passes"] == 3 and a["flaky"]
    assert result.returncode == 1, "a is not reliable"
    assert "missing from some runs" in doc["warning"]
    md = run_script("skills/eval-analyze/scripts/pass_at_k.py", tmp_path, "--k", "1,3")
    assert "pass@3" in md.stdout and "Flaky" in md.stdout


def test_calibration_sample_prefers_judged_runs_and_is_reproducible(run_script, tmp_path):
    write_run_dir(tmp_path, "20260930T120000", {
        "judged": [("PASSED", [("j", "llm", "PASSED", "fine")])],
        "plain": [("PASSED", [("r", "regex", "PASSED", None)])],
        "failed": [("FAILED", [("r", "regex", "FAILED", "x")])],
    })
    first = run_script("skills/eval-analyze/scripts/calibration_sample.py", tmp_path, "--n", "1", "--seed", "3", "--json").json()
    second = run_script("skills/eval-analyze/scripts/calibration_sample.py", tmp_path, "--n", "1", "--seed", "3", "--json").json()
    assert first == second and first["sample"][0]["case"] == "judged" and first["pool"] == 2
