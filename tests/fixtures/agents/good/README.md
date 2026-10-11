# Library reservations agent (fixture)

The eval-ready shape this plugin scaffolds: `agent.py:build_options()`, an
in-process MCP server with three deterministic tools, `.env.example`, and an
`evals/` directory with cases, config and the runner copy.

Run it: `python agent.py "Reserve Dune for member-42."`
Evaluate it: `python -m agent_sdk_evals run evals --tier pr` (from `evals/runner` on `PYTHONPATH`).

## Which cases use the `library` mock

`mocks: [library]` is set on **`reserve-available`** and **`two-turn-memory`**
only. The mock's `lookup_book` is a `canned` mock whose body is
`{{input.title}}: 2 copies available; reserved by nobody.`, and a canned mock has
no per-input branching: the runner's `mocks.MOCK_KEYS` is
`name, description, schema, expect, error, latency_ms, type`, so there is no
key that could answer differently per title, and inventing one for a fixture
would be inventing a feature. Those two cases ask for *Dune*, which the mock
answers correctly.

**`refuse-double-booking`, `no-cancel-unasked` and `unknown-title` must hit the
real tools.** Each depends on catalog state the canned mock contradicts: Emma is
held by `member-7` (one copy) and *The Blue Notebook* is not in the catalog,
while the mock reports every title as free with two copies. Under the mock the
agent would correctly reserve Emma and the cases would fail for the wrong
reason. `agent.py`'s `CATALOG` is itself deterministic in-process canned data —
no network, no clock — so dropping `mocks:` costs the cases nothing.
