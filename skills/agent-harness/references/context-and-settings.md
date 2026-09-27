# `setting_sources`, `CLAUDE.md`, and what isolation actually costs

## The default is "behave like the CLI"

When `setting_sources` is not passed, `query()` reads the same filesystem
configuration the Claude Code CLI reads: **user, project and local settings,
`CLAUDE.md` files, and `.claude/` skills, agents and commands.** That is a
deliberate choice by the SDK, and it is the right one for a coding tool running
on a developer's machine. It is the wrong one for an eval, a CI job, or a hosted
agent, because the result then depends on whose machine it ran on.

| Value | Loads |
|---|---|
| not passed | user + project + local, `CLAUDE.md`, `.claude/` skills/agents/commands |
| `["user", "project"]` | those two tiers only |
| `[]` | none of the three |
| not passed **but `skills` is set** | user and project only — set it explicitly to keep local |

## The measurement

Measured by this plugin on 2026-09-30, SDK 0.2.162 with bundled CLI 2.1.285, the
same trivial prompt ("Reply with exactly: ready"), same model
(`claude-sonnet-5-5`), same machine:

| Configuration | Cache-creation tokens | Cost |
|---|---|---|
| default `setting_sources` | 21 503 | **$0.0870** |
| `setting_sources=[]`, `tools=[]`, `strict_mcp_config=True` | 111 | **~$0.0050** |

**About 17x**, entirely in ambient configuration arriving as cache-creation
tokens. It is not a rounding error on a suite of a hundred cases, and it is the
reason this plugin's runner forces `setting_sources=[]` and
`strict_mcp_config=True` unless a case overrides them.

## `[]` is not full isolation

With `setting_sources=[]` the measured run **still** loaded 18 builtin-plugin
skills, 2 builtin plugins (`cc-plugin-agents-md`, `cc-plugin-telemetry`), and
the managed `claude.ai Claude Docs` MCP server. What the option covers is user,
project and local settings and `CLAUDE.md` — nothing else.

Read regardless of the option:

| Input | How to disable |
|---|---|
| managed policy settings (MDM plist, registry, managed settings file) | remove them from the host; server-managed settings are controlled by an organisation Owner and cannot be disabled from the SDK |
| `~/.claude.json` global config | relocate with `CLAUDE_CONFIG_DIR` in `env` |
| builtin plugins and their skills | not controllable from the options object |
| ambient MCP servers and claude.ai connectors | `strict_mcp_config=True` |
| auto memory at `~/.claude/projects/<project>/memory/` | `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in `env` |

So the isolation recipe is three things, not one:

```python
ClaudeAgentOptions(
    setting_sources=[],
    strict_mcp_config=True,
    env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
         "CLAUDE_CONFIG_DIR": per_tenant_config_dir},
    cwd=per_session_directory,
)
```

## A version trap

In **Python SDK 0.1.59 and earlier**, an empty list was treated the same as
omitting the option, so `setting_sources=[]` did not disable anything. The
isolation silently did not happen and the run cost 17x more than it looked like
it should. `OPT021` warns when a project pins an SDK at or below that version
while passing `[]`.

## `settings` is a different option

`settings` takes a file path or an inline JSON string (TypeScript also accepts
an object). Whatever you pass **overrides** user, project and local filesystem
settings; only managed policy ranks higher. It is the way to supply one known
configuration rather than to suppress the machine's.

## What this means for each situation

| Situation | `setting_sources` |
|---|---|
| eval or CI run | `[]`, always, plus `strict_mcp_config=True`. A run that reads the developer's `CLAUDE.md` is not reproducible on another machine |
| hosted or multi-tenant agent | `[]`, plus a per-tenant `CLAUDE_CONFIG_DIR` and `cwd`, plus auto memory off — otherwise one tenant's files reach another tenant's session |
| a coding tool running on a user's own machine | leave it unset; loading their `CLAUDE.md` is the feature |
| an agent that genuinely needs project conventions | `["project"]`, and commit the `CLAUDE.md` it depends on so the dependency is visible |

## Where state lives when nothing is configured

Three kinds of state sit on local disk and survive nothing:

| State | Default location |
|---|---|
| session transcripts | `~/.claude/projects/`, or `projects/` under `CLAUDE_CONFIG_DIR` |
| `CLAUDE.md` memory | `~/.claude/CLAUDE.md` (user tier), the working directory (project tier) |
| working-directory artifacts | the session's `cwd` |

A `SessionStore` adapter mirrors **transcripts only** — not memory files, not
artifacts. Those need a volume or an object-store sync of their own.

## Hooks and subagents from the filesystem

`.claude/settings.json` hooks and `.claude/agents/*.md` subagents come through
the same door. With `setting_sources=[]` they do not load (`HOK030`, `SUB010`).
That is usually correct; if they are genuinely part of the agent, move them into
the `hooks` and `agents` options, where they travel with the code and an eval can
see them.

---

Sources:
<https://code.claude.com/docs/en/agent-sdk/claude-code-features#control-filesystem-settings-with-settingsources>
and its "What settingSources does not control" table,
<https://code.claude.com/docs/en/agent-sdk/configuration#load-settings-files>,
<https://code.claude.com/docs/en/agent-sdk/hosting#multi-tenant-isolation>,
<https://code.claude.com/docs/en/agent-sdk/session-storage>,
<https://code.claude.com/docs/en/agent-sdk/migration-guide>
(the 0.1.59 empty-list behaviour), <https://code.claude.com/docs/en/memory>;
`claude-agent-sdk` 0.2.162 `types.py:2297` (`setting_sources`), `:2105`
(`settings`), `:2018` (`strict_mcp_config`). The 17x cost figure and the list of
what still loaded under `setting_sources=[]` were measured by this plugin on
2026-09-30.
