# `setting_sources`, `CLAUDE.md`, and what isolation actually costs

## The default is "behave like the CLI"

When `setting_sources` is not passed, `query()` reads the same filesystem configuration the Claude Code CLI reads: **user,
project and local settings, `CLAUDE.md` files, and `.claude/` skills, agents and commands.** Right for a coding tool on a developer's machine; wrong for an eval, a CI job or a hosted agent, whose result then depends on whose machine it ran on.

| Value | Loads |
|---|---|
| not passed | user + project + local, `CLAUDE.md`, `.claude/` skills/agents/commands |
| `["user", "project"]` | those two tiers only |
| `[]` | none of the three |
| not passed **but `skills` is set** | user and project only — set it explicitly to keep local |

`"local"` reads `<cwd>/.claude/settings.local.json`, which "can also load from the repository's root" when `cwd` is inside a
git repository; project `settings.json` loads from `<cwd>/.claude/` with no parent-directory fallback.

## The measurement

Measured by this plugin on 2026-09-30, SDK 0.2.162 with bundled CLI 2.1.285, the same trivial prompt ("Reply with exactly:
ready"), same model (`claude-sonnet-5-5`), same machine:

| Configuration | Cache-creation tokens | Cost |
|---|---|---|
| default `setting_sources` | 21 503 | **$0.0870** |
| `setting_sources=[]`, `tools=[]`, `strict_mcp_config=True` | 111 | **~$0.0050** |

**About 17x**, entirely in ambient configuration arriving as cache-creation tokens. It is not a rounding error on a suite of a
hundred cases, and it is the reason this plugin's runner forces `setting_sources=[]` and `strict_mcp_config=True` unless a
case overrides them.

## `[]` is not full isolation

With `setting_sources=[]` the measured run **still** loaded 18 builtin-plugin skills, 2 builtin plugins
(`cc-plugin-agents-md`, `cc-plugin-telemetry`), and the managed `claude.ai Claude Docs` MCP server. What the option covers is
user, project and local settings and `CLAUDE.md` — nothing else.

Read regardless of the option:

| Input | How to disable |
|---|---|
| managed policy settings (MDM plist, registry, managed settings file) | remove them from the host; server-managed settings are controlled by an organisation Owner and cannot be disabled from the SDK |
| `~/.claude.json` global config | relocate with `CLAUDE_CONFIG_DIR` in `env` |
| builtin plugins and their skills | not controllable from the options object |
| ambient MCP servers and claude.ai connectors | `strict_mcp_config=True` |
| auto memory at `~/.claude/projects/<project>/memory/` | `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in `env` |

With `permissions.blockWritesOutsideWorkingDirectories` on (2.1.314+, see `permission-model.md`) this project's auto-memory
`.md` files stay writable, but an `autoMemoryDirectory` chosen by repository settings is refused.

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

**Values in `env` — and in a settings file's `env` block — are not shell-expanded.** `"$HOME/.cache"`, `"~/state"` and
`"${TMPDIR}/x"` are passed through literally, so the subprocess sees a path that does not exist. Expand in Python and pass an
**absolute** path: `env={"CLAUDE_CONFIG_DIR": str(Path.home() / ".cache" / tenant)}`.

**What the subprocess does not inherit.** `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` governs a published list: `ANTHROPIC_API_KEY`,
`AWS_SECRET_ACCESS_KEY`, `CLAUDE_CONFIG_DIR` and anything matching the credential name/value patterns are removed from
commands Claude runs, while `GITHUB_TOKEN`, `GH_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN`,
`HTTP_PROXY`/`HTTPS_PROXY` and `GIT_CONFIG_*` are kept. A hook or a test that needs the key has to be given it explicitly.

## A version trap

In **Python SDK 0.1.59 and earlier**, an empty list was treated the same as omitting the option, so `setting_sources=[]` did
not disable anything. The isolation silently did not happen and the run cost 17x more than it looked like it should. `OPT021`
warns when a project pins an SDK at or below that version while passing `[]`.

## `settings` is a different option

`settings` takes a file path or an inline JSON string (TypeScript also accepts an object). From SDK 0.2.182 a path is read
relative to `cwd`, and settings that cannot be loaded or merged with `sandbox` raise `CLIConnectionError` at connect instead
of being skipped; Claude Code 2.1.325 likewise stops at start-up when settings that turn the sandbox on fail validation (it
used to run Bash unsandboxed). Whatever you pass **overrides** user, project and local filesystem settings; only managed
policy ranks higher. It is the way to supply one known configuration rather than to suppress the machine's.

Compaction keys are a common reason to pass `settings`, so know their reach. `idleCompaction` (default `true`) compacts a
200K+ token conversation left idle about an hour, before its one-hour prompt cache expires — but only in an **interactive
terminal session**, the VS Code chat panel or the desktop app, and only when feature flags are fetched, so an SDK run never
idle-compacts. `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` moves the 200000 threshold (floor 100000), and `DISABLE_AUTO_COMPACT=1`
now turns off idle compaction along with auto-compaction and overrides `autoCompactEnabled`. The `settings-reference` page
lists every key with its scope.

**`CLAUDE_CODE_AUTO_COMPACT_WINDOW`** sets how full the context gets before compaction, "from `100000` to `1000000` tokens".
From 2.1.304 it takes `k`/`M` suffixes (`200k`, `1M`) and warns on a bad value (before, `200k` silently set a 100K window).
After a compaction Claude is sent the skill list again (2.1.304). From **2.1.311** a standard-context session whose request
runs over 200K tokens compacts and continues instead of stopping with "Usage credits required for 1M context".

## Context is a budget: compaction, notes, just-in-time loading

Anthropic's context-engineering guidance (2025-09-29) frames the window as "a finite resource with diminishing marginal
returns": recall degrades as tokens accumulate, so aim for the smallest set of high-signal tokens. Its long-horizon techniques
map onto SDK knobs:

| Technique (article) | In an SDK agent (docs) |
|---|---|
| compaction, prompt tuned for recall first, then precision; clearing old tool results is the lightest form | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` sets when; a `PreCompact` hook logs or adds what must survive; return less from your own tools |
| structured note-taking outside the window (progress files, to-do lists) | `CLAUDE.md` loaded through `setting_sources`; Claude Code's auto memory, which an SDK session inherits even with `setting_sources=[]` unless `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`; or a notes file the agent reads at start (`agent-design/references/memory-design.md`) |
| just-in-time retrieval: keep paths and queries, load data with tools on demand | Read/Grep/Glob or a search tool rather than pasting documents into the prompt; skills load their body only when used |

Tool-result clearing and the memory tool the article names are Messages API features, not `ClaudeAgentOptions` fields (design
review: `/agent-sdk:agent-design`). **Message threads are a Messages API fact, not an SDK option.** Anthropic's article of
2026-11-02 describes threads: the first request carries the whole conversation, later ones only the new messages plus the
previous response's id, and a thread expires 5 minutes after its last request. Billed tokens do not change (Claude still reads
the full conversation), so it is a latency lever, not a cost lever: median time to first token fell about 35 % on
500K–1M-token requests in Claude Code. Neither the article nor the Claude Code docs say whether an SDK session uses them;
`ClaudeAgentOptions` has no field for them.

