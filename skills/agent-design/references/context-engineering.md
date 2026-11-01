# Context engineering

*Effective context engineering for AI agents* (2025-09-29) treats the context
window as a budget, not a bucket: recall degrades as tokens accumulate, so every
token the agent carries competes for its attention. The article's guiding rule
is to find the smallest set of high-signal tokens that makes the desired outcome
likely. Context engineering is the successor to prompt engineering: it is the
whole of what reaches the model on each turn — system prompt, tool definitions,
retrieved data, message history — and it is decided again on every turn.

## The system prompt: the right altitude

Two failure modes, one on each side:

- **Too low**: brittle if-else logic hardcoded into prose. Every new case adds a
  rule, and the rules start contradicting each other.
- **Too high**: vague guidance that assumes the model shares context it does
  not have.

Aim between them: specific enough to guide, general enough to give heuristics.
Organise the prompt into sections (background, instructions, tool guidance,
output description). Minimal does not mean short; it means nothing that does not
change behaviour.

**Process**: start with a minimal prompt on the best model you can use, run it,
and add instructions and examples only for failures you observed. A prompt
written in advance for imagined failures is mostly noise.

**Examples**: few-shot examples work, but curate a handful of diverse,
canonical ones rather than listing every edge case as a rule.

## Tools are context too

Every tool definition is read on every turn it is loaded. The article's biggest
recurring failure is a bloated tool set with overlapping functions or ambiguous
choice points: "If a human engineer can't definitively say which tool should be
used in a given situation, an AI agent can't be expected to do better."
Keep the set minimal, each tool self-contained with an unambiguous purpose and
descriptive parameters. [tool-design.md](tool-design.md) turns this into
checks.

In the SDK, MCP tool schemas are deferred by **tool search** by default: the
agent sees a summary and loads up to five relevant tools per search. That
removes the token cost of a large catalogue, not the choice problem — overlapping
tools still compete once loaded.

## Just-in-time retrieval

Rather than pre-loading everything that might matter, keep lightweight
identifiers — file paths, stored queries, links — and let the agent load data
through tools when it needs it. Metadata is signal: a folder hierarchy, file
names and timestamps tell the agent what is relevant before it reads anything.
The trade-off is speed: runtime exploration is slower and needs good tools, or
the agent spends context on dead ends. A hybrid works well — load a little up
front (Claude Code loads `CLAUDE.md`), explore the rest on demand (glob, grep).

## Long horizons: three techniques

