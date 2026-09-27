---
type: structured_output
schema:
  type: object
  properties:
    answer:
      type: string
  required: [answer]
contains:
  answer: Paris
---
Proves `ResultMessage.structured_output` arrived, matched the declared shape and
carried the expected answer.

`contains` is a subset check, so a longer answer string that includes "Paris"
still passes; use `equals` when the whole value must match.