`sandbox.allowNestedUserNamespaces` (2.1.305+, user or managed scope) lets sandboxed Linux/WSL2 commands create user
namespaces, and "you turn off a security boundary" (`secure-deployment.md`); `sshHostCommands` is Desktop-only.

## What this means for each situation

| Situation | `setting_sources` |
|---|---|
| eval or CI run | `[]`, always, plus `strict_mcp_config=True`. A run that reads the developer's `CLAUDE.md` is not reproducible on another machine |
| hosted or multi-tenant agent | `[]`, plus a per-tenant `CLAUDE_CONFIG_DIR` and `cwd`, plus auto memory off — otherwise one tenant's files reach another tenant's session |
| a coding tool running on a user's own machine | leave it unset; loading their `CLAUDE.md` is the feature |
| an agent that genuinely needs project conventions | `["project"]`, and commit the `CLAUDE.md` it depends on so the dependency is visible |

## Effort: which level a run gets

Claude Code resolves effort in this order, the first that applies winning: (1) `CLAUDE_CODE_EFFORT_LEVEL`; (2) a level picked
in the session (`/effort`, the `/model` picker, `applyFlagSettings()`); (3) `--effort` (the SDK's `effort` option); (4)
settings — a saved per-model level or `effortLevel`, precedence at `modelSettings`; (5) the model default: `high`, except Opus
5.5, Sonnet 5.5 and Haiku 5.5 (`medium`) and Opus 4.7 (`xhigh`). `CLAUDE_CODE_EFFORT_LEVEL=auto` or
`unset` sends no level, so the API default applies. A variable in `env` therefore beats the `effort` option. Bash subprocesses
and hook commands see the level in force as `CLAUDE_EFFORT`. A subagent or teammate with no `effort` of its own gets the
session's level only on the session's model; on another model it uses that model's saved level or default (2.1.317; see
`subagent-design.md`), unless `CLAUDE_CODE_SUBAGENT_EFFORT` (2.1.316, changelog only) names one.

## Where state lives when nothing is configured

Three kinds of state sit on local disk and survive nothing:

