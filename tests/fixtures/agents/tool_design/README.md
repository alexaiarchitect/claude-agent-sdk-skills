# Library reservations agent with a badly designed tool set (fixture)

The same library domain and entry-point convention as `good/`
(`agent.py:build_options()`, `run()`, `.env.example`, `evals/`), with a tool
set and a subagent shaped the way agents drift into: one commit at a time, each
reasonable on its own.

`skills/agent-design/scripts/design_check.py` reports every `DSG` rule on it,
deterministically: DSG001–DSG006 as warnings, DSG007 and DSG008 as notes, exit
code 1. The docstring of `agent.py` maps each rule to the line that triggers it.
The `plugin-evals/design-review` case scaffolds this fixture and asks whether
the tool set is well designed and whether the catalogue search should stay a
subagent.

**Do not fix this fixture.** Every defect is a check's subject; the `good`
fixture is the clean counterpart and must report no warning.

The `ils` MCP server's URL is `https://ils.example.invalid/mcp`, which resolves
nowhere: the 27 pre-approved `mcp__ils__*` names exist only so DSG006 has
something to count. Nothing here holds a credential.
