# Capability map

Thirteen skills. The router (`/agent-sdk:agent-sdk`) picks one; each does its
own discovery, so any of them can also be invoked directly.

## Agent side

| Skill | Use it to | Reads | Writes | Cost |
|---|---|---|---|---|
| `/agent-sdk:agent-create` | make an app eval-ready: `evals/`, config, runner copy, `.env.example`, pytest gate; hand off to `/agent-sdk-dev:new-sdk-app` for a bare app | your answers, the existing app | evals scaffolding, never the app itself | free |
| `/agent-sdk:agent-review` | review agent code: entry point, options, model policy, secrets, legacy SDK names | agent source (statically, never imported) | nothing, unless you approve fixes | free |
| `/agent-sdk:agent-debug` | triage a looping, stalling or flaky agent from a trace or a Claude Code session file | `*.trace.jsonl`, `~/.claude/projects/*/*.jsonl`, results | an imported trace, optionally | free (a fresh run is `run`) |
| `/agent-sdk:agent-harness` | design and lint hooks, permissions, MCP servers, subagents, `setting_sources` | agent source, `.claude/`, `.mcp.json` | hook or agent files on approval | free |
| `/agent-sdk:agent-deploy` | check hosting readiness: credentials, isolation, limits, telemetry | agent source, settings | Dockerfile or settings on approval | free |

## Evaluation side

| Skill | Use it to | Reads | Writes | Cost |
|---|---|---|---|---|
| `/agent-sdk:eval-create` | write cases by category, turn a trace into a trajectory grader, manage cases | agent tools and prompt, existing cases, traces | `evals/<case>/` | free |
| `/agent-sdk:eval-criteria` | pick graders and budgets, write rubrics, set judge and tiers | agent tools, existing config | `evals/eval_config.json`, grader files | free to write |
| `/agent-sdk:eval-review` | validate cases and config, cross-check tool names, measure coverage | eval files plus agent source | nothing | free |
| `/agent-sdk:eval-run` | run a tier honestly through the project's runner copy; repeat for pass@k | cases, config, runner | `evals/results/<timestamp>/` | run / judge |
| `/agent-sdk:eval-analyze` | explain results: quadrant, first divergence, reliability, efficiency | result and trace files | nothing | free |
| `/agent-sdk:eval-simulation` | simulated users with personas, mocked MCP tools, hook fault injection | agent tools, existing cases | mocks, personas, faults | free to write; simulated users cost `judge` |
| `/agent-sdk:eval-ci` | a plain workflow step that gates on the runner's exit code; maturity | repo layout, config, workflows | `.github/workflows/`, `tests/test_evals.py` | free to write |

## Cost tiers

- **free** — deterministic. No SDK session, no judge call. Static review,
  validation, coverage, replaying a saved trace through the free graders.
- **run** — executes the agent. One SDK session per case per run; subagents
  add turns. Paid by whatever credential the subprocess inherits: an API key
  bills the API, a subscription login or token draws on the plan's usage
  limits (and `total_cost_usd` is then an estimate), a provider switch bills
  that cloud.
- **judge** — adds LLM-as-judge calls: one per `llm` grader per sample, made
  through the SDK with the configured judge model, so the same credential
  pays for them.

The `pr` tier in a generated config uses free graders only, so a per-change
gate never needs a judge. The `nightly` tier adds judges and repeated runs.

`claude plugin eval` — the command that scores *a plugin*, not an agent — is a
separate cost tier again, and two things about it changed upstream. Its
`--judge-model` default is now **"the model Claude Code uses for background
tasks"**, which is not a fixed id, so pin it with
`--judge-model claude-sonnet-5-5` whenever a score has to be comparable with an
earlier one. The two fixes this plugin's own suite depends on landed in
Claude Code **2.1.289** and **2.1.293**, so treat **2.1.293** as the floor for
running `plugin eval`; from **2.1.299** a run that ends on an API error scores 0
without grading and makes the suite exit 1, and `--disallow-tools` keeps named
built-in tools (such as `Agent`) out of every case. The `disallowed_tools` case
field from the same release is changelog-only and untested here.

## A plugin class these skills do not cover

**Mods** (Claude Code 2.1.292+) are TypeScript plugins that register session
handlers, with ten documentation pages under `/docs/en/plugins/mods/`, a
`claude plugin test` command, a manifest `types` field for their `.d.ts`, and a
`gatingHooks` section in `claude plugin validate --json`. None of the skills
above reads or writes one. The single place a mod intersects this plugin's
subject matter is the permission model: a mod's `tool.check` answers after the
permission rules and the `PreToolUse` hooks and can replace their answer, which
is the seventh step in
`../../agent-harness/references/permission-model.md`. A question that is really
about a mod belongs in the upstream docs, not here.

## A normal sequence

Building something new:

```
/agent-sdk-dev:new-sdk-app (optional) → /agent-sdk:agent-create → /agent-sdk:eval-create → /agent-sdk:eval-criteria → /agent-sdk:eval-run → /agent-sdk:eval-ci
```

Taking over something that exists:

```
/agent-sdk:agent-sdk → /agent-sdk:agent-review → /agent-sdk:agent-harness → /agent-sdk:eval-review → /agent-sdk:eval-create (close gaps) → /agent-sdk:eval-run
```

Something is failing:

```
/agent-sdk:eval-analyze → /agent-sdk:agent-debug → fix → /agent-sdk:eval-create (regression case) → /agent-sdk:eval-run --runs 5
```

## Where the deterministic work happens

Every skill's judgement is backed by a script under `skills/<skill>/scripts/`.
They are standard library only and never import `claude_agent_sdk`, so they run
on a project whose environment is broken — which is often exactly when you need
them. The code that does need the SDK is the runner package this plugin copies
into the project (`evals/runner/agent_sdk_evals/`); scripts invoke it through a
resolved interpreter and say which one they used.

---

Sources: this plugin; `https://code.claude.com/docs/en/plugin-evals` and
`https://code.claude.com/docs/en/plugins/cli-reference` (the `--judge-model`
default and the 2.1.289/2.1.293 fixes),
`https://code.claude.com/docs/en/plugins/mods/overview` (the mod class),
`https://code.claude.com/docs/en/permissions` (a mod's `tool.check`
precedence), <https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md>
(2.1.299: API-error scoring, `--disallow-tools`). Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs; re-read 2026-10-24 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs.
