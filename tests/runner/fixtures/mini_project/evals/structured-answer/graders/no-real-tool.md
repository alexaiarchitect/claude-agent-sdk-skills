---
type: no_tool
tools: [Bash, Read, mcp__library__lookup_book]
---
Proves no real tool ran.

This is the grader that would break without the synthetic-tool rule: the CLI
delivers structured output as a `ToolUseBlock` named `StructuredOutput`, so a
grader that counted every tool call would see a phantom one on every
structured-output case.
