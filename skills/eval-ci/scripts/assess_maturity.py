#!/usr/bin/env python3
"""Where a project's evaluation practice actually stands, from what is on disk.

Six levels, each defined by something checkable rather than by intent:

    L0  no cases: every judgement is someone reading output and deciding
    L1  cases exist, and have never been run
    L2  the suite has been run at least once through the runner copy
    L3  it runs without anyone remembering: a CI workflow or a pytest gate
    L4  a judged tier repeats each case, so a pass rate exists
    L5  reliability is tracked over time: several result directories, enough
        samples per case for pass@1 to mean something

Most projects sit a level or two below where they believe they are, because
someone ran the agent by hand and it looked right.

**The ladder is not strictly cumulative, on purpose.** `evals/results/` is
gitignored in every sane project, so a repository with a real CI gate usually
shows no local results at all: L3 with no evidence for L2 is the normal state of
a healthy project, not a contradiction. The level reported is the highest one
whose own evidence is present; anything missing below it is listed as an
observation, with the note that a gitignored results directory explains it.

    assess_maturity.py <project> [--json]

Exit codes: 0 always. This is a report, not a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import results as results_lib  # noqa: E402
from agent_sdk_skills.eval_config import load_config, tier_graders  # noqa: E402
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_OK, EXIT_USAGE  # noqa: E402
from agent_sdk_skills.runner_version import inspect_runner_copy  # noqa: E402

#: A step running one of these is running the eval suite.
RUNNER_MARKERS = ("agent_sdk_evals", "run_evals.py", "test_evals.py")
#: Samples per case before a pass@1 figure is worth printing.
PASS_AT_1_SAMPLES = 5

LEVELS: dict[int, tuple[str, str]] = {
    0: ("Vibe checks",
        "Nothing on disk says what the agent should do, so every judgement is "
        "someone reading output and deciding."),
    1: ("Cases exist",
        "The suite states expected behaviour, but no run has been recorded, so "
        "nothing is known about whether it holds."),
    2: ("Run at least once",
        "The suite has actually executed through the runner copy in the "
        "project, so its verdicts are real rather than hypothetical."),
    3: ("Gated automatically",
        "The suite runs without anyone remembering to run it, and a failure "
        "blocks the change."),
    4: ("Judged and repeated",
        "A scheduled tier adds judge graders and repeats each case, so "
        "\"it works\" has a rate attached rather than one lucky verdict."),
    5: ("Reliability tracked",
        "Enough runs exist over time for pass@1 per case to be a measurement, "
        "so regressions in reliability are visible before users find them."),
}

NEXT_STEP = {
    0: "write the first two cases — one happy path, one refusal — with "
       "`/agent-sdk:eval-create`. Until something states the expected behaviour, "
       "nothing else on this ladder is possible.",
    1: "run the cheap tier once and read the results: `/agent-sdk:eval-run` "
       "(`--tier pr`), then `/agent-sdk:eval-analyze`.",
    2: "put the pr tier in CI: `gen_workflows.py <project> --tier pr`, or add the "
       "pytest gate (`assets/templates/test_evals.py.tmpl`) if the project "
       "already runs pytest in CI.",
    3: "add the nightly tier — judge graders and `--runs 3` — with "
       "`gen_workflows.py <project> --tier nightly`, and give the config a "
       "`nightly` tier that lists `judge` (`/agent-sdk:eval-criteria`).",
    4: "let the nightly tier accumulate: three or more result directories with "
       f"at least {PASS_AT_1_SAMPLES} samples per case, then read pass@k with "
       "`/agent-sdk:eval-analyze` (`pass_at_k.py`).",
    5: "keep the loop closed: every production failure becomes a case "
       "(`/agent-sdk:agent-debug` imports the session, `/agent-sdk:eval-create` "
       "turns it into a case), and revisit thresholds as the agent improves.",
}


def gather(project: Path) -> dict[str, Any]:
    layout = detect_layout(project)
    evals = layout.evals
    cases = evals.case_count if evals else 0

    copy = inspect_runner_copy(project / "evals" / "runner")
    config = load_config(project / "evals" / "eval_config.json")
    tiers = sorted(config.tiers) if config.ok else []
    nightly_judges = config.ok and "judge" in tier_graders(config, "nightly")

    run_dirs = results_lib.load_all(project)
    samples = results_lib.samples_by_case(run_dirs)
    max_samples = max((len(v) for v in samples.values()), default=0)
    max_runs_in_one_dir = max(
        (len(case.runs) for run_dir in run_dirs for case in run_dir.cases.values()), default=0)
    pass_at_1 = {
        name: round(sum(1 for s in statuses if s == "PASSED") / len(statuses), 3)
        for name, statuses in samples.items() if statuses
    }

    gating: list[str] = []
    scheduled: list[str] = []
    for name in layout.workflow_files:
        path = Path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(marker in text for marker in RUNNER_MARKERS):
            continue
        gating.append(path.name)
        if "schedule:" in text or "cron:" in text:
            scheduled.append(path.name)

    return {
        "cases": cases,
        "config_tiers": tiers,
        "nightly_lists_judge": nightly_judges,
        "runner_copy": {"present": copy.present, "version": copy.version, "status": copy.status},
        "pytest_gate": layout.pytest_gate,
        "gating_workflows": gating,
        "scheduled_workflows": scheduled,
        "result_dirs": [Path(d.path).name for d in run_dirs],
        "max_samples_per_case": max_samples,
        "max_runs_in_one_dir": max_runs_in_one_dir,
        "pass_at_1": pass_at_1,
    }


def assess(facts: dict[str, Any]) -> tuple[int, dict[int, list[str]]]:
    """The evidence for each level, and the highest level that has any."""
    evidence: dict[int, list[str]] = {level: [] for level in LEVELS}

    if facts["cases"] > 0:
        evidence[1].append(f"{facts['cases']} eval case(s) under evals/")

    if facts["cases"] > 0 and facts["result_dirs"] and facts["runner_copy"]["present"]:
        evidence[2].append(
            f"{len(facts['result_dirs'])} result director(ies) written by the runner copy "
            f"(version {facts['runner_copy']['version']})")

    if facts["cases"] > 0:
        if facts["gating_workflows"]:
            evidence[3].append("workflow(s) running the runner: "
                               + ", ".join(facts["gating_workflows"]))
        if facts["pytest_gate"]:
            evidence[3].append(f"a pytest gate at {Path(facts['pytest_gate']).name}")

    repeated = facts["max_runs_in_one_dir"] >= 3
    if (evidence[3] and facts["nightly_lists_judge"]
            and {"pr", "nightly"} <= set(facts["config_tiers"])
            and (facts["scheduled_workflows"] or repeated)):
        evidence[4].append(
            "both tiers configured, the nightly tier lists judge graders, and "
            + ("a scheduled workflow runs it" if facts["scheduled_workflows"]
               else f"one result directory holds {facts['max_runs_in_one_dir']} runs per case"))

    if len(facts["result_dirs"]) >= 3 and facts["max_samples_per_case"] >= PASS_AT_1_SAMPLES:
        evidence[5].append(
            f"{len(facts['result_dirs'])} result directories and up to "
            f"{facts['max_samples_per_case']} samples per case, so pass@1 is a measurement: "
            + ", ".join(f"{k} {v}" for k, v in sorted(facts["pass_at_1"].items())))

    level = max((index for index, items in evidence.items() if items), default=0)
    return level, evidence


def observations(level: int, facts: dict[str, Any], evidence: dict[int, list[str]]) -> list[str]:
    notes: list[str] = []
    for lower in range(1, level):
        if not evidence[lower]:
            notes.append(f"no evidence for L{lower} ({LEVELS[lower][0]})")
    if level >= 2 and not facts["result_dirs"]:
        notes.append("no results in this checkout, which is expected: `evals/results/` is "
                     "normally gitignored and CI uploads it as an artifact instead")
    if facts["cases"] and not facts["runner_copy"]["present"]:
        notes.append("no runner copy under evals/runner/: nothing here can run the suite "
                     "(install one with /agent-sdk:agent-create)")
    if facts["cases"] and not facts["config_tiers"]:
        notes.append("no tiers in evals/eval_config.json: every run costs whatever the "
                     "default happens to be (/agent-sdk:eval-criteria)")
    if 1 <= facts["max_samples_per_case"] < PASS_AT_1_SAMPLES:
        notes.append(f"{facts['max_samples_per_case']} sample(s) per case is too few to call a "
                     "pass rate reliable")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_USAGE
    layout = detect_layout(target)
    project = Path(layout.project_root or target)

    facts = gather(project)
    level, evidence = assess(facts)
    notes = observations(level, facts, evidence)
    next_level = min(level + 1, 5)

    payload = {
        "project": str(project),
        "level": level,
        "level_name": LEVELS[level][0],
        "level_meaning": LEVELS[level][1],
        "evidence": {str(k): v for k, v in evidence.items() if v},
        "observations": notes,
        "next_level": next_level,
        "next_step": NEXT_STEP[level],
        "facts": facts,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    print(f"# Evaluation maturity: L{level} — {LEVELS[level][0]}")
    print()
    print(LEVELS[level][1])
    print()
    print("| Level | | Evidence here |")
    print("|---|---|---|")
    for index, (name, _) in LEVELS.items():
        mark = "; ".join(evidence[index]) if evidence[index] else ("—" if index else "n/a")
        print(f"| L{index} | {name} | {mark} |")
    if notes:
        print()
        print("## Observations")
        print()
        for note in notes:
            print(f"- {note}")
    print()
    print(f"## Next step{'' if level == 5 else f' (towards L{next_level})'}")
    print()
    print(f"- {NEXT_STEP[level]}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
