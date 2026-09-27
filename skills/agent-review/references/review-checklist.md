# Review rules

Every check `lint_agent.py` performs: what triggers it, why it matters, and the
source you can check it against. Ids are stable across releases, so a skill may
branch on them and a test may assert them.

## Entry point and structure (`AGT00x`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `AGT000` | **error** | a module could not be parsed | the reviewer reads source; what it cannot parse it cannot judge |
| `AGT001` | **error** | no `ClaudeAgentOptions` anywhere | there is no agent here: an Agent SDK agent is a module that builds options and runs a session |
| `AGT002` | warn | several SDK modules and no `build_options()` | the entry point is a guess. Name it in `evals/eval_config.json` (`agent: "module:function"`) or `AGENT_ENTRY` |
| `AGT003` | warn | every `ClaudeAgentOptions(...)` is inside `main()` | the options exist only for that process. Nothing can obtain them, so every eval override becomes a source edit, and the static review can only see the literals |
| `AGT004` | warn | `query()` called with no `options` | the session runs on SDK defaults: no model pinned, no tool restriction, no ceilings, and the host machine's settings and `CLAUDE.md` loaded |

## Legacy names and deprecated fields (`AGT03x`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `AGT030` | **error** | `import claude_code_sdk` or `ClaudeCodeOptions` | the package and the class were renamed. `tools`, `setting_sources`, `max_budget_usd`, `agents`, `skills`, `effort` and `output_format` exist only on `ClaudeAgentOptions` |
| `AGT031` | warn | `max_thinking_tokens` | deprecated; use `thinking={"type": "adaptive"}`. On newer models the old field is read as on/off only |
| `AGT031` | warn | `debug_stderr` | deprecated **and no longer read by the transport**, so it captures nothing. Use the `stderr` callback |

## Model policy (`AGT01x`, `OPT012`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `AGT010` | warn | a model id written as a literal in the options | dated ids are retired and the agent stops working on a date nobody wrote down. `os.getenv("CLAUDE_MODEL", "...")` is **not** a finding: the default is graded, the pattern is not |
| `AGT011` | warn | a retirement-eligible id | there is a clock on it. See [model-policy.md](model-policy.md) for whose clock |
| `AGT012` | **error** | a retired id | requests fail outright |
| `OPT012` | warn | no `model` and no `fallback_model` | the session starts on Claude Code's default. Measured on the build machine: the CLI default (`claude-fable-5-1`) cost about 4x what Sonnet cost for the same trivial prompt, and a model that can change under you makes results incomparable |
| `SUB002` | warn / **error** | an `AgentDefinition` pins a retiring / retired id | same clock, one level down |

## Credentials (`AGT02x`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `AGT020` | **error** | a string starting `sk-ant-`, or a literal assigned to `ANTHROPIC_API_KEY` / `CLAUDE_CODE_OAUTH_TOKEN` | rotate it. The SDK never reads a credential from your code: the bundled CLI takes it from the subprocess environment |
| `AGT021` | info | no `.env.example` | nothing tells the next person which variables the agent needs, or that leaving the key unset runs on the subscription |

## Tool surface and permissions (`OPT00x`, `OPT06x`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `OPT001` | warn | `allowed_tools` set, `disallowed_tools` empty, `tools` not `[]` | **`allowed_tools` only pre-approves.** An unlisted tool stays in Claude's context and its call falls through to `permission_mode`. Removing a tool takes a bare name in `disallowed_tools`, or `tools=[]` |
| `OPT002` | warn (**error** under `--strict`) | `permission_mode="bypassPermissions"` | approves everything that reaches the permission-mode step. Deny rules still apply; nothing else does |
| `OPT003` | info | allow/deny lists set but `tools` never set | the built-ins are still in context. `tools=[]` is what removes them; MCP tools are unaffected either way |
| `OPT004` | warn | `"Skill"` in `allowed_tools` | deprecated. The `skills` option configures everything including allowing the Skill tool |
| `OPT040` | warn | `agents` defined but neither `Agent` nor `Task` is available | Claude cannot delegate. The CLI reports the tool as `Task`, the docs and SDK call it `Agent`; a check has to accept both |
| `OPT060` | **error** | `permission_mode` is not one of the six literals | `default`, `acceptEdits`, `plan`, `bypassPermissions`, `dontAsk`, `auto` |
| `OPT061` | **error** | `effort` is not one of the five literals | `low`, `medium`, `high`, `xhigh`, `max` |

## Limits (`OPT01x`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `OPT010` | warn | no `max_turns` | a loop has no ceiling. Note it is not a hard stop on assistant turns: measured, `max_turns=1` produced `num_turns=2`. Assert on `terminal_reason == "max_turns"` or `subtype == "error_max_turns"` |
| `OPT011` | warn | no `max_budget_usd` | nothing stops a run that goes wrong expensively. The cap counts subagent requests too, refuses to spawn more subagents, and ends the query with `error_max_budget_usd` |

## Context and settings (`OPT02x`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `OPT020` | warn when `.claude/` or `CLAUDE.md` exists, info otherwise | `setting_sources` not passed | the SDK default matches the CLI: user, project and local settings plus every `CLAUDE.md`. Measured on the build machine, the same prompt cost **17x** more with the default than with `setting_sources=[]` and `strict_mcp_config=True`, because ambient config landed in the cache-creation tokens. Evals and CI should pass `[]` |
| `OPT021` | warn | `setting_sources=[]` while the project pins `claude-agent-sdk <= 0.1.59` | on those releases an empty list was treated as unset, so the isolation silently does not happen |

