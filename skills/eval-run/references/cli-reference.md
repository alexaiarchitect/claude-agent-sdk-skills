# The runner's command line

The runner copy in `evals/runner/agent_sdk_evals` is invoked as
`python -m agent_sdk_evals <subcommand>` with `evals/runner` and the project
root on `PYTHONPATH`; the plugin's `run_evals.py` builds exactly that command
and prints it under `--dry-run`. Every subcommand prints a human summary and,
as its last stdout line, one JSON object.

## Subcommands

| Subcommand | Does | Spends |
|---|---|---|
| `run <evals-dir>` | runs cases of a tier, writes `results/<timestamp>/` | sessions, and judge calls for `llm` graders in the tier |
| `replay <trace> --graders-only` | re-grades a saved trace with the free graders | nothing (`--judge` adds judge calls) |
| `list-tools` | builds the agent's options and lists the tools it would have | nothing (imports the agent, starts no session) |
| `whoami` | the credential kind the subprocess will inherit, plan type, SDK and CLI versions | nothing |
| `version` | runner version and SDK version | nothing |

## `run` flags

| Flag | Meaning |
|---|---|
| `--tier pr\|nightly\|free\|run\|judge` | a named tier from `eval_config.json`, or a grader tier: `free` skips `llm` graders, `judge` includes them |
| `--runs N` | runs per case; each run is recorded separately (default from the tier) |
| `--case GLOB`, `--tag T` | select cases by name or tag |
| `--out DIR` | results directory (default `evals/results/<timestamp>/`) |
| `--max-cost-usd X` | stop launching runs when the estimated total crosses X; partial results, exit 3 |
| `--concurrency N` | parallel runs, 1 by default: every run is a CLI child on the same credential |
| `--wait-for-reset` | on a `rejected` rate-limit status, sleep until `resets_at` once and retry the pending runs |
| `--dry-run` | print the plan (cases, model, isolation, credential) and start nothing |
| `--keep-cwd` | keep each run's temporary working directory for inspection |
| `--json` | machine-readable output |

## What a run applies to the agent's options

1. the agent's own `build_options()` (or the entry named by `eval_config.json`,
   the case, or `AGENT_ENTRY`);
2. isolation defaults `setting_sources=[]`, `strict_mcp_config=True`;
3. the model: case override, then config `model` (with `${CLAUDE_MODEL:-...}`
   expansion), then the agent's own; none of these set means a refusal;
4. the case's `overrides`, validated by name before anything starts;
5. mocked servers replacing the named `mcp_servers` entries;
6. the capture hook (and fault hooks when the case names a faults file);
7. `cwd` set to a fresh temporary directory where `scaffold_script` has run.

## Output files

`<case>.<n>.trace.jsonl` per run, `<case>.result.json` per case,
`aggregate.json` per invocation; shapes in `/agent-sdk:eval-analyze`'s
[result-schema.md](../../eval-analyze/references/result-schema.md).

---

Sources: this plugin's `runner/agent_sdk_evals/cli.py` and `.dev/CONTRACTS.md`;
SDK behaviour per `https://code.claude.com/docs/en/agent-sdk/python` (`query`,
`ClaudeSDKClient`, `ClaudeAgentOptions`) and
`https://code.claude.com/docs/en/agent-sdk/configuration` (model selection,
`setting_sources`).
