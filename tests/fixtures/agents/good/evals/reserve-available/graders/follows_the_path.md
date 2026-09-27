---
name: follows_the_path
type: trajectory
match: IN_ORDER
args_match: subset
expected:
  - tool: mcp__library__lookup_book
    args:
      title: Dune
  - tool: mcp__library__reserve_book
    args:
      title: Dune
      member_id: member-42
---
Proves the agent looked Dune up before reserving it, and that both calls carried
the title and member the prompt named. `args_match: subset` means extra
arguments the model chooses to send are allowed; the named ones must match.

It does not prove the reply told the member anything, and IN_ORDER allows calls
in between — a lookup of a second title would still pass. That is the right
tolerance for a happy-path case and the wrong one for an adversarial case, where
`no-cancel-unasked` uses EXACT instead.
