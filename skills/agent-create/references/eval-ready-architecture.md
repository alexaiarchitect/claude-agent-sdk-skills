# What makes an Agent SDK agent evaluable

An agent that works is not the same thing as an agent you can test. The
difference is five properties, and none of them is about the agent's quality:
they are about whether a second program can obtain the agent, run it, and get
the same answer twice.

This is why `/agent-sdk:agent-create` never writes the agent. The app is the
easy part and the official `agent-sdk-dev` plugin already writes one. What is
usually missing is the seam.

## 1. Injectable options

The runner has to *obtain* `ClaudeAgentOptions` before the session starts, so
it can override the model, narrow the tools, cap the budget and force the
isolation defaults. That is only possible when the options are built by
something a second process can call:

```python
def build_options() -> ClaudeAgentOptions:      # injectable
    return ClaudeAgentOptions(model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"), ...)

async def main() -> None:                        # NOT injectable
    options = ClaudeAgentOptions(...)            # exists only inside this process
```

The second shape is `AGT003`. Everything downstream inherits the problem: a
case cannot pin a model, so results drift with the CLI's default; a case cannot
narrow the tools, so an adversarial case cannot prove the agent *chose* not to
call something it was never offered.

Several modules that each build options, and none named `build_options`, is
`AGT002` — the same problem with a different cause. Name the entry point in
`evals/eval_config.json` and it goes away.

## 2. Deterministic tools

A grader compares a run against an expectation. If the tool underneath returns
a different answer each time, the comparison measures the backend. Two ways
out, and they compose:

* **In-process tools over fixed data.** `@tool` functions over a dict or a
  SQLite file in the run's working directory. This is what the plugin's own
  fixture agent does.
* **Mocks.** `evals/mocks/<server>/<tool>.md` replaces a server with canned
  answers for the duration of a case. Use these for anything you do not own:
  a payment API, a search index, another team's service.

A case that talks to production is not an eval; it is a smoke test with a
grader attached, and it will fail on the day the backend is slow.

## 3. A stable entry point

`agent:build_options` — module, colon, function. It is written down in one
place (`evals/eval_config.json`), overridable per case (`agent:` in the
frontmatter) and per environment (`AGENT_ENTRY`). See
[entry-point-convention.md](entry-point-convention.md).

## 4. Isolation

By default the SDK loads the developer's user, project and local settings and
their `CLAUDE.md`, exactly as the CLI does. That makes a run depend on the
machine it ran on — and it is expensive: with ambient settings loaded, the
measured cost of the same case was 17x. The runner therefore forces
`setting_sources=[]` and `strict_mcp_config=True` unless a case explicitly
overrides them, and records the choice in the trace's `init` event.

This is not full isolation. Builtin plugins and their skills still load; a case
that depends on one is still machine-dependent. What it buys is that two
developers running the same suite compare the same thing.

## 5. A pinned model

`CLAUDE_MODEL` in `.env`, read by `build_options()` and by the config's
`"model": "${CLAUDE_MODEL:-claude-sonnet-5-5}"`. Without it the SDK inherits
Claude Code's default, which is not the same model on every machine or in every
week, and a suite that silently changes model is a suite whose regressions are
uninterpretable.

## The readiness checklist, as the script reports it

| Check | Finding when missing | Why it blocks evaluation |
|---|---|---|
| entry point, injectable | `AGT003` / `AGT002` | the runner cannot obtain or override options |
| not the retired SDK | `AGT030` | `claude_code_sdk` / `ClaudeCodeOptions` no longer import |
| `.env.example` | `AGT021` | nobody knows which variables matter |
| `.env` gitignored | `ENV020` | a credential reaches the repository |
| `evals/` with a config | gap | no model pin, no tiers, no thresholds |
| at least one case | gap | nothing to replay; claims rest on memory |
| runner copy | `DEP001`-`DEP004` | nothing can run, or runs an unknown version |
| `evals/results/` gitignored | `EVC070` | traces carry prompt and tool-result text |
| pytest gate | gap | the suite runs only when someone remembers |

Run `readiness.py <project>` rather than reading this list: it reports what is
actually there, and the findings carry their own fixes.

Sources: `lib/agent_sdk_skills/layout.py` and `discover.py` (the checks and
their ids); `.dev/CONTRACTS.md` §1.2 (the isolation defaults the runner forces,
and the 17x measurement behind them);
https://code.claude.com/docs/en/agent-sdk/python (`ClaudeAgentOptions`,
`setting_sources`, `strict_mcp_config`);
https://code.claude.com/docs/en/agent-sdk/custom-tools (in-process `@tool`
servers); https://code.claude.com/docs/en/agent-sdk/configuration (choosing a
model).
