---
name: follows_the_path
type: trajectory
match: EXACT
args_match: subset
threshold: 1.0
expected:
  - tool: mcp__library__lookup_book
    args:
      title: Dune
  - tool: mcp__library__reserve_book
    args:
      title: Dune
      member_id: member-42
---
Proves the agent looked the title up and then reserved exactly that title for
exactly that member, with no other call in between.

It does not prove the reply told the member what happened.
