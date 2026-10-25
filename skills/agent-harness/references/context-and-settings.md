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

`"local"` reads `<cwd>/.claude/settings.local.json`, which "can also load from
the repository's root" when `cwd` is inside a git repository; project
`settings.json` loads from `<cwd>/.claude/` with no parent-directory fallback.

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

**Values in `env` — and in a settings file's `env` block — are not
shell-expanded.** `"$HOME/.cache"`, `"~/state"` and `"${TMPDIR}/x"` are passed
through as those literal strings, so the subprocess sees a path that does not
exist. Expand in Python and pass an **absolute** path:
`env={"CLAUDE_CONFIG_DIR": str(Path.home() / ".cache" / tenant)}`. Boolean
settings are read more loosely than they used to be (`"true"`, `"1"`, `"yes"`
and their negatives all parse), but a path is still a path.

**What the subprocess does not inherit.** `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`
governs a published list: `ANTHROPIC_API_KEY`, `AWS_SECRET_ACCESS_KEY`,
`CLAUDE_CONFIG_DIR` (added in 2.1.251) and anything matching the credential
name/value patterns are removed from commands Claude runs, while `GITHUB_TOKEN`,
`GH_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN`,
`HTTP_PROXY`/`HTTPS_PROXY` and `GIT_CONFIG_*` are kept. Before 2.1.251 only the
first two were removed. A hook or a test that needs the key has to be given it
explicitly.

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

Compaction keys are a common reason to pass `settings`, so know their reach.
`idleCompaction` (default `true`) compacts a 200K+ token conversation left idle
about an hour, before its one-hour prompt cache expires — but only in an
**interactive terminal session**, the VS Code chat panel or the desktop app, and
only when feature flags are fetched, so an SDK run never idle-compacts.
`CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` moves the 200000 threshold (floor
100000), and `DISABLE_AUTO_COMPACT=1` now turns off idle compaction along with
auto-compaction and overrides `autoCompactEnabled`. The `settings-reference`
page lists every key with its scope.

**`CLAUDE_CODE_AUTO_COMPACT_WINDOW`** sets how full the context gets before
compaction, "from `100000` to `1000000` tokens". From 2.1.304 it takes `k`/`M`
suffixes (`200k`, `1M`) and warns on a bad value: "reads as <N> tokens, so
Claude Code treats it as the 100k minimum", "is too large, so Claude Code treats
it as the 1M maximum", or "isn't a usable size, so Claude Code ignores it".
Before 2.1.304 `200k` silently set a 100K window. A bare number is tokens:
`CLAUDE_CODE_AUTO_COMPACT_WINDOW=200` means 200 tokens (clamped to 100k), though
`/autocompact 200` means 200,000. After a compaction Claude is sent the skill
list again (2.1.304), and from 2.1.310 `-p` and Agent SDK sessions use less
memory compacting a very large transcript file. From **2.1.311** a
standard-context session whose request runs over 200K tokens compacts and
continues instead of stopping with "Usage credits required for 1M context", and
Claude no longer sees stale `MEMORY.md`/`CLAUDE.md` right after an
auto-compaction when those files were edited earlier in the session.

## Context is a budget: compaction, notes, just-in-time loading

Anthropic's context-engineering guidance (2025-09-29) frames the window as "a
finite resource with diminishing marginal returns": recall degrades as tokens
accumulate, so aim for the smallest set of high-signal tokens. Its long-horizon
techniques map onto SDK knobs:

