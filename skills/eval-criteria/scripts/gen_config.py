#!/usr/bin/env python3
"""Write `evals/eval_config.json`: the decisions that apply to every case.

Five of them, and each has a default that is a decision rather than a habit:

* **`model`** is written as `${CLAUDE_MODEL:-<default>}`, not as a literal id.
  A literal goes stale when a model retires; the env form lets a case, a shell
  or a CI matrix override it without editing the file, and still refuses to
  inherit Claude Code's own default — which is a different model on different
  machines and measured four times Sonnet's cost on this account.
* **`isolation`** is `setting_sources: []` and `strict_mcp_config: true`. With
  ambient settings loaded the same case measured 17x the cost and describes the
  machine it ran on rather than the agent.
* **`judge`** carries the model, `samples` and the vote. An odd `samples` on
  purpose: majority voting over an even number can tie.
* **`tiers`** are `pr` (free graders, one run, threshold 1.0) and `nightly`
  (judges too, repeated runs, threshold 0.8 with pass@k). The split exists
  because no single tier can be cheap enough for every pull request and
  thorough enough to trust for a release.
* **`budget`** caps per run and in total, with `on_not_evaluated: warn` so a
  usage limit reads as inconclusive rather than as a regression.

    gen_config.py <project> [--model M] [--judge-model M] [--samples N]
                  [--pr-threshold X] [--nightly-runs N]
                  [--force] [--dry-run] [--json]

Exit codes: 0 written or planned, 1 the generated config has warnings or errors
(it is validated before it is offered), 2 usage error. Informational notes are
printed and do not change the exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agent_sdk_skills import DEFAULT_JUDGE_MODEL, DEFAULT_MODEL, MODEL_ENV_VAR  # noqa: E402
from agent_sdk_skills.eval_config import (  # noqa: E402
    CONFIG_NAME, LoadedConfig, default_config, validate_config,
)
from agent_sdk_skills.layout import detect_layout  # noqa: E402
from agent_sdk_skills.report import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, GapReport  # noqa: E402
from agent_sdk_skills.runner_version import inspect_runner_copy  # noqa: E402
from agent_sdk_skills.templating import WritePlan, dumps_json  # noqa: E402


def build_config(*, model: str | None, judge_model: str | None, samples: int | None,
                 pr_threshold: float | None, nightly_runs: int | None,
                 agent: str, runner_version: str | None) -> dict:
    config = default_config(model=model, judge_model=judge_model,
                            runner_version=runner_version, agent=agent)
    if samples is not None:
        config["judge"]["samples"] = samples
    if pr_threshold is not None:
        config["tiers"]["pr"]["threshold"] = pr_threshold
    if nightly_runs is not None:
        config["tiers"]["nightly"]["runs"] = nightly_runs
        config["tiers"]["nightly"]["pass_k"] = min(
            config["tiers"]["nightly"].get("pass_k", 3), nightly_runs)
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--model", help=f"agent model (default ${{{MODEL_ENV_VAR}:-{DEFAULT_MODEL}}})")
    parser.add_argument("--judge-model", help=f"judge model (default {DEFAULT_JUDGE_MODEL})")
    parser.add_argument("--samples", type=int, help="judge samples per grader; keep it odd")
    parser.add_argument("--pr-threshold", type=float, help="pass rate the pr tier requires")
    parser.add_argument("--nightly-runs", type=int, help="runs per case in the nightly tier")
    parser.add_argument("--force", action="store_true", help="replace an existing config")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.project).expanduser()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    layout = detect_layout(target)
    project = Path(layout.project_root or target)
    path = project / "evals" / CONFIG_NAME

    copy = inspect_runner_copy(project / "evals" / "runner")
    config = build_config(
        model=args.model, judge_model=args.judge_model, samples=args.samples,
        pr_threshold=args.pr_threshold, nightly_runs=args.nightly_runs,
        agent=layout.entry_spec or "agent:build_options",
        runner_version=copy.version)

    # Validate what is about to be written, not what was written last time: a
    # generator that can produce a config its own validator rejects is a bug,
    # and `--samples 2` or a retiring `--judge-model` reaches that state.
    findings = validate_config(
        LoadedConfig(path=str(path), data=config, exists=True),
        runner_copy_version=copy.version)

    plan = WritePlan()
    plan.add(path, dumps_json(config), force=args.force,
             reason="pins the model, the isolation defaults, the judge and the two tiers")
    written = [] if args.dry_run else plan.apply()

    report = GapReport(subject=str(path), skill="eval-criteria")
    report.extend(findings)
    report.discovered = {
        "model": config["model"],
        "judge": f"{config['judge']['model']} x{config['judge']['samples']} ({config['judge']['vote']})",
        "agent": config["agent"],
        "runner_version": config["runner_version"],
        "tiers": {name: f"{', '.join(t['graders'])}; runs={t['runs']}; threshold={t['threshold']}"
                  for name, t in config["tiers"].items()},
    }

    payload = {"project": str(project), "path": str(path), "config": config,
               "dry_run": args.dry_run, "plan": plan.to_dict(), "written": written,
               "findings": [f.to_dict() for f in findings]}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(report.to_md())
        print()
        print(plan.to_md())
        print("\n_Dry run: nothing was written._" if args.dry_run
              else f"\n_Wrote {len(written)} file(s)._")
        if any(i.action == "skip" for i in plan.items):
            print("\n- the config already exists and was left alone; pass --force to replace it, "
                  "or edit the keys you want changed rather than regenerating")
    # Info-level notes (the judge sharing the agent's model, say) are worth
    # printing and not worth an exit code: the default config produces one.
    actionable = [f for f in findings if f.severity in ("error", "warn")]
    return EXIT_FINDINGS if actionable else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
