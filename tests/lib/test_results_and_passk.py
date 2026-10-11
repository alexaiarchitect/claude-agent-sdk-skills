"""Result files are read by schema; reliability is computed from statuses, never averaged."""

import json
from pathlib import Path

from agent_sdk_skills.passk import aggregate, classify, pass_at_k, pass_power_k
from agent_sdk_skills.results import (
    efficiency_rows, find_run_dirs, latest, load_all, not_evaluated_cause, parse_result,
    samples_by_case, suite_runs,
)


def write_run_dir(root: Path, name: str, statuses: dict[str, list[str]], *, cost=0.01, tier="pr") -> Path:
    directory = root / "evals" / "results" / name
    directory.mkdir(parents=True)
    totals = {"passed": 0, "failed": 0, "not_evaluated": 0, "cost_usd": 0.0, "cost_basis": "subscription"}
    for case, runs in statuses.items():
        records = []
        for index, status in enumerate(runs, start=1):
            totals[status.lower()] = totals.get(status.lower(), 0) + 1
            totals["cost_usd"] += cost
            graders = [{"name": "criteria", "type": "llm" if status == "NOT_EVALUATED" else "regex",
                        "status": status, "score": 1.0 if status == "PASSED" else 0.0}]
            records.append({"run": index, "trace": f"{case}.{index}.trace.jsonl", "status": status,
                            "graders": graders,
                            "result": {"subtype": "success", "terminal_reason": "completed", "num_turns": 3,
                                       "duration_ms": 4000, "total_cost_usd": cost, "cost_delta_usd": cost,
                                       "usage": {"input_tokens": 10, "output_tokens": 200,
                                                 "cache_read_input_tokens": 4000}}})
        (directory / f"{case}.result.json").write_text(json.dumps({
            "schema": "agent-sdk-skills.result/1", "case": case, "category": "happy",
            "config": {"tier": tier, "cost_basis": "subscription"}, "runs": records,
            "summary": {"passed": runs.count("PASSED"), "failed": runs.count("FAILED"),
                        "not_evaluated": runs.count("NOT_EVALUATED"), "pass_rate": runs.count("PASSED") / len(runs),
                        "cost_usd": cost * len(runs)},
        }))
    (directory / "aggregate.json").write_text(json.dumps({
        "schema": "agent-sdk-skills.aggregate/1", "tier": tier, "started": name, "finished": name,
        "cases": [], "totals": totals, "exit_code": 1 if totals["failed"] else 0,
        "runner_version": "0.1.2", "sdk_version": "0.2.165", "cli_version": "2.1.294",
        "credential": {"kind": "subscription", "subscription_type": "max"},
    }))
    return directory


def test_results_are_read_by_schema_and_statuses_kept_apart(tmp_path):
    write_run_dir(tmp_path, "20260930T120000", {"a": ["PASSED"], "b": ["FAILED"], "c": ["NOT_EVALUATED"]})
    run = latest(tmp_path)
    assert run is not None and run.aggregate and run.aggregate.ok
    assert run.status_counts() == {"PASSED": 1, "FAILED": 1, "NOT_EVALUATED": 0 + 1, "INFORMATIONAL": 0}
    assert not run.is_clean
    assert run.aggregate.cost_basis == "subscription" and run.aggregate.cli_version == "2.1.294"
    assert "judge" in not_evaluated_cause(run.cases["c"].runs[0])


def test_unknown_schema_is_an_error_not_a_crash(tmp_path):
    bad = tmp_path / "x.result.json"
    bad.write_text(json.dumps({"schema": "something/9", "case": "x"}))
    parsed = parse_result(bad)
    assert not parsed.ok and "unknown schema" in parsed.error
    broken = tmp_path / "y.result.json"
    broken.write_text("{not json")
    assert "invalid JSON" in parse_result(broken).error


def test_results_root_accepts_project_evals_results_or_one_run(tmp_path):
    directory = write_run_dir(tmp_path, "20260930T120000", {"a": ["PASSED"]})
    assert find_run_dirs(tmp_path) == [directory]
    assert find_run_dirs(tmp_path / "evals") == [directory]
    assert find_run_dirs(tmp_path / "evals" / "results") == [directory]
    assert find_run_dirs(directory) == [directory]
    assert find_run_dirs(tmp_path / "nowhere") == []


def test_samples_combine_inner_runs_and_separate_directories(tmp_path):
    write_run_dir(tmp_path, "20260930T120000", {"a": ["PASSED", "FAILED", "PASSED"]})
    write_run_dir(tmp_path, "20260930T130000", {"a": ["PASSED"]})
    runs = load_all(tmp_path)
    assert samples_by_case(runs) == {"a": ["PASSED", "FAILED", "PASSED", "PASSED"]}
    assert len(suite_runs(runs)) == 4


def test_pass_at_k_is_unbiased_and_pass_power_k_is_strict():
    assert pass_at_k(5, 5, 1) == 1.0 and pass_at_k(5, 0, 3) == 0.0
    assert abs(pass_at_k(5, 2, 1) - 0.4) < 1e-9
    assert abs(pass_at_k(5, 2, 3) - 0.9) < 1e-9, "1 - C(3,3)/C(5,3) = 0.9"
    assert abs(pass_power_k(0.8, 3) - 0.512) < 1e-9
    assert classify(0.96) == "RELIABLE" and classify(0.8) == "MARGINAL" and classify(0.4) == "UNRELIABLE"


def test_aggregate_reports_fragility_flakiness_and_missing_runs():
    report = aggregate([
        {"a": "PASSED", "b": "PASSED"}, {"a": "FAILED", "b": "PASSED"},
        {"a": "PASSED", "b": "PASSED"}, {"a": "PASSED", "b": "NOT_EVALUATED"}, {"a": "PASSED"},
    ], ks=(1, 3, 5), suite="library")
    doc = report.to_dict()
    a = next(c for c in report.cases if c.case == "a")
    assert a.flaky and a.passes == 4 and a.runs == 5 and a.fragility > 0
    assert report.perfect_runs == 3
    assert "missing from some runs" in report.warning
    assert doc["suite_pass_at"]["1"] == 0.6
    md = report.to_md()
    assert "Flaky case(s)" in md and "never-evaluated" in md


def test_efficiency_rows_are_means_sorted_by_cost(tmp_path):
    write_run_dir(tmp_path, "20260930T120000", {"cheap": ["PASSED"], "dear": ["PASSED", "PASSED"]}, cost=0.02)
    rows = efficiency_rows(load_all(tmp_path))
    assert [r["case"] for r in rows] == ["cheap", "dear"] or rows[0]["mean_cost_usd"] >= rows[1]["mean_cost_usd"]
    assert rows[0]["mean_turns"] == 3.0 and rows[0]["cost_basis"] == "subscription"
