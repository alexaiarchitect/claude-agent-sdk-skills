---
name: agent-sdk
description: >-
  Entry point for Claude Agent SDK (Python) agent and evaluation work. Discovers
  the project: which module is the agent and its entry point, SDK version and
  interpreter, the credential the SDK subprocess would use (API key, subscription
  login or token, cloud provider) and what that means for cost, Claude Code files
  the SDK may load, eval cases, config, runner copy, results and CI; shows what
  exists and what is missing, then routes to one focused skill. Use when the user
  says "agent sdk", "claude agent", "evaluate my agent", "eval cases", "graders",
  "trajectory", "pass@k", "LLM judge", "simulated user", "mock MCP", "hooks",
  "permissions", "subagents", "deploy my agent", "session transcript", asks what
  this plugin can do, or when the intent spans several of those. Don't use when
  the request already names one task - go straight to `/agent-sdk:agent-create`,
  `/agent-sdk:agent-review`, `/agent-sdk:agent-debug`, `/agent-sdk:agent-harness`,
  `/agent-sdk:agent-deploy`, `/agent-sdk:eval-create`, `/agent-sdk:eval-criteria`,
  `/agent-sdk:eval-review`, `/agent-sdk:eval-run`, `/agent-sdk:eval-analyze`,
  `/agent-sdk:eval-simulation` or `/agent-sdk:eval-ci`. Don't use for Claude Code
  plugins or subagent .md files: those are evaluated with `claude plugin eval`.
argument-hint: "[project-dir]"
allowed-tools: Read, Grep, Glob, AskUserQuestion, Skill, Bash(python3 *)
---

# Agent SDK agents and evaluations — start here

An Agent SDK agent is a Python program that builds `ClaudeAgentOptions` and
runs a session; the SDK prescribes no layout, ships no eval harness, and
authenticates through a subprocess whose credential the code never mentions.
So the three things people guess wrong are the three that decide what to do
next: which module is the agent, how a run is paid for, and whether any case
exists that a machine could replay. The first step is never advice: it is
finding out what this project already has.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own
directory. Use it verbatim in every command below; a sibling skill's scripts
are at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Discover.** Run it before saying anything about the project:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/discover.py <path> --format md
   ```

   Add `--no-probe` to skip the interpreter check when you only need file
   facts, `--no-cli` to skip `claude auth status`. `--focus layout,evals`
   narrows the work. For the environment alone:
   `python3 ${CLAUDE_SKILL_DIR}/scripts/check_env.py <project-dir>`.

2. **Report.** Show the user the `Found` / `Missing` / `Warnings` blocks the
   script produced. Do not paraphrase the numbers; they are the evidence for
   every option you are about to offer. Always repeat the credential line: an
   API key bills the API, a subscription draws on usage limits.

3. **Options.** Offer the skills from the report's `Options` section, each
   with its cost tier (`free` deterministic, `run` executes the agent, `judge`
   adds judge calls). Exactly one is marked recommended.

4. **Confirm.** Ask with `AskUserQuestion`, then invoke the chosen skill with
   the `Skill` tool. Nothing is written and no session starts before that
   answer. Full protocol: [interaction-protocol.md](references/interaction-protocol.md).

## Route by intent

| The user wants | Skill |
|---|---|
| eval scaffolding for a new or existing app; the runner installed or upgraded | `/agent-sdk:agent-create` |
| a review of agent code: entry point, options, model ids, secrets, legacy names | `/agent-sdk:agent-review` |
| a fix for looping, stalling, wrong tools, flaky runs; a session file explained | `/agent-sdk:agent-debug` |
| hooks, permissions, MCP servers, subagents, `setting_sources` designed or checked | `/agent-sdk:agent-harness` |
| to host it: credentials, isolation, limits, telemetry, a Dockerfile | `/agent-sdk:agent-deploy` |
| eval cases written, a trace turned into a trajectory grader, cases managed | `/agent-sdk:eval-create` |
| to choose graders and budgets, write rubrics, set the judge and tiers | `/agent-sdk:eval-criteria` |
| cases and config validated, tool names cross-checked, coverage measured | `/agent-sdk:eval-review` |
| a tier run, repeated for pass@k, a saved trace re-graded | `/agent-sdk:eval-run` |
| results explained, reliability and efficiency measured | `/agent-sdk:eval-analyze` |
| simulated users, mocked MCP tools, injected faults | `/agent-sdk:eval-simulation` |
| a CI gate, or a read on evaluation maturity | `/agent-sdk:eval-ci` |

A request that names none of these is usually "is my agent any good?", which
starts with `/agent-sdk:eval-review` when cases exist and
`/agent-sdk:eval-create` when they do not.

## Several agents in one repository

When discovery reports a collection, or the request is about a monorepo,
inventory before choosing one:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/inventory.py <repo-root>
```

