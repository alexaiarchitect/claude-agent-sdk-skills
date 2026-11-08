# Memory across sessions

A session ends and the next one starts with an empty window. *The components of
agent memory* (Lance Martin, 2026-11-06, article #30) is about what carries
across that gap. Its experiments ran on **Claude Managed Agents** (a mounted
memory directory) and internal harnesses, and it compares **Claude Code's auto
memory**; it never mentions the Agent SDK. This page cites the article for its
method and maps that method to the SDK; the mapping is ours.

## What a memory note is

In the article, agent memory is knowledge Claude gains from experience — with
users, with tasks — and keeps **between sessions** as context it can read
later. Three things are not memory in this sense:

| Not memory | Why |
|---|---|
| in-context learning | it lasts one conversation |
| compaction | a summary that replaces older turns of the *same* session |
| a transcript | the raw record; memory is what was judged worth keeping from it |

A **memory note is a prediction about what a future session will need**. A
rule predicts the pattern will recur; a verified fact predicts a later session
will rely on it without re-checking. The article puts it as "Memory is,
occasionally, a prediction." A note should therefore say how it is known to be
true and what traps were found, so the next session can trust it or test it.

Capture happens during the session (notes written as the agent works, plus the
session log); consolidation happens afterwards, offline. Keep them apart.

## The hierarchy, and why only the top loads

| Layer | Loaded | Holds |
|---|---|---|
| top file | at every session start, injected into context | current goal, an index of the notes below, the agent's own memory rules |
| topic notes | read on demand with the file tools | one subject per file: a tested rule, a decision, a reference |
| raw session logs | searched only when checking | the ground truth consolidation tests notes against |

The article draws a top layer injected into every session and layers below it
read on demand; "three layers" is our reading of it. The top is small on
purpose: every injected token is paid for in every session, a wrong note rides
into every session, and loading a note does not guarantee the model follows it.
Move detail down and leave a link behind.

Claude Code's auto memory has the same shape: a `MEMORY.md` index plus one
topic file per memory, and only the first 200 lines or 25 KB of `MEMORY.md`,
whichever comes first, load at session start. Topic files are read when needed.
When the index nears a limit, Claude Code reminds Claude to shorten it.

## Steering Claude to write memory

- **Say what memory is for, not how to use it.** The article: "it helps to tell
  Claude what memory is for, but not how to use it." On its database benchmark,
  telling recent models that a memory folder existed was enough; a fixed rule
  ("record only failures") removed most of the gain.
- **Let the model judge salience.** Store what the environment will not tell
  you again — plans, tested rules, decisions and their reasons — not what can be
  re-read each turn (a file's contents, a balance, the current state of a page).
  In the article's game runs an older model wrote hundreds of files and spent
  its turns searching them; a newer one kept a handful plus a small top file.
- **Write at decision points**, not only at the end: when a theory is tested,
  when a plan changes, when the user corrects the agent. A session that crashes
  before its summary leaves nothing.
- **Older or smaller models need more steering**: tell them to read memory first
  and to test a theory before recording it as a rule.

## Consolidation ("dreaming")

The article calls the offline pass **dreaming**: reflect over notes and logs
after the sessions, without a user waiting. Five moves, each a section there:

| Move | What it does | Example from the article |
|---|---|---|
| correct | test each note against the transcripts and rewrite the wrong ones | a wrong landmark note sent a game run off the same ledge three times; corrected, the run got past it |
| build representations | organise notes into linked pages per subject (a wiki) | helped multi-document questions over a large code corpus; no gain when the answer sat in one document |
| promote | float notes that every session needs into the top file; move detail down | keeps the top file small and current |
| focus | tune what memory grows toward a goal, then rebuild | one page per contract, terms quoted word for word |
| fill gaps | look across sessions for patterns no single session saw | repointed broken links, added a missing index |

Dreaming costs compute, and its output is not available to a session already
running. Schedule it **between** sessions: after N sessions, nightly, or when
the top file nears its size limit. Check volatile notes more often than stable
ones; checking everything every time is rarely worth it.

## In SDK terms

**(a) The inherited path: Claude Code's auto memory.** An Agent SDK session
inherits Claude Code's auto memory by default, regardless of `setting_sources`,
until `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` is set in `env`. The directory is
`~/.claude/projects/<project>/memory/` (under `CLAUDE_CONFIG_DIR` when set); its
index loads into the system prompt at session start, and the agent writes
memories with the ordinary `Write` and `Edit` tools, so it saves nothing if
those are unavailable. A 2.1.319 `init` measured on 2026-11-08 carried
`memory_paths.auto` with `setting_sources=[]`. `autoMemoryEnabled: false` in
settings also turns it off.

- **A multi-tenant app must turn it off**: `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`,
  `setting_sources=[]`, a per-tenant `CLAUDE_CONFIG_DIR` and `cwd` — otherwise
  what one tenant's session saved loads into another's.
- **A single-user coding tool** can keep it: that is Claude Code's behaviour.
- **Prompt cache**: the `claude_code` preset embeds the auto-memory location
  ahead of your `append` text, so sessions with different locations share no
  cache entry; `"exclude_dynamic_sections": True` on the preset moves it to the
  first user message.
- A subagent's `AgentDefinition.memory` (`"user"`, `"project"`, `"local"`) gives
  it its own directory; it is part of auto memory and has no effect when auto
  memory is off.

**(b) The app-designed path (our design).** When the app owns its memory —
per user, per tenant, stored where the app chooses — turn auto memory off and
build the hierarchy above from SDK parts:

| Part | SDK mechanism |
|---|---|
| memory folder | a `memory/` directory under `cwd`, or a directory passed in `add_dirs`; per tenant, never shared |
| top file at start | the app reads `memory/INDEX.md` (kept short) and passes it as `system_prompt={"type": "preset", "preset": "claude_code", "append": ...}`; or a `SessionStart` shell hook in a settings file loaded through `setting_sources` (Python has no `SessionStart` callback) |
| what memory is for | one paragraph in the same `append`: what to keep, where, and to link detail from the index |
| notes | written by the agent with `Read`/`Write`/`Edit`; a `PostToolUse` hook can log each write for audit |
| write scope | `permission_mode="dontAsk"` with `allowed_tools=["Read", "Glob", "Grep", "Edit(memory/**)"]` — a path rule for writes is written `Edit(path)` (a `Write(path)` rule matches nothing) |
| consolidation | a separate, scheduled `query()` whose prompt is one dreaming move, with the session logs readable, writes cut to `Edit(memory/**)`, `max_turns` and `max_budget_usd` set |
| session logs | the transcripts the SDK already keeps, or a `session_store`; a `PreCompact` hook can archive before compaction |

`allowed_tools` pre-approves and never restricts on its own; it is the
`dontAsk` mode that denies everything not pre-approved. Keep the consolidation
run separate from the working session so a dreaming mistake never lands
mid-task, and diff the memory folder before and after it.

**(c) Managed Agents.** The article's own runs mounted a memory directory into a
Managed Agents session, and its dreaming cookbook uses the Managed Agents API.
That is a Claude Platform service, not the Agent SDK; hosting trade-offs are in
`/agent-sdk:agent-deploy` (`hosting-options.md`).

## Failure shapes

| Failure | Sign | Fix |
|---|---|---|
| stale note | the agent acts on a fact that has changed | date each note; consolidation re-checks volatile notes first |
| wrong note never corrected | the same mistake in every session | a `correct` pass against the logs; keep logs long enough to check against |
| top-file bloat | the index grows until detail crowds out the goal, or is cut off at load | a size limit; `promote` moves detail down and leaves links |
| cross-tenant leak | one user's preference shows up for another | auto memory off, one memory folder and config directory per tenant |
| memory used as a transcript | notes record what happened, not what will matter | say what memory is for; review salience in a consolidation pass |
| memory confused with compaction | rules lost after a long session | rules that must hold for the whole run go in `CLAUDE.md` or the top file, not the first prompt |

## What to test

`/agent-sdk:eval-create` (`memory-and-multiturn.md`) describes the cases: a
**two-run pair** (one case checks that a session writes the note; a second,
seeded with that note by `scaffold_script`, checks that the agent uses it
instead of rediscovering it) and a **consolidation case** (a seeded wrong note
plus a log that contradicts it; the note must come out corrected). The SDK has
no state store, so every assertion reads files or the trace.

## In this plugin

- No `DSG` rule checks memory design; this page is advice for the design
  review, and the brief's long-running checklist covers the progress file.
- `/agent-sdk:agent-harness` (`context-and-settings.md`) lists what loads
  regardless of `setting_sources`, auto memory included, with the isolation
  recipe; `/agent-sdk:agent-deploy` (`hosting-options.md`) covers per-tenant
  storage.
- [long-running-harness.md](long-running-harness.md) for the progress file, which
  serves one long task; a memory note serves sessions that have not happened yet.

Sources: https://www.anthropic.com/research/components-of-agent-memory ("The components of agent memory", 2026-11-06, the definition of memory and what it excludes, a note as a prediction, salience, steering by purpose not rules, the injected top layer kept small, the five dreaming moves and their cost; experiments on Claude Managed Agents, compared with Claude Code's auto memory, no Agent SDK mention); https://www.anthropic.com/research/effective-context-engineering-for-ai-agents ("Effective context engineering for AI agents", 2025-09-29, structured note-taking outside the window); https://www.anthropic.com/research/effective-harnesses-for-long-running-agents ("Effective harnesses for long-running agents", 2025-11-26, the progress file a later session reads); https://code.claude.com/docs/en/memory (read 2026-11-08, `MEMORY.md` index and topic files, first 200 lines or 25 KB, size reminders, `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, `autoMemoryEnabled`); https://code.claude.com/docs/en/agent-sdk/claude-code-features (read 2026-10-29, re-read 2026-11-08, auto memory loads regardless of `setting_sources` and is written with `Write`/`Edit`); https://code.claude.com/docs/en/agent-sdk/hosting (read 2026-11-08, multi-tenant: `setting_sources=[]` plus `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`); https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts (read 2026-11-08, the auto-memory location in the preset and `exclude_dynamic_sections`); https://code.claude.com/docs/en/agent-sdk/hooks (read 2026-11-08, `SessionStart` only as a settings-file shell hook in Python); https://code.claude.com/docs/en/agent-sdk/python (read 2026-11-08, `system_prompt` `append`, `AgentDefinition.memory`); https://code.claude.com/docs/en/sub-agents (read 2026-11-08, subagent memory is part of auto memory); https://code.claude.com/docs/en/permissions (read 2026-11-08, write path rules as `Edit(path)`); https://code.claude.com/docs/en/permission-modes (read 2026-11-08, `dontAsk` denies what is not pre-approved). Written 2026-11-08 against claude-agent-sdk 0.2.179 / Claude Code 2.1.319 docs.
