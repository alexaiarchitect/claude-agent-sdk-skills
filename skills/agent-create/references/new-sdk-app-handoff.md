# Handing off to `/agent-sdk-dev:new-sdk-app`

Anthropic ships an official plugin for the Agent SDK, `agent-sdk-dev`. This
plugin references it and does not depend on it. That distinction is deliberate
and worth understanding before you offer the handoff.

## What `new-sdk-app` does

It is an interview command. It asks what the agent should do, then writes a
small working application — typically a single `main.py` that imports
`claude_agent_sdk`, builds options, and runs a session — plus a README and the
dependency. The plugin also ships two prompt-only verifier agents.

That is genuinely useful for the thing it does: getting from an empty directory
to a program that runs. It is the fastest path to "my agent said something".

## What it does not do

* No `evals/` directory, no cases, no graders, no config.
* No eval runner, so nothing can replay a case or gate a pull request.
* No `.env.example`, so the credential and model story is undocumented.
* No guarantee of an injectable `build_options()`: an interview-written
  `main.py` usually builds options inside `main()`, which is `AGT003` here.

None of that is a criticism — it is a different job. This plugin's `evals/`
scaffold assumes an agent exists; that plugin's scaffold assumes nobody will
evaluate it.

## The soft-reference policy

`.claude-plugin/plugin.json` carries **no `dependencies` entry** for
`agent-sdk-dev`. Three reasons:

1. A dependency would make this plugin fail to install when the other is
   unavailable, for a feature that is one optional step in one skill.
2. `agent-sdk-dev` has been unchanged since 2025-10-17 and some of its docs
   URLs point at hosts that now redirect. Depending on a stale artifact
   inherits its staleness.
3. Nothing in this plugin's flow requires it. Every check works on an agent
   written by hand, by Cursor, or by that plugin.

So discovery *detects* it — `readiness.py` looks under `~/.claude/plugins/` and
asks `claude plugin list --json` when the CLI is on PATH — and reports
`DEP010`, severity **info**, when it is absent. Info, not a warning: a project
that already has an agent needs nothing from it.

## When to offer the handoff

Offer it when **all** of these hold:

* `readiness.py` exited 2, meaning no module here builds `ClaudeAgentOptions`
  or calls `query()` / `ClaudeSDKClient`; and
* the user wants an agent rather than an evaluation of one; and
* `DEP010` is absent from the report, meaning the plugin is installed.

Then say, in one line, what it writes and what it does not, and that they
should come back here afterwards:

> `/agent-sdk-dev:new-sdk-app` will interview you and write the app. It does
> not write evals, a runner or a `.env.example` — come back here for those.

When the plugin is **not** installed, do not propose installing it as part of
this flow. Offer the smaller thing instead: a minimal `agent.py` with
`build_options()` is about fifteen lines, and the user can write it in less
time than an install takes. Say what it needs to contain and let them decide.

## After the handoff

Whatever wrote the app, the return path is the same:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/readiness.py <project>
```

Expect `AGT003` on an interview-written `main.py`. The fix is the extraction
described in [entry-point-convention.md](entry-point-convention.md): move the
`ClaudeAgentOptions(...)` construction out of `main()` into
`build_options()`, and have `main()` call it. Nothing else about the app
changes, and it stays runnable exactly as before.

Sources: `.claude-plugin/plugin.json` (no `dependencies` entry, asserted by
`tests/test_plugin_hygiene.py`); `lib/agent_sdk_skills/report.py` (`DEP010` is
info); https://code.claude.com/docs/en/claude-code/plugins (plugin
installation, `claude plugin list`);
https://code.claude.com/docs/en/claude-code/plugins-reference (manifest schema
and the `dependencies` field this plugin deliberately omits).
