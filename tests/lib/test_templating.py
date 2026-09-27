"""Templates never leave a placeholder behind, and write plans never clobber by surprise."""

import pytest

from agent_sdk_skills.templating import TemplateError, WritePlan, placeholders, render


def test_render_fills_every_placeholder_and_refuses_unknown_ones():
    assert render("m={{MODEL}} n={{ N }}", {"MODEL": "claude-sonnet-5-5", "N": "3"}) == "m=claude-sonnet-5-5 n=3"
    with pytest.raises(TemplateError):
        render("{{MISSING}}", {})
    assert render("{{MISSING}}", {}, strict=False) == "{{MISSING}}"


def test_github_expressions_are_not_placeholders():
    text = "group: evals-${{ github.ref }}\nmodel: {{MODEL}}"
    assert placeholders(text) == {"MODEL"}


def test_write_plan_skips_existing_files_unless_forced(tmp_path):
    existing = tmp_path / "eval_config.json"
    existing.write_text("{}")
    plan = WritePlan()
    plan.add(existing, "{\"a\": 1}")
    plan.add(tmp_path / "new.md", "hello")
    assert [i.action for i in plan.items] == ["skip", "create"]
    assert plan.apply() == [str(tmp_path / "new.md")]
    assert existing.read_text() == "{}"
    forced = WritePlan()
    forced.add(existing, "{\"a\": 1}", force=True)
    assert forced.items[0].action == "overwrite"
    assert "## Write plan" in forced.to_md()
