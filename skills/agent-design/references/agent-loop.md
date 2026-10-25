# The agent loop, and when not to build an agent

## The loop

Anthropic's Agent SDK article frames every agent as one loop: **gather
context, take action, verify the work, repeat** (*Building agents with the
Claude Agent SDK*, 2025-09-29). Use the loop to decide what the agent needs,
one phase at a time:

| Phase | The design question | SDK feature |
|---|---|---|
| Gather context | Can the agent fetch its own context rather than receive it all in the prompt? | built-in `Read`/`Grep`/`Glob` over a folder laid out for search; MCP tools; subagents for isolated exploration; automatic compaction |
| Take action | Which actions are frequent enough to deserve a tool, and which are better as code or a shell command? | `@tool` + `create_sdk_mcp_server`; `Bash`; external MCP servers |
| Verify | How does the agent learn that its output is wrong before it compounds? | tool results with `is_error`; structured output; hooks; a second session as a judge |

Three habits from the same article:

- **The file system is context.** Folder and file layout is a form of context
  engineering: an agent that can `grep` a well-named directory needs less in
  its prompt.
- **Agentic search first.** Start with grep and file reads; add embedding-based
  semantic search only when speed or recall demands it. It is faster, but less
  accurate, harder to maintain and less transparent.
- **Code for precise work.** Operations that must be exact, composable and
  repeatable are better written as code the agent runs than as a long chain of
  tool calls.

## Workflows against agents

*Building effective AI agents* (2024-12-19) separates two kinds of agentic
system. A **workflow** runs LLM calls and tools through code paths you wrote; an
**agent** lets the model direct its own process and tool use. The article's
rule is to find the simplest solution that works and add complexity only when
it demonstrably improves outcomes — sometimes that means one well-prompted call
with retrieval and examples, and no agent at all.

The page carries its own banner saying the tooling landscape has changed since
December 2024. Cite it for the design rationale below; take current SDK
behaviour from the docs.

Signs you want a workflow, not an agent: the steps are known in advance, the
categories are distinct, and a wrong turn is expensive. Signs you want an agent:
the number of steps cannot be predicted, the environment gives ground truth at
each step (test results, tool output), and you can bound the run.

An agent needs **stopping conditions**. In the SDK that is `max_turns` and
`max_budget_usd`. Count `max_turns` as each turn with tool calls plus one for
the final text-only response; without that extra turn the run ends with
`error_max_turns` and no final response (agent-loop docs, 2026-10-29).

## The five workflow patterns, mapped to the SDK

| Pattern | When it fits (article #2) | In the Agent SDK |
|---|---|---|
| Prompt chaining | a fixed sequence where each step is easier than the whole; programmatic gates between steps | several `query()` calls in your code, each with its own prompt and `output_format`; check each result before the next |
| Routing | distinct input categories that can be classified reliably | classify first, then pick the `ClaudeAgentOptions` per route; inside one session, a `model` per `AgentDefinition` sends cheap work to a small model |
| Parallelization | independent subtasks (sectioning) or the same task several times (voting) | subagents, which the main agent launches in the background by default; parallel tool calls for tools marked `readOnlyHint` |
| Orchestrator-workers | subtasks that cannot be predicted in advance | the main agent with `agents=` and the Agent tool; scope each subagent's `tools` and set `maxTurns` |
| Evaluator-optimizer | clear criteria, and feedback measurably improves the output | a second session (or subagent) that only grades; in evals, an `llm` grader |

Combine them freely; the article is explicit that these are building blocks,
not prescriptions. Before adding a subagent, read
[subagent-decisions.md](subagent-decisions.md): a single loop with skills is
often better.

## The verification ladder

The Agent SDK article orders verification methods from most to least robust:

1. **Rules.** Clearly defined checks on the output, reporting which rule failed
   and why. Linting is the model case. Prefer output formats that admit more
   checks (typed code over untyped, a JSON schema over prose). In the SDK:
   `output_format` with a JSON schema, a tool that validates its input and
   returns `is_error` with what to change, a `PreToolUse` hook that denies with
   a reason.
2. **Visual feedback.** For rendered output, screenshot it and check layout and
   content, for example through a browser-automation MCP server.
3. **LLM as judge.** A second model grades fuzzy criteria. The article calls
   it "generally not a very robust method" with latency costs; use it where
   nothing above can decide.

Climb only as far as you must. A rule that can decide should never be replaced
by a judge.

## Testing and improving the agent

The Agent SDK article's questions, applied to a failing transcript:

- Did it misunderstand the task? Then it lacked information: restructure the
  search tools so it can find it.
- Does it fail the same way repeatedly? Add a formal rule in the tool that
  detects and explains the failure.
- Can it not fix its own errors? Give it a more useful tool.
- Does quality move as features land? Build a representative eval set from real
  usage and run it on every change.

Read the transcripts, not only the scores. Put yourself in the agent's place:
with only these tools and this prompt, could you do the task?

## Three principles

From article #2: keep the design simple; make the agent's planning visible;
and treat the agent-computer interface — tool names, descriptions, parameters —
with the care you would give a human interface. The SWE-bench team in that
article spent more time on its tools than on the prompt. See
[tool-design.md](tool-design.md).

## In this plugin

- `design_check.py` reports DSG008 when nothing bounds the loop;
  `design_brief.py` prints the verification ladder against this plugin's
  grader types.
- Rules map to the free graders (`regex`, `tool_used`, `tool_order`,
  `trajectory`, `no_tool`, `structured_output`, `final_text`, `terminal`,
  `budget`, `hook_event`, `file_exists`); the judge rung is the `llm` grader —
  `/agent-sdk:eval-criteria` chooses between them.
- An eval set from real usage: `/agent-sdk:eval-create`.
- Writing the agent itself: `/agent-sdk-dev:new-sdk-app`, then
  `/agent-sdk:agent-create` for the eval-ready layout.

Sources: https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk ("Building agents with the Claude Agent SDK", 2025-09-29, the gather/act/verify loop, agentic search, the verification ladder and the testing questions); https://www.anthropic.com/research/building-effective-agents ("Building effective AI agents", 2024-12-19, workflows against agents, the five patterns, stopping conditions, the three principles; the page's own banner says its tooling has changed); https://code.claude.com/docs/en/agent-sdk/agent-loop (read 2026-10-29, turns and budget incl. the plus-one rule for `max_turns`, parallel tool execution, compaction); https://code.claude.com/docs/en/agent-sdk/subagents (read 2026-10-29, background launch and `model` per `AgentDefinition`); https://code.claude.com/docs/en/agent-sdk/custom-tools (read 2026-10-29, `readOnlyHint` and `is_error`); https://code.claude.com/docs/en/agent-sdk/structured-outputs (read 2026-10-29, `output_format`). Written 2026-10-29 against claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