| Technique | What it does | Fits | In the Agent SDK |
|---|---|---|---|
| Compaction | summarise a near-full conversation and continue from the summary | long back-and-forth | automatic; the stream carries a `compact_boundary` system message; choose the point with `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (100,000–1,000,000 tokens) in `env`; a `PreCompact` hook can archive the transcript first; tell the compactor what to keep in `CLAUDE.md` |
| Structured note-taking | the agent writes notes outside the window and reads them back | iterative work with milestones | a progress file or `NOTES.md` the prompt tells it to maintain; persistent rules in `CLAUDE.md`, which loads through `setting_sources` and is re-injected on every request |
| Sub-agent architectures | focused agents explore with clean windows and return a condensed summary | parallel, breadth-first research | `agents=`; each subagent returns one final message |

The article's advice on compaction prompts: tune for recall first, so nothing
needed is lost, then for precision. Its description of what Claude Code keeps
after compacting is a 2025 description; current behaviour is in the agent-loop
docs. Tool-result clearing and the memory tool it mentions are Claude Developer
Platform features, not Agent SDK options.

Instructions given early in a conversation may not survive compaction. Put
anything that must hold for the whole run in `CLAUDE.md`, not the first prompt.

Sub-agent summaries in the article are often 1,000–2,000 tokens for tens of
thousands explored. If the parent needs more than that from a subagent, the
split is probably wrong ([subagent-decisions.md](subagent-decisions.md)).

**Resending the history costs time, not only tokens.** *Make long-running agents
faster with message threads* (2026-11-02, article #15) describes a Messages API
beta in which the client sends the full conversation once and afterwards only
the new messages plus the previous response's id; a thread expires 5 minutes
after its last request. Billed tokens do not change — the model still reads the
whole context — but the article reports about 35 % lower median time to first
token for 500K–1M-token requests in Claude Code. It is a Claude Platform fact:
nothing in the Agent SDK or Claude Code docs says the SDK uses or exposes
threads, so treat it as a latency note, not a context or cost lever.

## Progressive disclosure: skills

*Equipping agents with Agent Skills* (2025-10-16) calls progressive disclosure
the core design principle of skills, at three levels:

1. the skill's `name` and `description`, preloaded so the agent can tell when
   the skill is relevant;
2. the `SKILL.md` body, read when it is;
3. bundled files (references, scripts), read or run only when needed.

So the context a skill can carry is effectively unbounded while its standing
cost is two lines. Write the `description` for triggering: it is what the
agent decides on. Put deterministic work in scripts the agent runs rather than
reads — a script's output costs tokens, its source need not.

In the SDK, skills are files under `.claude/skills/<name>/SKILL.md`, discovered
through `setting_sources` and scoped with the `skills` option; there is no
programmatic registration. A skill is also how a subagent's instructions fold
into the main loop.

The format is an open standard: since *Donating Agent Skills to the Agentic AI
Foundation* (2026-10-22, article #22) the base spec is governed by the Agentic
AI Foundation under the Linux Foundation. A skill is still a folder with a
`SKILL.md`; Claude Code's own extensions (invocation control, running in a
subagent, injected context) are not part of the donated spec.

**Trust**: a skill can carry instructions and code. Install skills only from
sources you trust, and audit a less-trusted one in full — bundled files,
dependencies, any instruction to contact a network host.

## Code execution with MCP: the trade-off

*Code execution with MCP for efficient agents* (2025-11-04) presents MCP servers
as code APIs the agent calls from a script, so tool definitions load on demand
and large intermediate results are filtered in code instead of passing through
the window. The article reports one workflow dropping from 150,000 to 2,000
tokens. The cost is a **sandboxed execution environment** with resource limits
and monitoring, which direct tool calls do not need. It is a harness pattern,
not an SDK option; the SDK's built-in answer to "too many tool definitions" is
tool search. Choose code execution only when you already run agent-written code
in a sandbox — `/agent-sdk:agent-deploy` covers that.

## In this plugin

- `design_check.py`: DSG005 (overlapping tools) and DSG006 (too many tool
  definitions) are this reference's checks; DSG008 notes when the compaction
  point is left at the default.
- `/agent-sdk:agent-harness` (`context-and-settings.md`) for `setting_sources`,
  `CLAUDE.md` and what the host machine leaks into a run.
- `/agent-sdk:eval-create` for a case that runs past compaction.

Sources: https://www.anthropic.com/research/effective-context-engineering-for-ai-agents ("Effective context engineering for AI agents", 2025-09-29, context as a finite budget, right-altitude prompts, minimal tool sets, just-in-time retrieval, compaction, note-taking, sub-agent summaries); https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills ("Equipping agents with Agent Skills", 2025-10-16, progressive disclosure and skill trust); https://www.anthropic.com/research/code-execution-with-mcp ("Code execution with MCP for efficient agents", 2025-11-04, the token trade-off and the sandbox requirement); https://code.claude.com/docs/en/agent-sdk/agent-loop (read 2026-10-29, what consumes context, automatic compaction, `PreCompact`, CLAUDE.md summary instructions); https://code.claude.com/docs/en/env-vars (read 2026-10-29, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` range); https://code.claude.com/docs/en/agent-sdk/tool-search (read 2026-10-29, deferred tool loading, five tools per search); https://code.claude.com/docs/en/agent-sdk/skills (read 2026-10-29, filesystem skills, `setting_sources`, the `skills` option); https://code.claude.com/docs/en/agent-sdk/claude-code-features (read 2026-10-29, CLAUDE.md loading); https://claude.com/resources/articles/message-threads ("Make long-running agents faster with message threads", 2026-11-02, threads as a time-to-first-token lever with unchanged billing) and https://platform.claude.com/docs/en/build-with-claude/message-threads (read 2026-11-02, beta status, 5-minute expiry); https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation ("Donating Agent Skills to the Agentic AI Foundation", 2026-10-22, the AAIF governs the base spec, format unchanged); https://code.claude.com/docs/en/skills (read 2026-11-02, Claude Code's extensions to the standard). Written 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs. Re-read 2026-11-02 against claude-agent-sdk 0.2.176 / Claude Code 2.1.316 docs.
