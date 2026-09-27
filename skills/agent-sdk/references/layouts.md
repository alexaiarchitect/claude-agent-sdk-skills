# Layouts: what discovery detects, and where eval files belong

## The SDK prescribes no layout

An agent is any Python module that builds `ClaudeAgentOptions` and calls
`query()` or drives a `ClaudeSDKClient`. Discovery reads every `.py` file that
mentions `claude_agent_sdk` (or the retired `claude_code_sdk`) with `ast` and
classifies it:

| Style | What was found | What the runner can do |
|---|---|---|
| `convention` | a module defining `build_options() -> ClaudeAgentOptions` (`agent.py` preferred) | load it directly, apply case overrides |
| `custom` | one agent module whose options are built in a named function other than `main` | load it when `eval_config.json` names `module:function` |
| `inline` | options built inside `main()` or at module level | nothing until a builder is exposed (`AGT003`) |
| `collection` | several agent modules and no `build_options()` | nothing until `eval_config.json` names one (`AGT002`) |
| `none` | no SDK usage | scaffold first |

Nothing is imported: a project whose dependencies are broken still gets a
correct answer about where its agent is.

## The convention this plugin scaffolds

```
<project>/
  agent.py                 build_options() -> ClaudeAgentOptions; optional run(prompt, options)
  .env / .env.example      CLAUDE_MODEL, optional ANTHROPIC_API_KEY, AGENT_ENTRY
  evals/
    eval_config.json       model, credential policy, judge, tiers, budgets
    <case>/prompt.md       frontmatter + first user prompt
    <case>/graders/*.md    one grader per file
    mocks/<server>/<tool>.md
    personas/*.json  faults/*.json
    runner/agent_sdk_evals/   the runner copy (VERSION, MANIFEST.sha256)
    results/<timestamp>/   traces, per-case results, aggregate.json (gitignored)
  tests/test_evals.py      pytest gate that runs the pr tier
  .github/workflows/       agent-evals-pr.yml, agent-evals-nightly.yml
```

The entry point may be overridden per project (`"agent": "svc.agent:make"` in
`eval_config.json` or `AGENT_ENTRY` in the environment) and per case
(`agent:` in the prompt frontmatter). Whatever it is, it returns options the
runner can copy and override; that is the only requirement.

## Claude Code files the SDK may load

When `setting_sources` is omitted the SDK loads user, project and local
filesystem settings, the same as the CLI: `~/.claude/settings.json`,
`.claude/settings.json`, `.claude/settings.local.json`, `CLAUDE.md` files and
custom commands (a v0.1.0 change to load nothing was reverted). Pass
`setting_sources=[]` to run isolated; Python SDK 0.1.59 and earlier treated the
empty list as omitted, so upgrade before relying on it. Discovery lists these
files so a review can say "this project's evals run with the developer's local
settings and CLAUDE.md in the prompt" (`OPT020`), which is exactly what an eval
or a CI run should avoid. Hosting guidance is the same: `setting_sources=[]`
and `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` keep one tenant's files out of
another's session.

## Where the session transcripts are

The subprocess writes every session as JSONL under `~/.claude/projects/`, in a
directory named after the working directory, or under `CLAUDE_CONFIG_DIR` when
set. `agent-debug` can import one of those files into the trace format, so a
production run can be analysed without re-running it. Cost fields are not in
session files, so budget graders report `NOT_EVALUATED` on imported sessions.

## Targets discovery accepts

- the project root (the usual case),
- the agent module itself (`agent.py`), when the project root is its parent,
- the `evals/` directory, which resolves to its parent.

A repository holding several projects is inventoried with `inventory.py`, which
groups agent modules by the nearest directory that has `evals/`,
`pyproject.toml`, `requirements.txt` or `.git`.

---

Sources: `https://code.claude.com/docs/en/agent-sdk/configuration` (options,
`setting_sources`), `https://code.claude.com/docs/en/agent-sdk/hosting` (state on
local disk, multi-tenant isolation), `https://code.claude.com/docs/en/agent-sdk/sessions`;
this plugin's `lib/agent_sdk_skills/layout.py`.
