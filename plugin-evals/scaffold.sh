#!/usr/bin/env bash
# Prepare the eval session's working directory.
#
#   scaffold.sh [<fixture>|none] [<mutation>] [stage-results[=<dirs>]] [stage-traces] [stage-sessions]
#
# Fixtures live in tests/fixtures/agents/ and use a library-reservations domain,
# so a case can exercise a real project without touching the repository. `none`
# copies no project, for cases that only need staged data.
#
# A mutation plants a specific defect, for cases whose prompt describes one:
#   bad-override     an eval case whose `overrides` names an option that does not exist
#   retiring-judge   an eval_config.json whose judge model is retiring
#   stale-runner     a runner copy stamped with an old VERSION
#
# Staging directives copy read-only fixture data into the sandbox, so a prompt
# can use a sandbox-relative path instead of reaching back into the plugin:
#   stage-results    tests/fixtures/results  -> ./fixtures/results
#   stage-traces     tests/fixtures/traces   -> ./fixtures/traces
#   stage-sessions   tests/fixtures/sessions -> ./fixtures/sessions
#
# `stage-results` takes an optional comma-separated selector naming which run
# directories to copy, e.g. `stage-results=failure_only,import_failed`; with no
# selector every directory is staged, as before. Staging all four at once makes
# "the last run" ambiguous (their timestamps are identical) and makes
# `pass_at_k.py` pool unrelated series, so a case that asks about one run should
# name the one it means.
#
# It also writes ./.scaffold/ for a human: manifest.txt records what ran,
# protected.sha256 records the checksum of every file a case must not modify.
# No grader reads either one — `file_exists` counts only files Claude created
# during a run, so a file this script writes is invisible to it. Inspect them
# yourself with `claude plugin eval --keep-temp`; the "nothing was clobbered"
# assertion lives in the regex-over-the-trace graders beside each case.
#
# Requires `claude plugin eval --scaffold`; scaffold scripts are opt-in.
set -euo pipefail

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fixture=""
mutation=""
stage_results=0
stage_results_only=""
stage_traces=0
stage_sessions=0

for arg in "$@"; do
  case "${arg}" in
    stage-results)  stage_results=1 ;;
    stage-results=*) stage_results=1; stage_results_only="${arg#stage-results=}" ;;
    stage-traces)   stage_traces=1 ;;
    stage-sessions) stage_sessions=1 ;;
    *)
      if [[ -z "${fixture}" ]]; then
        fixture="${arg}"
      elif [[ -z "${mutation}" ]]; then
        mutation="${arg}"
      else
        echo "unexpected argument: ${arg}" >&2
        exit 2
      fi
      ;;
  esac
done

fixture="${fixture:-good}"
mutation="${mutation:-none}"

if [[ "${fixture}" != "none" ]]; then
  source_dir="${plugin_root}/tests/fixtures/agents/${fixture}"
  if [[ ! -d "${source_dir}" ]]; then
    echo "no such fixture project: ${fixture}" >&2
    exit 2
  fi
  cp -R "${source_dir}/." .
  # A runner copy, so run/dry-run paths resolve; results stay out of the repo.
  if [[ -d "${plugin_root}/runner/agent_sdk_evals" && ! -d ./evals/runner/agent_sdk_evals ]]; then
    mkdir -p ./evals/runner
    cp -R "${plugin_root}/runner/agent_sdk_evals" ./evals/runner/
  fi
fi

case "${mutation}" in
  none) ;;
  bad-override)
    python3 - <<'PY'
import pathlib
case = pathlib.Path("evals/refuse-double-booking/prompt.md")
text = case.read_text()
text = text.replace("overrides:\n", "overrides:\n  permision_mode: dontAsk\n", 1) if "overrides:\n" in text \
    else text.replace("---\n", "---\noverrides:\n  permision_mode: dontAsk\n", 1)
case.write_text(text)
PY
    ;;
  retiring-judge)
    # claude-haiku-4-5-20251001 on purpose, and still correct as of 2026-10-11:
    # its retirement is "not sooner than 2026-10-15", so the plugin grades it
    # `retiring` and CFG010/CFG011 fire. Do NOT modernise this to Haiku 5.5 —
    # that id is `current`, the finding would not fire, and the case would pass
    # for the wrong reason. When Haiku 4.5 finally retires, swap it for whatever
    # the deprecations page then lists as retiring-eligible, not for a current
    # id. (claude-sonnet-4-5-20250929 is the obvious successor: deprecated
    # 2026-09-30, retires 2026-11-30, graded `deprecated` and treated like
    # `retiring` by every consumer.)
    python3 - <<'PY'
import json, pathlib
path = pathlib.Path("evals/eval_config.json")
doc = json.loads(path.read_text())
doc.setdefault("judge", {})["model"] = "claude-haiku-4-5-20251001"
path.write_text(json.dumps(doc, indent=2) + "\n")
PY
    ;;
  stale-runner)
    printf '0.0.1\n' > evals/runner/agent_sdk_evals/VERSION
    ;;
  *)
    echo "unknown mutation: ${mutation}" >&2
    exit 2
    ;;
esac

staged=""
if [[ "${stage_results}" -eq 1 ]]; then
  mkdir -p ./fixtures/results
  if [[ -z "${stage_results_only}" ]]; then
    cp -R "${plugin_root}/tests/fixtures/results/." ./fixtures/results/
    staged="${staged} results"
  else
    IFS=',' read -r -a wanted <<< "${stage_results_only}"
    for name in "${wanted[@]}"; do
      [[ -z "${name}" ]] && continue
      run_dir="${plugin_root}/tests/fixtures/results/${name}"
      if [[ ! -d "${run_dir}" ]]; then
        echo "no such results fixture: ${name}" >&2
        exit 2
      fi
      cp -R "${run_dir}" ./fixtures/results/
    done
    staged="${staged} results(${stage_results_only})"
  fi
fi
if [[ "${stage_traces}" -eq 1 ]]; then
  mkdir -p ./fixtures/traces
  cp -R "${plugin_root}/tests/fixtures/traces/." ./fixtures/traces/
  staged="${staged} traces"
fi
if [[ "${stage_sessions}" -eq 1 ]]; then
  mkdir -p ./fixtures/sessions
  cp -R "${plugin_root}/tests/fixtures/sessions/." ./fixtures/sessions/
  staged="${staged} sessions"
fi

mkdir -p .scaffold
{
  echo "fixture=${fixture}"
  echo "mutation=${mutation}"
  echo "staged=${staged# }"
} > .scaffold/manifest.txt

: > .scaffold/protected.sha256
for protected in agent.py evals/eval_config.json evals/refuse-double-booking/prompt.md evals/reserve-available/prompt.md; do
  if [[ -f "${protected}" ]]; then
    python3 - "${protected}" >> .scaffold/protected.sha256 <<'PY'
import hashlib, sys
path = sys.argv[1]
print(f"{hashlib.sha256(open(path, 'rb').read()).hexdigest()}  {path}")
PY
  fi
done

echo "scaffolded ${fixture} (mutation: ${mutation}; staged:${staged:-" none"}) into $(pwd)"
