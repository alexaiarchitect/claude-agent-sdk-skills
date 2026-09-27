---
name: structured-answer
category: edge
tags: [structured, free]
timeout_seconds: 120
overrides:
  tools: []
  allowed_tools: []
  output_format:
    type: json_schema
    schema:
      type: object
      properties:
        answer:
          type: string
      required: [answer]
---

What is the capital of France? Answer through the schema.
