# Library reservations agent (fixture)

The eval-ready shape this plugin scaffolds: `agent.py:build_options()`, an
in-process MCP server with three deterministic tools, `.env.example`, and an
`evals/` directory with cases, config and the runner copy.

Run it: `python agent.py "Reserve Dune for member-42."`
Evaluate it: `python -m agent_sdk_evals run evals --tier pr` (from `evals/runner` on `PYTHONPATH`).