| State | Default location |
|---|---|
| session transcripts | `~/.claude/projects/`, or `projects/` under `CLAUDE_CONFIG_DIR` |
| `CLAUDE.md` memory | `~/.claude/CLAUDE.md` (user tier), the working directory (project tier) |
| working-directory artifacts | the session's `cwd` |

A `SessionStore` adapter mirrors **transcripts only** — not memory files, not artifacts. Those need a volume or an
object-store sync of their own. To leave **no local transcript** from a fresh session, set `CLAUDE_CONFIG_DIR` to a new,
private temp directory in `env` (a run resumed from the store already deletes its local copy). That directory holds no login,
so a claude.ai sign-in or a user `apiKeyHelper` fails with `Not logged in`: pass `CLAUDE_CODE_OAUTH_TOKEN` from `claude
setup-token` (model requests only — no claude.ai connectors in that run) or `ANTHROPIC_API_KEY` in the SDK's `env`, or copy
the config files in. The OAuth variables (`CLAUDE_CODE_OAUTH_TOKEN`, `_REFRESH_TOKEN`, `_SCOPES`) are ignored in a project or
local settings file's `env` block (docs read 2026-11-04). From 2.1.317 a `claude -p` started inside a cloud or self-hosted
runner session gets its own session id and transcript; `CLAUDE_CODE_DISABLE_NESTED_SESSION_ID=1` on a self-hosted runner
restores the shared one (changelog only; not on the env-vars page).

**Resuming** (`sessions`, read 2026-11-17): Claude Code doesn't restore `--mcp-config`, `--plugin-dir`, `--add-dir`,
`--settings` or `--fallback-model` on `--continue`/`--resume` — an SDK app passes the same options again. Two `claude -p` runs
(or two SDK clients) resuming one session at once write to one transcript and can lose messages: give each its own copy with
`fork_session=True`. `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` now also stops the generated-title request in Agent SDK sessions.
From 2.1.326 values nested deeper than 64 levels are dropped with a warning, and a settings file that fails to save while the
session runs is now named instead of skipped silently.

## Streaming input and matching results

A `ClaudeSDKClient` can take a new message while Claude is still working ("Send messages to a running agent", rewritten
2026-11-17). Run **one `receive_response()` loop per response**: each stops at the next `ResultMessage`, and in Python it
yields an error result without raising. A message sent during tool calls reaches Claude after them and is answered in the same
response as the earlier one (a new turn if the turn ended first), so one result can answer two prompts. `interrupt()` ends the
response with `error_during_execution`; messages sent before it still reach Claude afterwards.

`origin` says only what *started* a turn: a prompt sent while an injected turn (a background-task notification, a scheduled
prompt) runs can be answered inside it, and that result carries the injected origin, and `receive_response()` may stop at it
(the SDK docstring says to read with `receive_messages()`). From **0.2.183** match by uuid instead: send each prompt as a
user-message dict with a fresh top-level `uuid` and look for it in the result.

```python
uid = uuid.uuid4().hex                     # never reuse one: the CLI can skip a uuid it has seen
async def one():
    yield {"type": "user", "message": {"role": "user", "content": text}, "parent_tool_use_id": None, "uuid": uid}
await client.query(one())
mine = uid == result.user_message_uuid or uid in (result.user_message_uuids or [])
```

Measured 2026-11-17 on CLI 2.1.326 and 2.1.327: the uuid comes back verbatim in `user_message_uuid` and as `user_message_uuids
== [uid]` on the `ResultMessage` and the first `AssistantMessage` (`init` lists it too); a plain-string prompt gets `None` for
both. Per the docstrings it is set on error results too (check `is_error` before treating the prompt as answered), the list
holds at most 64, and an interrupted turn's list can be empty. This plugin's runner (0.2.6) stamps every prompt this way and
keeps reading past results of injected turns. Set `max_buffer_size` (characters; `64 * 1024 * 1024`) before an agent reads
PDFs or screenshots, or one oversized message ends the stream with `CLIJSONDecodeError`
(`agent-review/references/options-reference.md`).

## Hooks and subagents from the filesystem

`.claude/settings.json` hooks and `.claude/agents/*.md` subagents come through the same door. With `setting_sources=[]` they
do not load (`HOK030`, `SUB010`). That is usually correct; if they are genuinely part of the agent, move them into the `hooks`
and `agents` options, where they travel with the code and an eval can see them.

