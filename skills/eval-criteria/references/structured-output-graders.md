# Grading structured output

When an agent declares an `output_format`, the SDK returns a parsed object on
`ResultMessage.structured_output` and a `structured_output` grader checks it.
Two things about the mechanism decide how the graders have to be written.

## The synthetic tool call

The CLI delivers a structured result as a **`ToolUseBlock` named
`StructuredOutput`**. It appears in the trace as a tool call, but the agent did
not decide to make it — it is the transport.

So `tool_used`, `tool_order`, `trajectory` and `no_tool` all skip
`StructuredOutput` (and `ToolSearch`, the deferred-tool-loading call) unless a
grader names one explicitly. Without that rule:

* every structured-output case shows a phantom call at the end of its
  trajectory, and `EXACT` fails everywhere;
* every `no_tool` grader fails, because a tool *was* called.

Naming it explicitly is the escape hatch: a `tool_used` grader with
`tool: StructuredOutput` asserts that structured output was produced at all,
which is occasionally what you want.

## The grader

```markdown
---
name: reservation_record
type: structured_output
schema:
  type: object
  required: [title, member_id, copies_left]
  properties:
    title: {type: string}
    member_id: {type: string}
    copies_left: {type: integer}
contains:
  member_id: member-42
---
Proves the agent returned a record of the shape the caller can rely on, and
that it is about the member the prompt named.

It does not prove the values are true. A well-shaped object can be confidently
wrong — `copies_left: 7` validates perfectly. Pair this with a `tool_used`
grader on the lookup that should have produced the number.
```

* `schema` inline, or `schema_file` pointing at a JSON file beside the case.
* `equals` asserts the whole object; `contains` asserts a subset, which is
  almost always what you want — the agent may legitimately add fields.

The schema check is a **hand-rolled subset** of JSON Schema: `type`,
`required`, `properties`, `items`, `enum`, `minimum`/`maximum`,
`minItems`/`maxItems`, and `additionalProperties: false`. There is no
`jsonschema` dependency, because the runner is copied into user projects and
must import nothing but the SDK. A schema using a keyword outside that list is
not silently ignored — the grader says which keyword it could not apply.

## What a schema does not prove

Shape is not truth. The three failure modes a `structured_output` grader will
happily pass:

* **Correct shape, invented values.** The model filled the fields because the
  schema demanded them.
* **Correct shape, wrong subject.** A record about a different title. `contains`
  with the identifying field is the cheap fix.
* **Correct shape, stale values.** The agent answered from the prompt rather
  than from the tool result. A `tool_used` or `trajectory` grader proving the
  lookup happened is what covers this.

A structured-output case wants at least two graders for that reason: this one
for the contract, and a trace-level one for the provenance.

## `additionalProperties: false` and model drift

Setting it makes the schema strict, which catches a model that starts adding
fields — and also breaks the case the first time someone adds a field on
purpose. Use it when the object crosses a boundary (an API response, a file
another system reads) and leave it off when the object is internal.

## When the agent has no `output_format`

Then `result.structured_output` is `null` and the grader fails with "no
structured output". That is the right failure: the case is asserting a contract
the agent does not implement. Add `output_format` to the options, or use
`regex` / `final_text` on the reply instead.

An imported Claude Code session has no `result` event at all, so this grader
reports `NOT_EVALUATED` there rather than failing.

Sources: `lib/agent_sdk_skills/graders.py` (the `structured_output` spec,
`SYNTHETIC_TOOLS` handling, `RESULT_SHAPED_TYPES`); `.dev/CONTRACTS.md` §2.1
(the synthetic-call rule), §5.2 (`structured_output` on the result event) and
§12.8 (the hand-rolled schema subset);
https://code.claude.com/docs/en/agent-sdk/structured-outputs (`output_format`,
the JSON-schema shape); https://code.claude.com/docs/en/agent-sdk/python
(`ResultMessage.structured_output`, `ToolUseBlock`).
