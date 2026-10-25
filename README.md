# `agent-sdk` — Claude Code skills for Claude Agent SDK agents and evaluations

Fourteen skills for building, reviewing and evaluating agents written with the
Claude Agent SDK (Python). Checked against `claude-agent-sdk` 0.2.174 with its
bundled Claude Code 2.1.310; documentation read at Claude Code 2.1.312.

The premise: an agent's system prompt is a promise written in prose, and **eval
cases are the only form of that promise a machine can check**. The SDK ships no
harness for that, so this plugin does: a runner that lives in your project,
cases and graders in the same grammar `claude plugin eval` uses, an LLM judge
through the SDK, pass@k over repeated runs, and a CI gate whose exit code means
something.

## Install

Run these commands inside Claude Code:

```text
/plugin marketplace add alexaiarchitect/claude-agent-sdk-skills
/plugin install agent-sdk@alexaiarchitect-agent-sdk
```

To try a local checkout without installing:

```bash
claude --plugin-dir /path/to/claude-agent-sdk-skills
```

Then start with `/agent-sdk:agent-sdk` in any project, or go straight to the
skill you want.

## The skills

| Skill | Use it to |
|---|---|
| `/agent-sdk:agent-sdk` | discover a project and route to the right skill |
| `/agent-sdk:agent-create` | make an app eval-ready: cases dir, config, runner copy, `.env.example`, pytest gate |
| `/agent-sdk:agent-review` | review agent code statically: entry point, options, model policy, secrets, legacy SDK names |
| `/agent-sdk:agent-debug` | triage looping, stalling, wrong tools, flakiness from a trace or a session file |
| `/agent-sdk:agent-harness` | design and lint hooks, permissions, MCP servers, subagents, `setting_sources` |
| `/agent-sdk:agent-design` | review the design: tool design, context use, whether a subagent should exist, long-running patterns |
| `/agent-sdk:agent-deploy` | check hosting readiness: credentials, isolation, limits, telemetry |
| `/agent-sdk:eval-create` | write eval cases; turn a reviewed trace into a trajectory grader; manage cases |
| `/agent-sdk:eval-criteria` | choose graders and budgets, write rubrics, set the judge and tiers |
| `/agent-sdk:eval-review` | validate cases and config, cross-check tool names, measure coverage |
| `/agent-sdk:eval-run` | run a tier honestly; repeat for pass@k; replay saved traces for free |
| `/agent-sdk:eval-analyze` | explain results: quadrant, never-evaluated causes, efficiency, reliability |
| `/agent-sdk:eval-simulation` | simulated users, mocked MCP tools, injected faults |
| `/agent-sdk:eval-ci` | a plain workflow step that gates on the runner's exit code; evaluation maturity |

## How they behave

Every skill follows the same five steps: **discover** the project with a script,
**report** what it found, **offer options** with their cost, **confirm** with a
question, then **act and verify**. Nothing is written and no session starts
before you answer.

Costs are stated up front as a tier: `free` (static checks, validation, replay
of saved traces), `run` (executes the agent: one SDK session per case per run),
`judge` (adds LLM-as-judge calls per sample).

## Five things worth knowing before you start

**Runs are paid by whatever credential the SDK subprocess inherits.** An
`ANTHROPIC_API_KEY` bills the API and wins even when you are logged in. With no
key, a stored `claude login` or a `CLAUDE_CODE_OAUTH_TOKEN` from
`claude setup-token` draws on your subscription's usage limits, and the SDK's
`total_cost_usd` becomes an API-equivalent estimate. Every report says which
applies. Anthropic's terms allow this for your own use, not for offering your
login to other people's use of a product; `agent-deploy` asks for a key or a
cloud provider for anything hosted.

**Isolation is forced.** The runner sets `setting_sources=[]` and
`strict_mcp_config=True` unless a case says otherwise: without them a trivial
run loaded the developer's settings and `CLAUDE.md` files and cost seventeen
times more. The SDK's default matches the CLI and loads everything.

