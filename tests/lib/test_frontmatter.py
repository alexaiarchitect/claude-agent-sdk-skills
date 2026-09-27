"""The frontmatter subset both the plugin and the runner copy read."""

import pytest

from agent_sdk_skills.frontmatter import FrontmatterError, dump, parse

CASE = """---
name: refuse-double-booking
tags: [edge, refusal]
runs: 3
timeout_seconds: 180.5
turns:
  - "Reserve 'Dune' for member 42"
  - Actually make that two copies
overrides:
  model: claude-sonnet-5-5   # pinned
  permission_mode: dontAsk
  allowed_tools: [mcp__library__reserve, "mcp__library__lookup"]
  max_budget_usd: 0.5
  nested:
    deep: true
expected:
  - tool: mcp__library__lookup_book
    args:
      title: Dune
  - tool: mcp__library__reserve_book
env: { }
---

Reserve 'Dune' for member 42.
"""


def test_parses_the_case_shape():
    doc = parse(CASE.replace("env: { }\n", ""))
    m = doc.meta
    assert m["name"] == "refuse-double-booking" and m["tags"] == ["edge", "refusal"]
    assert m["runs"] == 3 and m["timeout_seconds"] == 180.5
    assert m["turns"] == ["Reserve 'Dune' for member 42", "Actually make that two copies"]
    assert m["overrides"]["model"] == "claude-sonnet-5-5"
    assert m["overrides"]["allowed_tools"] == ["mcp__library__reserve", "mcp__library__lookup"]
    assert m["overrides"]["max_budget_usd"] == 0.5 and m["overrides"]["nested"] == {"deep": True}
    assert m["expected"] == [
        {"tool": "mcp__library__lookup_book", "args": {"title": "Dune"}},
        {"tool": "mcp__library__reserve_book"},
    ]
    assert doc.body.startswith("Reserve 'Dune'") and doc.has_frontmatter


def test_no_frontmatter_is_not_an_error():
    doc = parse("just a prompt")
    assert doc.meta == {} and doc.body == "just a prompt" and not doc.has_frontmatter


@pytest.mark.parametrize("text, message", [
    ("---\nname: x\n", "never closed"),
    ("---\nenv: { }\n---\n", "flow mappings"),
    ("---\ncriteria: |\n  long\n---\n", "block scalars"),
    ("---\nname: a\nname: b\n---\n", "duplicate"),
    ("---\n\tname: a\n---\n", "tabs"),
    ("---\nnot a key\n---\n", "expected `key: value`"),
])
def test_errors_name_the_problem(text, message):
    with pytest.raises(FrontmatterError) as exc:
        parse(text)
    assert message in str(exc.value)


def test_dump_round_trips_generated_headers():
    meta = {"type": "trajectory", "match": "EXACT", "threshold": 1.0,
            "expected": [{"tool": "a", "args": {"x": 1}}, {"tool": "b"}],
            "tags": ["one", "two words"], "note": "has: colon"}
    text = dump(meta, "body text")
    assert parse(text).meta == meta
