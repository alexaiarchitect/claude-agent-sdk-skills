# `agent_sdk_evals`

The eval runner for Claude Agent SDK agents. **This directory is a managed copy.**

## What it is

A stdlib-plus-`claude-agent-sdk` package that runs the cases in an `evals/`
directory against your agent, captures every SDK message as a trace, grades the
traces, and writes results. It is the only part of the `agent-sdk` plugin that
imports the SDK; everything on the plugin side is static analysis.

## How it is invoked

```
python -m agent_sdk_evals run <evals-dir> [--case glob] [--tag t] [--runs n]
        [--tier pr|nightly|free|run|judge] [--json] [--dry-run] [--max-cost-usd x]
        [--concurrency n] [--wait-for-reset] [--keep-cwd] [--out dir]
python -m agent_sdk_evals list-tools [<evals-dir>] [--agent module:function] [--probe]
python -m agent_sdk_evals replay <trace> [--case-dir <evals/case>] --graders-only
python -m agent_sdk_evals version
python -m agent_sdk_evals whoami
```

Run it from the project root with `evals/runner` and the project on `PYTHONPATH`,
in an interpreter that has `claude-agent-sdk` installed. The plugin's `eval-run`
skill does this for you.

Every subcommand prints **one JSON object as its last stdout line**; anything
readable comes before it. The exit code is the gate:

| code | meaning |
|---|---|
| 0 | every case at or above its tier threshold |
| 1 | a case below threshold |
| 2 | usage, import, backend or runner-version error |
| 3 | inconclusive: only NOT_EVALUATED results, a cost ceiling hit, or a rejected rate limit |

Start with `--dry-run`. It resolves the config, the cases, the agent entry, the
model, the isolation and the credential, refuses anything invalid, prints what
*would* run, and exits 0 having started nothing. It also reports
`sessions_total` — the sum of the per-case runs, one session per run whatever
the turn count — because a case's own `runs:` outranks the tier's, so the
number of sessions is not `cases x tier.runs`.

## Four things worth knowing before you trust a number

- **Isolation is forced.** Every run gets `setting_sources=[]` and
  `strict_mcp_config=True` unless a case overrides them. Without those, the
  machine's own settings and CLAUDE.md load into every run: measured 17x the
  cost for the same prompt, and results that do not reproduce elsewhere.
- **The model never defaults.** A case override, then `eval_config.json`'s
  `model` (which reads `${CLAUDE_MODEL:-…}`), then the agent's own options — and
  if all three are empty the runner refuses rather than inheriting the CLI's
  default model, which is a different, more expensive model.
- **On a subscription the dollar figures are estimates.** `total_cost_usd` is a
  client-side calculation from a bundled price table; what a run really spends is
  plan quota. `whoami` says which basis you are on. A `rejected` rate limit marks
  runs NOT_EVALUATED and exits 3 — never a fabricated failure. An
  `allowed_warning` is recorded and the suite keeps going. The cost is also not
  all the agent's: the trace's `models_billed` lists every model in
  `model_usage`, and the CLI bills its own background work to a cheap model
  nobody asked for (measured `claude-haiku-5-5` on CLI 2.1.294, 2.1.301 and
  2.1.310).
- **The permission mode is decided, never inherited.** An agent that leaves
  `permission_mode` unset gets `dontAsk`, and the trace `init` event says who
  chose it (`permission_mode_source`: `"agent"` or `"runner-default"`). Left
  unset, the mode is whatever the CLI picks. The docs say so since 2.1.302:
  "In Claude Code v2.1.302 or later, `claude -p` and Agent SDK runs with no
  permission mode set start in Manual mode" (`default`; measured on 2.1.310),
  and "Before v2.1.302, these runs could start in auto mode if they didn't
  fetch feature flags" ([permission modes](https://code.claude.com/docs/en/permission-modes#which-mode-a-non-interactive-run-starts-in)).
  Measured on CLI 2.1.285–2.1.301: a headless session that fetches feature
  flags starts in `default`; one that does not (third-party provider, telemetry
  off, first run after an install or upgrade) starts in `auto`, where a
  classifier reviews each tool call and a bare allow rule no longer settles it.
  The runner forces `dontAsk` either way. `--dry-run` prints the resolved mode and its
  source for every case.

## This is a copy

The source of truth is `runner/agent_sdk_evals/` in the `agent-sdk` plugin. The
plugin stamps `VERSION` and a `MANIFEST.sha256` when it installs this copy, and
warns when the two drift. Edit it here and the next upgrade will notice; send the
change upstream instead.

`frontmatter.py` in particular is a **verbatim** copy of the plugin's module — a
test on both sides asserts the two files are byte-identical.