**Only a `rejected` rate-limit status stops a suite.** Warnings are recorded;
a rejection marks the rest `NOT_EVALUATED` and exits 3, never a fake failure.
`max_turns` is not a hard cap on turns; assert on `terminal_reason`.

**Leaving `permission_mode` unset is a trap, not a default.** It is not the
same as passing `"default"`: the CLI resolves the mode, and the answer depends
on its version. The docs now state it: "In Claude Code v2.1.302 or later,
`claude -p` and Agent SDK runs with no permission mode set start in Manual
mode" (`default`), where a call needing approval is denied unless something
approves it, and "Before v2.1.302, these runs could start in auto mode if they
didn't fetch feature flags, for example on a third-party provider or with
`DISABLE_TELEMETRY`" — on Claude Code 2.1.285–2.1.301 such a session could land
in `auto`, where a classifier reviews each shell command and broad allow rules
such as a bare `Bash` are dropped.
The runner therefore forces `dontAsk` when your options leave the mode unset and
records that in the trace; `agent-review` reports the omission as `OPT013` (a
warn), because your agent also runs outside the runner, on whatever CLI it
finds.

**The runner copy can go stale.** It is copied into your project's
`evals/runner/` with a `VERSION` and a manifest, so CI needs nothing from the
plugin. Discovery reports `DEP001` when the plugin has moved on, and
`agent-create` upgrades the copy after showing a diff.

## Requirements

Python 3.10+ for the plugin's own scripts, which are **standard library only**
and never import `claude_agent_sdk`. That is deliberate: a review has to work
on a project whose environment is broken.

Anything that actually runs an agent uses the project's interpreter, resolved
in this order:

1. `$AGENT_SDK_PYTHON`
2. a virtualenv at or above the project that imports `claude_agent_sdk`
3. a `python3` on `PATH` that imports it
4. `uv run --with "claude-agent-sdk>=0.2.140"`

```bash
python3 -m venv .venv && .venv/bin/pip install claude-agent-sdk
export AGENT_SDK_PYTHON=.venv/bin/python
```

## Layout

The SDK prescribes none; discovery finds any module that builds
`ClaudeAgentOptions`. Scaffolds assume one convention, and the runner loads it
by default:

```
agent.py                  build_options() -> ClaudeAgentOptions, optional run(prompt, options)
.env.example              CLAUDE_MODEL=claude-sonnet-5-5, optional ANTHROPIC_API_KEY, AGENT_ENTRY
evals/eval_config.json    model, judge, tiers, budgets, isolation
evals/<case>/prompt.md    frontmatter + the first user prompt
evals/<case>/graders/*.md one grader per file
evals/runner/             the runner copy
evals/results/            traces, results, aggregate (gitignored)
```

Any other entry point is named as `module:function` in the config or
`AGENT_ENTRY`.

## Development

```bash
python3 -m pytest tests -q                                          # the plugin's own tests
claude plugin validate . --strict
# skill-level cases under plugin-evals/; needs Claude Code 2.1.293+ (2.1.299+ scores API-error runs 0)
claude plugin eval . --scaffold --allow-tools Bash Write Edit --runs 1 \
  --judge-model claude-sonnet-5-5
python3 .dev/check_sources.py --tier 1                              # what moved upstream
```

Scripts are exercised as subprocesses, the way a skill runs them. SDK-backed
paths run against a fake interpreter in `tests/fixtures/bin/`, so the suite
needs no network and no credentials.

## Attribution

SDK behaviour is cited from `anthropics/claude-agent-sdk-python` (MIT) and the
documentation at `code.claude.com`; the evaluation practices draw on Anthropic's
engineering writing and the `skill-creator` grader design. The design guidance
(`/agent-sdk:agent-design` and the cross-links in the other skills) is grounded
in 14 published Anthropic articles, paraphrased and cited with their dates — see
[Cited Anthropic articles](THIRD_PARTY_NOTICES.md#cited-anthropic-articles). See
`THIRD_PARTY_NOTICES.md` for every snapshot consulted. Fixtures use an original
library-reservations domain; nothing from a non-redistributable source is
included.
