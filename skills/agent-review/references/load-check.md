# The load check: what it proves, and what a failure means

## What it does

`load_agent.py` runs one probe string in an interpreter that has the SDK:

1. imports `claude_agent_sdk` (so a broken environment fails here, loudly);
2. imports the entry module (`agent`, or whatever `--entry module:function`,
   `AGENT_ENTRY` or the detected layout names);
3. calls the builder;
4. reads the returned dataclass and prints one JSON line.

**It never starts a session.** No `query()`, no `ClaudeSDKClient`, no
credential needed, nothing spent. What it costs is one import of the project's
own code — which is the thing under test.

## Why it is a separate script

The static review works on projects that cannot run, which is most of its value.
But three classes of problem only show up on import:

- **the environment** — a dependency missing from the interpreter that has the
  SDK, a version of the SDK older than the fields the agent uses;
- **construction** — `ClaudeAgentOptions` is a plain dataclass, so a misspelled
  keyword raises `TypeError` immediately; `skills` names are validated and raise
  `ValueError`;
- **computed values** — the static reviewer marks anything it cannot read as
  `dynamic`. The probe prints what those actually came out as, which is the only
  way to see that a model id assembled from an environment variable resolved to
  an empty string.

## Which interpreter runs it

`agent_sdk_skills.env.resolve_runner`, in order:

| Step | What |
|---|---|
| 1 | `$AGENT_SDK_PYTHON` |
| 2 | `.venv/bin/python`, `venv/bin/python` at or above the project (Windows: `Scripts\python.exe`) |
| 3 | `python3`, `python3.12`, `python3.11`, `python3.10` on PATH that can import the SDK |
| 4 | `uv run --with "claude-agent-sdk>=0.2.140" python`, if `uv` is on PATH |
| 5 | none — exit 2, with the venv command to run |

Each candidate is probed by importing the SDK, so a virtualenv that exists but
has no SDK is skipped rather than chosen and then failed on.

## Decoding a failure

| `error_type` | What it usually is |
|---|---|
| `ModuleNotFoundError` | the project is not on `sys.path` (run from the project root), or a dependency is missing from the interpreter that has the SDK. Install the project's requirements into the same environment |
| `ImportError` | a name moved. Several did when `claude_code_sdk` became `claude_agent_sdk`. Note `MessageParseError` is **not** exported from the package root: it lives in `claude_agent_sdk._errors`, so code importing it from the root raises `AttributeError`/`ImportError` |
| `AttributeError` | the module imports but exposes no builder. Define `build_options()`, or pass `--entry module:function` |
| `TypeError` | `ClaudeAgentOptions` rejected a keyword: a typo, or a field from a newer SDK than the one installed. Compare against the 49 in [options-reference.md](options-reference.md) |
| `ValueError` | a value was rejected at construction. Since 0.2.129 the `skills` option rejects parentheses, commas, wildcards, a leading `/` and surrounding whitespace |
| `FileNotFoundError` | the builder read a file relative to the working directory that is not there — a prompt loaded from disk, a catalog fixture |
| `CLINotFoundError` | no `claude` binary. Most installs bundle one at `claude_agent_sdk/_bundled/claude`; a source checkout may not. Install Claude Code or pass `cli_path` |
| `ProbeFailed` | the probe printed no JSON. The tail of stdout and stderr is in the report; usually the interpreter itself failed to start |

## Two facts the output makes concrete

**The bundled CLI beats PATH.** `_find_cli()` returns
`claude_agent_sdk/_bundled/claude` before `shutil.which("claude")`. On the build
machine that meant SDK runs used CLI 2.1.285 while `claude -p` used 2.1.274 —
two versions on one host. `cli_path` is the only way to force the PATH binary,
and the report prints the bundled version so the difference is visible.

**`option_fields` is the installed field list.** The probe prints every field the
installed dataclass declares. Comparing it with what the agent sets is how you
see, for one example, that a project upgraded its SDK and never adopted
`max_budget_usd`.

## When to offer it

- The static review is clean but the agent is reported not to work.
- The review reported values it could not read (`dynamic`), and the answer
  matters.
- Mid-migration from `claude_code_sdk`, where the question is which import
  still resolves.
- Before the first eval run, to separate "the agent does not load" from "the
  agent behaves badly" — the two failures look identical in a run that never
  produced a result.

Do not offer it as a substitute for the static review: it needs a working
environment, and the projects that most need reviewing are the ones that do not
have one.

---

Sources:
<https://code.claude.com/docs/en/agent-sdk/python#claudeagentoptions>,
<https://code.claude.com/docs/en/agent-sdk/migration-guide>,
<https://code.claude.com/docs/en/agent-sdk/troubleshooting>,
<https://code.claude.com/docs/en/agent-sdk/skills>;
`claude-agent-sdk` 0.2.162 `_internal/transport/subprocess_cli.py:237-264`
(CLI discovery order), `_errors.py:129` (`MessageParseError`),
`types.py:2309` (`skills`); this plugin's `lib/agent_sdk_skills/env.py`
(`resolve_runner`) and `lib/agent_sdk_skills/sdk_subprocess.py` (`run_probe`).
The two-CLI-versions-on-one-host observation was measured by this plugin on
2026-09-30.
