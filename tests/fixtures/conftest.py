"""Fixture projects are data, not tests.

Fixture projects carry `agent.py` modules that import `claude_agent_sdk`, and
some carry a copy of the eval runner plus a `tests/test_evals.py` gate. The
interpreter running this plugin's own tests deliberately does not have the SDK:
the whole point of the plugin is that it works before the project's environment
does. So pytest must treat everything under `fixtures/` as data and never
collect it.
"""

collect_ignore_glob = ["*"]