| Technique (article) | In an SDK agent (docs) |
|---|---|
| compaction, prompt tuned for recall first, then precision; clearing old tool results is the lightest form | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` sets when; a `PreCompact` hook logs or adds what must survive; return less from your own tools |
| structured note-taking outside the window (progress files, to-do lists) | memory files (`CLAUDE.md`, auto memory) loaded through `setting_sources`, or a notes file the agent reads at start |
| just-in-time retrieval: keep paths and queries, load data with tools on demand | Read/Grep/Glob or a search tool rather than pasting documents into the prompt; skills load their body only when used |

Tool-result clearing and the memory tool the article names are Claude Developer
Platform (Messages API) features, not `ClaudeAgentOptions` fields. For a design
review of context use, `/agent-sdk:agent-design`.

Two settings keys arrived since the last read: `sandbox.allowNestedUserNamespaces`
(2.1.305+, user or managed scope; lets sandboxed Linux/WSL2 commands create user
namespaces, and "you turn off a security boundary" — see `secure-deployment.md`)
and `sshHostCommands` (Desktop's SSH-from-a-command connections; irrelevant to
an SDK agent).

## What this means for each situation

| Situation | `setting_sources` |
|---|---|
| eval or CI run | `[]`, always, plus `strict_mcp_config=True`. A run that reads the developer's `CLAUDE.md` is not reproducible on another machine |
| hosted or multi-tenant agent | `[]`, plus a per-tenant `CLAUDE_CONFIG_DIR` and `cwd`, plus auto memory off — otherwise one tenant's files reach another tenant's session |
| a coding tool running on a user's own machine | leave it unset; loading their `CLAUDE.md` is the feature |
| an agent that genuinely needs project conventions | `["project"]`, and commit the `CLAUDE.md` it depends on so the dependency is visible |

## Effort: which level a run gets

Claude Code resolves effort in this order, the first that applies winning:
(1) `CLAUDE_CODE_EFFORT_LEVEL`; (2) a level picked in the session (`/effort`,
the `/model` picker, `applyFlagSettings()`); (3) `--effort` (the SDK's `effort`
option); (4) settings — a saved per-model level or `effortLevel`, precedence at
`modelSettings`; (5) the model default: `high`, except Opus 5.5, Sonnet 5.5 and
Haiku 5.5 (`medium`) and Opus 4.7 (`xhigh`). `CLAUDE_CODE_EFFORT_LEVEL=auto` or
`unset` sends no level, so the API default applies. A variable in `env` therefore
beats the `effort` option. Bash subprocesses and hook commands see the level in
force as `CLAUDE_EFFORT`.

## Where state lives when nothing is configured

Three kinds of state sit on local disk and survive nothing:

| State | Default location |
|---|---|
| session transcripts | `~/.claude/projects/`, or `projects/` under `CLAUDE_CONFIG_DIR` |
| `CLAUDE.md` memory | `~/.claude/CLAUDE.md` (user tier), the working directory (project tier) |
| working-directory artifacts | the session's `cwd` |

A `SessionStore` adapter mirrors **transcripts only** — not memory files, not
artifacts. Those need a volume or an object-store sync of their own. To leave
**no local transcript** from a fresh session, set `CLAUDE_CONFIG_DIR` to a new,
private temp directory in `env` (a run resumed from the store already deletes
its local copy). That directory holds no login, so a claude.ai sign-in or a user
`apiKeyHelper` fails with `Not logged in`: pass `CLAUDE_CODE_OAUTH_TOKEN` from
`claude setup-token` (model requests only — no claude.ai connectors in that
run) or `ANTHROPIC_API_KEY` in `env`, or copy the config files in.

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
<https://code.claude.com/docs/en/agent-sdk/session-storage> (`CLAUDE_CONFIG_DIR`
temp directory and its credentials),
<https://code.claude.com/docs/en/model-config> (effort resolution order and
defaults), <https://code.claude.com/docs/en/agent-sdk/claude-code-features>
(`settings.local.json` from the repository root),
<https://code.claude.com/docs/en/agent-sdk/migration-guide>
(the 0.1.59 empty-list behaviour), <https://code.claude.com/docs/en/memory>;
<https://code.claude.com/docs/en/env-vars> (the scrub table, and that `env`
values are not shell-expanded, `DISABLE_AUTO_COMPACT`,
`CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`), <https://code.claude.com/docs/en/settings>,
<https://code.claude.com/docs/en/settings-reference#idlecompaction>;
<https://code.claude.com/docs/en/model-config> (values and warnings for
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.304,
2.1.305, 2.1.310, 2.1.311 compaction entries);
<https://www.anthropic.com/research/effective-context-engineering-for-ai-agents>
("Effective context engineering for AI agents", 2025-09-29, context as a finite
resource, compaction tuned for recall then precision, note-taking, just-in-time
retrieval);
`claude-agent-sdk` 0.2.174 `types.py:2653` (`setting_sources`), `:2460`
(`settings`), `:2373` (`strict_mcp_config`), `:2451` (`cwd`). The 17x cost figure
and the list of what still loaded under `setting_sources=[]` were measured by
this plugin on 2026-09-30. Re-read 2026-10-11 against claude-agent-sdk 0.2.165 /
Claude Code 2.1.296 docs. Re-read 2026-10-24 against claude-agent-sdk
0.2.174 / Claude Code 2.1.310 docs. Re-read 2026-10-29 against claude-agent-sdk
0.2.174 / Claude Code 2.1.312 docs.
