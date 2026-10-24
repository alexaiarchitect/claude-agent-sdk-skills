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
| `--runs N` | runs per case; each run is recorded separately. Narrowest of four sources (see below) |
| `--case GLOB`, `--tag T` | select cases by name or tag |
| `--out DIR` | results directory (default `evals/results/<timestamp>/`) |
| `--max-cost-usd X` | stop launching runs when the estimated total crosses X; partial results, exit 3 |
| `--concurrency N` | parallel runs, 1 by default: every run is a CLI child on the same credential |
| `--wait-for-reset` | on a `rejected` rate-limit status, sleep until `resets_at` once and retry the pending runs |
| `--dry-run` | print the plan (cases, per-case runs and their source, `sessions_total`, model, isolation, credential) and start nothing |
| `--keep-cwd` | keep each run's temporary working directory for inspection |
| `--json` | machine-readable output |

## How many sessions a run starts

`runs` is resolved narrowest-first, and the first of these that is set wins:

1. `--runs N` on the command line;
2. the case's own `runs:` in `prompt.md`;
3. the tier's `runs` in `eval_config.json`;
4. 1.

A case may therefore pin its own repetition and outrank the tier — that is the
design: a flaky edge case is worth three runs on a tier that gives everything
else one. The arithmetic that follows is the part worth saying out loud:

> **sessions = the sum of the per-case runs**, one session per run, whatever the
> turn count. A scripted multi-turn case (`turns:`) or a `simulated_user` case
> replays its turns inside the *one* session, so it costs one session per run
> like any other case.

It is **not** `cases x tier.runs`. The worked example in
`tests/fixtures/agents/good/evals` has five cases and a `pr` tier at `runs: 1`,
but three of them pin `runs: 3`, so `pr` starts 3 + 3 + 3 + 1 + 1 = **11**
sessions. `--dry-run` reports that as `sessions_total: 11` in the JSON, with
per-case `runs`, `runs_source` (`"cli"`, `"case"`, `"tier"` or `"default"`) and
`sessions`, and prints `sessions: 11 (3 cases pin runs: 3)` in the prose. The
plugin's `run_evals.py --dry-run` reports the same `sessions_total` from the
case files, before the runner is even reached.

## What a run applies to the agent's options

1. the agent's own `build_options()` (or the entry named by `eval_config.json`,
   the case, or `AGENT_ENTRY`);
2. isolation defaults `setting_sources=[]`, `strict_mcp_config=True`, and
   `permission_mode="dontAsk"` when the agent left the mode unset — recorded in
   the trace `init` event as `permission_mode_source: "runner-default"` (or
   `"agent"` when the agent set it). The runner resolves the mode itself because
   the CLI's choice varies: a session that fetches feature flags starts in
   `default`, but on Claude Code 2.1.285–2.1.301 one that fetches none (gateway,
   telemetry off, first run after an upgrade) starts in `auto`, where broad allow
   rules are dropped, and 2.1.302 starts those in `default` again; an explicit
   mode in the options or in a case's `overrides` always wins;
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

Sources: this plugin's `runner/agent_sdk_evals/cli.py` and `.dev/CONTRACTS.md`
(§13.1 for the forced `dontAsk` and `permission_mode_source`);
SDK behaviour per `https://code.claude.com/docs/en/agent-sdk/python` (`query`,
`ClaudeSDKClient`, `ClaudeAgentOptions`),
`https://code.claude.com/docs/en/agent-sdk/configuration` (model selection,
`setting_sources`) and
`https://code.claude.com/docs/en/permission-modes#which-mode-a-non-interactive-run-starts-in`
(`default` from v2.1.302; "Before v2.1.302, these runs could start in auto mode
if they didn't fetch feature flags"), with
`https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md` for the
2.1.302 change. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs; the `runs` precedence and
the session arithmetic re-checked 2026-10-13 against `cli.py`; re-read
2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs.