## Prompt and structured output (`OPT03x`, `OPT05x`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `OPT030` | info | no `system_prompt` | the SDK's minimal default: tool calling and nothing else, with none of the `claude_code` preset's safety instructions. Correct for a thin tool-calling loop; not for an agent with a persona or a refusal rule. `claude -p` uses the preset, the SDK does not |
| `OPT031` | info | the `claude_code` preset with no `append` | the agent has Claude Code's instructions and none of its own. `append` adds yours and removes nothing |
| `OPT050` | **error** | `output_format` is not `{"type": "json_schema", "schema": {...}}` | the transport acts only on `type == "json_schema"`; any other type is dropped silently and `structured_output` stays empty |

## Hooks (`HOK0xx`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `HOK001` | **error** | a callback is not `async def`, or does not take three parameters | the SDK awaits `cb(input_data, tool_use_id, context)` |
| `HOK002` | **error** | a callback returns a dict the SDK does not read — no `hookSpecificOutput` **and** a key outside the common fields — or a `hookSpecificOutput` whose `hookEventName` is not the event it is registered on | nothing in that dict reaches the decision. Not flagged: `return {}` (allow, unchanged), and a return made only of common top-level fields (`continue_`, `stopReason`, `decision`, `reason`, `systemMessage`, `suppressOutput`, `async_`), which every event accepts — that is how a hook halts a turn. `Stop`, `SubagentStop` and `PreCompact` have no `hookSpecificOutput` type and are skipped |
| `HOK003` | **error** | the matcher is not a valid regular expression | it can never match |
| `HOK010` | warn | a `PreToolUse` deny with no `permissionDecisionReason` | the reason is the only thing the model reads; without it the agent is told no and cannot correct |
| `HOK020` | **error** | an event the Python SDK does not have, e.g. `SessionStart` | the Python `HookEvent` literal has **ten** values. `SessionStart` and `SessionEnd` are TypeScript-only, even though a `SessionStartHookSpecificOutput` type exists in Python |
| `HOK030` | info | hooks in `.claude/settings.json` while `setting_sources` excludes `project` | they do not load in an SDK run. Usually what an eval wants |

## MCP servers and tools (`MCP0xx`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `MCP001` | **error** | an `mcp__<server>__` prefix in `allowed_tools` with no such server | the rule can never match. Tool names are `mcp__<server>__<tool>`, where `<server>` is the key in `mcp_servers` |
| `MCP002` | warn | a stdio server's `command` is not on this machine's PATH | the server fails to connect and its tools are absent from the init message. Pass `--no-path-check` when reviewing for a different machine |
| `MCP010` | warn | a `@tool` schema that is not a readable dict of types, a missing description, or a non-async handler | the description and schema are the whole of what the model is told; arguments are validated against the schema before the handler runs |

## Subagents (`SUB0xx`)

| Id | Severity | Trigger | Why |
|---|---|---|---|
| `SUB001` | info | an `AgentDefinition` with no `tools` | it inherits every tool available to subagents. Tool restriction is one of the four reasons to delegate at all |
| `SUB003` | warn | an `AgentDefinition` with no `maxTurns` | the parent's `max_turns` does not cap a subagent, and each subagent's requests count toward the query's `total_cost_usd` |
| `SUB010` | info | `.claude/agents/*.md` present while `setting_sources` excludes `project` | those files do not load. Programmatic `agents` entries take precedence over files of the same name anyway |

## Reading the severities

- **error** — the SDK rejects it, ignores it, or acts on it in a way that makes
  the run mean something other than what you wrote.
- **warn** — it runs today, and either misleads or stops running on a date.
- **info** — worth knowing; no action implied.

A clean review is not a guarantee the agent works: it is a guarantee that these
specific things are not wrong. `load_agent.py` proves it imports and shows what
the computed values came out as; evals prove it behaves.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/permissions>,
`.../agent-sdk/hooks`, `.../agent-sdk/mcp`, `.../agent-sdk/custom-tools`,
`.../agent-sdk/subagents`, `.../agent-sdk/configuration`,
`.../agent-sdk/claude-code-features`, `.../agent-sdk/modifying-system-prompts`,
`.../agent-sdk/structured-outputs`, `.../agent-sdk/agent-loop`,
`.../agent-sdk/migration-guide`, `.../agent-sdk/python`;
`claude-agent-sdk` 0.2.162 `types.py:25` (`PermissionMode`), `:37`
(`EffortLevel`), `:284` (`HookEvent`), `:507-581` (`HookJSONOutput`), `:594`
(`HookCallback`), `:606` (`HookMatcher`), `:1990` (the `Skill` deprecation),
`:2149` (`debug_stderr`), `:2350` (`max_thinking_tokens`), `:1971-2430` (the 49
fields); `__init__.py:241` (`SdkMcpTool`);
<https://platform.claude.com/docs/en/about-claude/model-deprecations>. The 17x
and 4x cost figures and the `max_turns=1 -> num_turns=2` result were measured by
this plugin against SDK 0.2.162 with bundled CLI 2.1.285.
