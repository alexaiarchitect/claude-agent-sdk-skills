---
type: no_tool
tools: [Bash, Read, Write, mcp__library__lookup_book]
---
Proves the run reached its answer without touching a tool. The case overrides
`tools: []`, so a tool call here would mean the isolation defaults did not apply.

`StructuredOutput` is deliberately not listed: it is a synthetic name the CLI
uses to deliver `output_format` results, and graders skip it unless named.
