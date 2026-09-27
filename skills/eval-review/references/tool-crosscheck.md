# Making the graders, the agent and the mocks agree

Three lists of tool names drift apart quietly:

* what the **agent** exposes — `@tool` functions inside in-process MCP servers,
  plus whatever `allowed_tools` declares;
* what the **mocks** provide — `evals/mocks/<server>/<tool>.md`;
* what the **graders** assert about.

None of these is the source of truth for the others, and a mismatch does not
raise an error anywhere. It makes a grader assert nothing.

## Why a mismatch is worse than a failure

```yaml
type: no_tool
tools: [mcp__library__reserv_book]     # typo
```

This grader passes. It will pass every time, on every run, forever, including
the run where the agent reserves the book it should have refused. The case is
green and the suite is lying.

The mirror image — a `tool_used` grader naming a tool that does not exist —
fails every time, which at least gets noticed. The silent pass is the dangerous
one, and it is why the cross-check is a warning on every restraint grader
rather than a nicety.

## The four mismatches

| Kind | What you see | Remedy |
|---|---|---|
| unqualified | grader says `reserve_book`, agent exposes `mcp__library__reserve_book` | write the qualified name — bare names match only by suffix |
| unknown server | grader says `mcp__billing__charge`, no `billing` server anywhere | add the server, add a mock, or fix the name |
| orphan mock | `evals/mocks/billing/` but the agent has no `billing` | the agent renamed or dropped it (`MCP020`) |
| untested tool | the agent has `cancel_reservation`, no grader mentions it | add a `tool_used` or `no_tool` grader somewhere |

## Names that are always known

Three names never count as mismatches:

* **`Task` and `Agent`** are the same tool. The CLI reports `Task`, the docs
  and the Python SDK say `Agent`. A grader naming either matches both, and
  neither is reported as unknown.
* **`StructuredOutput`** is how the CLI delivers an `output_format` result — a
  synthetic call, not a tool the agent declares.
* **`ToolSearch`** is deferred MCP tool loading, measured as a real first call
  on MCP-tool cases. Also synthetic.

The last two are skipped by `tool_used`, `tool_order`, `trajectory` and
`no_tool` unless a grader names one explicitly, which is how a case asserts
that structured output was produced at all.

## Bare names and the suffix rule

A grader may write `reserve_book` and it will match `mcp__library__reserve_book`
by suffix. That is a compatibility affordance, not a recommendation:

* the trace records the qualified name, so a report about the bare name reads
  oddly;
* two servers can expose the same tool name, and the suffix match then resolves
  ambiguously;
* the qualified name is what the model actually sees, so it is what the case is
  really talking about.

Generated graders always write the qualified form, and `EVC020` nudges hand-
written ones towards it.

## Where the agent's tool list comes from

An AST read of every module that imports the SDK: `@tool` decorators give the
tool names, `create_sdk_mcp_server(name=…)` gives the server they hang under,
and `allowed_tools` adds anything declared but not defined locally. Nothing is
imported or executed — a review has to work on a project whose imports are the
problem.

When that produces nothing — options built at runtime, `allowed_tools` computed
from a database — the cross-check is **skipped and said to be skipped**. It is
not run against an empty set, which would report every grader as naming an
unknown tool. `/agent-sdk:agent-review`'s `load_agent.py` can get the real list
from a live import when that matters.

## Running it

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/crosscheck_tools.py <project>
python3 ${CLAUDE_SKILL_DIR}/scripts/crosscheck_tools.py <project> --strict   # untested tools count too
```

Run it after any rename in the agent. A tool rename is the single most common
cause of a suite that stays green while proving less than it did yesterday.

Sources: `lib/agent_sdk_skills/graders.py` (`normalize_tool_name`,
`tool_names_match`, `grader_tool_names`, `SYNTHETIC_TOOLS`);
`lib/agent_sdk_skills/evalcase.py` (`EVC020` and its three shapes);
`lib/agent_sdk_skills/mocks.py` (`mock_tool_names`, `MCP020`);
`lib/agent_sdk_skills/options_ast.py` (`tool_names()` from `@tool` and
`create_sdk_mcp_server`); `.dev/CONTRACTS.md` §2.1 and §12.1/§12.7;
https://code.claude.com/docs/en/claude-code/mcp (tools reach the model as
`mcp__<server>__<tool>`).
