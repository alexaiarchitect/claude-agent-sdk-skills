"""Layout detection reads source and never imports it."""

from agent_sdk_skills.layout import detect_layout, scan_sdk_usage


def test_convention_fixture_is_detected(agent_dir):
    layout = detect_layout(agent_dir("good"))
    assert layout.style == "convention"
    assert layout.entry_spec == "agent:build_options"
    assert layout.example_files and not layout.legacy_modules
    assert layout.agent_modules[0].has_run


def test_drift_fixture_is_inline_and_legacy(agent_dir):
    layout = detect_layout(agent_dir("drift"))
    assert layout.style == "inline"
    assert layout.legacy_modules == [str(agent_dir("drift") / "agent.py")]
    assert layout.agent_modules[0].options_only_in_main


def test_no_evals_fixture_has_no_evals(agent_dir):
    layout = detect_layout(agent_dir("no_evals"))
    assert layout.style == "convention" and layout.evals is None and not layout.has_evals


def test_custom_builder_is_named_as_module_function(tmp_path):
    pkg = tmp_path / "svc"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "agent.py").write_text(
        "from claude_agent_sdk import ClaudeAgentOptions, query\n"
        "def make():\n    return ClaudeAgentOptions()\n"
        "async def go():\n    async for m in query(prompt='x', options=make()): pass\n"
    )
    layout = detect_layout(tmp_path)
    assert layout.style == "custom" and layout.entry_spec == "svc.agent:make"


def test_evals_dir_and_runner_copy_are_scanned(tmp_path):
    (tmp_path / "agent.py").write_text("from claude_agent_sdk import ClaudeAgentOptions\ndef build_options():\n    return ClaudeAgentOptions()\n")
    evals = tmp_path / "evals"
    (evals / "happy" / "graders").mkdir(parents=True)
    (evals / "happy" / "prompt.md").write_text("---\n---\nhi")
    (evals / "orphan").mkdir()
    (evals / "orphan" / "prompt.md").write_text("hi")
    (evals / "prompt.md").write_text("stray")
    (evals / "eval_config.json").write_text("{}")
    (evals / "runner" / "agent_sdk_evals").mkdir(parents=True)
    (evals / "mocks" / "library").mkdir(parents=True)
    layout = detect_layout(evals)         # the evals dir resolves to its parent
    assert layout.project_root == str(tmp_path)
    info = layout.evals
    assert info.case_count == 2 and info.config and info.runner_dir
    assert info.case_dirs_without_graders == [str(evals / "orphan")]
    assert info.stray_prompt_files == [str(evals / "prompt.md")]
    assert info.mocks == [str(evals / "mocks" / "library")]


def test_scan_never_raises_on_broken_source(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n")
    usage = scan_sdk_usage(bad)
    assert not usage.is_agent and usage.entry_style == "none"


def test_collection_needs_an_explicit_entry(tmp_path):
    for name in ("a", "b"):
        (tmp_path / f"{name}.py").write_text("from claude_agent_sdk import query\nasync def m():\n    async for x in query(prompt='p'): pass\n")
    layout = detect_layout(tmp_path)
    assert layout.style == "collection" and layout.entry_spec is None