**Plugins and skills.** A plugin passed in `plugins` loads at session start. To apply a change to its skills, commands, agents
or hooks without a new session, the TypeScript SDK has `reloadPlugins()`; "The Python SDK doesn't expose an equivalent method;
send `/reload-plugins` as a prompt in the session instead" (`agent-sdk/plugins`, read 2026-11-08). A plugin that only a
project's `.claude/settings.json` enables is **not installed** by that file: each clone runs `claude plugin install
<name>@<marketplace> --scope project` (or `CLAUDE_CODE_SYNC_PLUGIN_INSTALL=1` for one `-p` run), and a plugin enabled in an
`--add-dir` directory loads only when that file's setting source is on (`plugins/loading`, read 2026-11-14). Anthropic's notes
on how the Claude Code team uses skills (2026-06-03, Claude Code material) carry over to skills an SDK agent loads through
`setting_sources` or `plugins` and filters with `skills`: write the description for when to trigger the skill, and grow a
gotchas section from observed failures.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/claude-code-features#control-filesystem-settings-with-settingsources> and
its "What settingSources does not control" table,
<https://code.claude.com/docs/en/agent-sdk/configuration#load-settings-files>,
<https://code.claude.com/docs/en/agent-sdk/hosting#multi-tenant-isolation>,
<https://code.claude.com/docs/en/agent-sdk/session-storage> (`CLAUDE_CONFIG_DIR` temp directory and its credentials),
<https://code.claude.com/docs/en/model-config> (effort resolution order and defaults),
<https://code.claude.com/docs/en/agent-sdk/claude-code-features> (`settings.local.json` from the repository root; auto memory
regardless of `settingSources`), <https://code.claude.com/docs/en/agent-sdk/migration-guide> (the 0.1.59 empty-list behaviour),
<https://code.claude.com/docs/en/memory>; <https://code.claude.com/docs/en/env-vars> (the scrub table, and that `env` values
are not shell-expanded, `DISABLE_AUTO_COMPACT`, `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`),
<https://code.claude.com/docs/en/settings>, <https://code.claude.com/docs/en/settings-reference#idlecompaction>;
<https://code.claude.com/docs/en/model-config> (values and warnings for `CLAUDE_CODE_AUTO_COMPACT_WINDOW`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.304, 2.1.305, 2.1.310, 2.1.311 compaction entries;
2.1.316 `CLAUDE_CODE_SUBAGENT_EFFORT`; 2.1.317 subagent effort and `CLAUDE_CODE_DISABLE_NESTED_SESSION_ID`);
<https://code.claude.com/docs/en/settings-reference#variables-claude-code-ignores-in-env>;
<https://code.claude.com/docs/en/settings-reference> (`permissions.blockWritesOutsideWorkingDirectories`, what stays writable);
<https://code.claude.com/docs/en/agent-sdk/plugins> ("Reload plugins in a running session", read 2026-11-08);
<https://claude.com/resources/articles/message-threads> ("Make long-running agents faster with message threads", 2026-11-02,
threads, 5-minute expiry, unchanged billing, the ~35 % TTFT figure);
<https://platform.claude.com/docs/en/build-with-claude/message-threads> (beta header, expiry and deletion, ZDR);
<https://www.anthropic.com/research/effective-context-engineering-for-ai-agents> ("Effective context engineering for AI
agents", 2025-09-29, context as a finite resource, compaction tuned for recall then precision, note-taking, just-in-time
retrieval); <https://claude.dev/blog/lessons-from-building-claude-code-how-we-use-skills/> ("Lessons from building Claude Code:
How we use skills", 2026-06-03, descriptions written for triggering, gotchas);
<https://code.claude.com/docs/en/plugins/loading> ("Enabled in project settings but not installed", read 2026-11-14);
<https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode> (read each response, interrupt, messages sent during tool
calls; read 2026-11-17), <https://code.claude.com/docs/en/sessions> (flags to pass again, concurrent resumes, the title
variable; read 2026-11-17), the 2.1.326 changelog (settings depth and errors); `claude-agent-sdk` 0.2.183 `types.py:2721`
(`setting_sources`), `:2526` (`settings`), `:2439` (`strict_mcp_config`), `:2517` (`cwd`), `:1359-1373` (`MessageOrigin`),
`:1413-1422` (`AssistantMessage.user_message_uuid(s)`), `:1728-1786` (`ResultMessage`, the uuid fields at `:1767-1786`); the
uuid echo measured by this plugin on 2026-11-17 (0.2.183, CLI 2.1.326 and 2.1.327). The 17x cost figure and the list of what
still loaded under `setting_sources=[]` were measured by this plugin on 2026-09-30. Re-read 2026-10-11 against claude-agent-sdk
0.2.165 / Claude Code 2.1.296 docs. Re-read 2026-10-24 against claude-agent-sdk 0.2.174 / Claude Code 2.1.310
docs.
Re-read 2026-11-14 against claude-agent-sdk 0.2.182 / Claude Code 2.1.325 docs.
Re-read 2026-11-17 against claude-agent-sdk 0.2.183 / Claude Code 2.1.326 docs.