One row per project: entry style, case count, config, runner copy status,
results, CI. Read down the columns and the next piece of work names itself.

## Two neighbours this plugin does not replace

- **`agent-sdk-dev`** (Anthropic's plugin, `claude-plugins-official`) owns
  `/agent-sdk-dev:new-sdk-app`, an interview that writes a bare `main.py`.
  `/agent-sdk:agent-create` offers it when it is installed and picks up from
  there; nothing here depends on it.
- **`claude plugin eval`** evaluates Claude Code plugins and skills. An agent
  that is a `.claude/agents/*.md` file or a plugin is its job, not this one's.

## What to tell the user when they ask what this can do

1. **Make** an app eval-ready: cases, config, a runner that lives in the project.
2. **Review** the agent statically: entry point, options, model policy, hooks, MCP.
3. **Write** eval cases: happy path, edge, adversarial, memory, regression.
4. **Grade** them: free graders per change, an LLM judge and pass@k nightly.
5. **Run** them, locally or in CI, on your subscription or an API key, and read
   the results honestly.
6. **Debug** what fails from the trace, and pin the fix as a regression case.

## Ground rules

- **Never guess the entry point, the SDK version or the credential.** Run the
  discovery script.
- **Say what a run spends before running it.** Sessions and judge calls, in
  tokens and count; dollars are estimates on a subscription.
- **An existing case is a specification.** Never edit one to make a failing run
  pass without saying so; add a sibling case instead.
- **Cite the source** when you explain an SDK behaviour, so the user can check.

## References

| Question | File |
|---|---|
| How every skill in this plugin behaves | [interaction-protocol.md](references/interaction-protocol.md) |
| What each skill does, what it needs, what it costs | [capability-map.md](references/capability-map.md) |
| The report format and finding-id scheme | [gap-report-format.md](references/gap-report-format.md) |
| Credentials, cost basis, `.env`, picking a Python | [environment.md](references/environment.md) |
| What discovery detects, and where eval files belong | [layouts.md](references/layouts.md) |
| `claude_code_sdk` names and their Agent SDK replacements | [sdk-rename-migration.md](references/sdk-rename-migration.md) |
| What a word means here (case, tier, trajectory, quadrant) | [glossary.md](references/glossary.md) |

## Scripts

| Command | Output | Exit codes |
|---|---|---|
| `scripts/discover.py <path> [--format json\|md] [--focus ...] [--no-probe] [--no-cli]` | full gap report | 0 clean, 1 errors, 2 bad target |
| `scripts/check_env.py <project-dir> [--json] [--no-probe] [--no-cli]` | credential, cost basis, interpreter, model | 0 ready, 1 blocked, 2 bad target |
| `scripts/inventory.py [repo-root] [--json]` | every project in a repository with its evaluation standing | 0, 2 bad target |

## Completion checklist

- [ ] Discovery was run, and its output shown to the user rather than summarized from memory.
- [ ] The credential and its cost basis were stated, or the user was told they could not be verified.
- [ ] The SDK version is known, or the user was told it could not be verified.
- [ ] Options were offered with cost tiers, and the user chose.
- [ ] The chosen skill was invoked, not re-implemented here.
