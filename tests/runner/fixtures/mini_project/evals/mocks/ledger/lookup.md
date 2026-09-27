---
name: lookup
description: Look a member up in the ledger
schema:
  type: object
  properties:
    member_id:
      type: string
  required: [member_id]
latency_ms: 0
type: canned
---
Member {{input.member_id}} is in good standing with 0 fines outstanding.
