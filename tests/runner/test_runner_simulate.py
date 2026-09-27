"""Scripted multi-turn, the simulated user, scaffolding and mocks inside a run."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

import claude_agent_sdk as sdk
import pytest

from agent_sdk_evals import EXIT_OK, NOT_EVALUATED, PASSED
from agent_sdk_evals import cli as cli_module
from agent_sdk_evals.simulate import Persona, SimulatedUser, build_options, build_prompt

from test_runner_cli import INIT, execute, result, text  # noqa: F401 - shared script builders


# -- the persona ------------------------------------------------------------

def test_a_persona_reads_its_defaults():
    persona = Persona.from_dict({"name": "impatient renewer", "goal": "renew an overdue loan"})
    assert persona.max_user_turns == 4 and persona.stop_marker == "DONE"
    assert persona.has_rubrics is False


def test_the_user_prompt_never_asks_the_model_to_be_the_agent():
    persona = Persona.from_dict({"name": "n", "goal": "g", "style": "terse",
                                "constraints": ["never reveal your member id"]})
    prompt = build_prompt(persona, [("user", "hello"), ("agent", "how can I help?")])
    assert "You are NOT the agent" in prompt
    assert "never reveal your member id" in prompt
    assert "You: hello" in prompt and "Agent: how can I help?" in prompt
    assert "reply with exactly DONE" in prompt


def test_the_simulated_user_gets_no_tools_and_the_same_isolation_as_the_judge():
    options = build_options(Persona(model="claude-haiku-4-5"), sdk.ClaudeAgentOptions)
    assert options.tools == [] and options.allowed_tools == []
    assert options.setting_sources == [] and options.strict_mcp_config is True
    assert options.model == "claude-haiku-4-5"


def test_the_opening_line_is_used_verbatim_and_costs_nothing():
    user = SimulatedUser(Persona(opening="I need to renew my book."), sdk)
    assert asyncio.run(user.next_turn([])) == "I need to renew my book."
    assert user.calls == 0 and sdk.calls() == []


def test_the_user_stops_on_the_marker():
    sdk.set_script([text("DONE"), result(result="DONE")])
    user = SimulatedUser(Persona(), sdk)
    assert asyncio.run(user.next_turn([("user", "hi"), ("agent", "done")])) is None


def test_the_user_stops_at_max_user_turns():
    user = SimulatedUser(Persona(max_user_turns=1), sdk)
    pairs = [("user", "hi"), ("agent", "hello")]
    assert asyncio.run(user.next_turn(pairs)) is None
    assert sdk.calls() == [], "the ceiling is checked before anything is spent"


def test_the_user_generates_a_turn_and_records_its_cost():
    sdk.set_script([text("Just renew it, please."), result(total_cost_usd=0.003)])
    user = SimulatedUser(Persona(), sdk)
    turn = asyncio.run(user.next_turn([("user", "hi"), ("agent", "which book?")]))
    assert turn == "Just renew it, please."
    assert user.cost_usd == pytest.approx(0.003) and user.calls == 1
    assert user.turns == ["Just renew it, please."]


def test_violation_rubrics_judge_the_users_turns_not_the_agents():
    from agent_sdk_evals.judge import Judge, JudgeConfig
    from agent_sdk_evals.simulate import check_rubrics

    persona = Persona(violation_rubrics=["the user never gave a payment card"])
    sdk.set_script([text("PASS"),
                    result(structured_output={"verdict": "PASS", "reason": "no card given"})])
    judge = Judge(JudgeConfig(samples=1), sdk)
    checks = asyncio.run(check_rubrics(persona, ["renew it", "no, I will not pay"], judge))
    assert checks == [{"rubric": "the user never gave a payment card", "status": PASSED,
                      "reason": "no card given", "votes": ["PASS"]}]
    prompt = sdk.calls()[0]["prompt"]
    assert "User turn 1: renew it" in prompt, "the evidence is the user's turns"
    assert "simulated user" in prompt


def test_rubrics_without_a_judge_are_simply_not_checked():
    from agent_sdk_evals.simulate import check_rubrics

    persona = Persona(violation_rubrics=["anything"])
    assert asyncio.run(check_rubrics(persona, ["a turn"], None)) == []


# -- scripted multi-turn ----------------------------------------------------

def test_scripted_turns_run_on_one_client_and_the_cost_is_diffed(project, monkeypatch):
    """`total_cost_usd` is a session running total, so turn 2's delta is the diff."""
    case = project / "evals" / "two-turns"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        '---\nname: two-turns\ncategory: memory\n'
        'turns: ["Reserve Dune for member-7", "Actually make that two copies"]\n'
        '---\n\nignored when turns is set\n')
    (case / "graders" / "answered-twice.md").write_text(
        "---\ntype: regex\npattern: two copies\nflags: i\n---\nprose\n")
    script = [
        dict(INIT, _turn=1), dict(text("Reserved one copy of Dune."), _turn=1),
        dict(result(total_cost_usd=0.004991), _turn=1),
        dict(INIT, _turn=2), dict(text("Done — two copies are now held."), _turn=2),
        dict(result(total_cost_usd=0.0061734, num_turns=2), _turn=2),
    ]
    payload, code = execute(project, script, monkeypatch, case="two-turns")
    assert code == EXIT_OK
    stored = json.loads((Path(payload["results_dir"]) / "two-turns.result.json").read_text())
    run = stored["runs"][0]
    assert run["result"]["total_cost_usd"] == pytest.approx(0.0061734), "the case total"
    assert run["result"]["cost_delta_usd"] == pytest.approx(0.0011824), "the per-turn delta"
    trace = (Path(payload["results_dir"]) / run["trace"]).read_text().splitlines()
    events = [json.loads(line) for line in trace]
    assert [e["turn"] for e in events if e["type"] == "user"] == [1, 2]
    assert len([e for e in events if e["type"] == "init"]) == 2, "init arrives per turn"
    assert [e["occurrence"] for e in events if e["type"] == "init"] == [1, 2]
    assert len(sdk.calls()) == 2 and all(c["via"] == "client" for c in sdk.calls())


# -- the simulated user inside a run ---------------------------------------

def test_a_simulated_user_case_runs_and_records_its_turns(project, monkeypatch):
    case = project / "evals" / "persona-case"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: persona-case\ncategory: adversarial\n"
        "simulated_user: personas/impatient.json\n---\n\nignored\n")
    (case / "personas").mkdir()
    (case / "personas" / "impatient.json").write_text(json.dumps({
        "name": "impatient renewer", "goal": "renew an overdue loan",
        "opening": "Renew my book.", "max_user_turns": 1, "stop_marker": "DONE",
    }))
    (case / "graders" / "answered.md").write_text(
        "---\ntype: regex\npattern: renew\nflags: i\n---\nprose\n")
    script = [INIT, text("I can renew that for you."), result()]
    payload, code = execute(project, script, monkeypatch, case="persona-case")
    assert code == EXIT_OK
    stored = json.loads((Path(payload["results_dir"]) / "persona-case.result.json").read_text())
    assert stored["runs"][0]["simulated_user_turns"] == ["Renew my book."]


def test_a_trajectory_grader_on_a_simulated_user_case_is_inconclusive(project, monkeypatch):
    case = project / "evals" / "persona-trajectory"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: persona-trajectory\ncategory: adversarial\n"
        "simulated_user: personas/p.json\n---\n\nignored\n")
    (case / "personas").mkdir()
    (case / "personas" / "p.json").write_text(json.dumps(
        {"name": "n", "goal": "g", "opening": "hello", "max_user_turns": 1}))
    (case / "graders" / "path.md").write_text(
        "---\ntype: trajectory\nexpected:\n  - tool: lookup_book\n---\nprose\n")
    payload, code = execute(project, [INIT, text("hi"), result()], monkeypatch,
                            case="persona-trajectory")
    stored = json.loads((Path(payload["results_dir"]) / "persona-trajectory.result.json").read_text())
    grader = stored["runs"][0]["graders"][0]
    assert grader["status"] == NOT_EVALUATED and "EVC040" in grader["reason"]


# -- scaffolding and mocks inside a run ------------------------------------

def test_a_scaffold_script_runs_in_the_fresh_working_directory(project, monkeypatch):
    case = project / "evals" / "with-scaffold"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: with-scaffold\ncategory: happy\n"
        "scaffold_script: printf 'seeded\\n' > seed.txt\n---\n\nread the seed\n")
    (case / "graders" / "seeded.md").write_text(
        "---\ntype: file_exists\npath: seed.txt\n---\nprose\n")
    payload, code = execute(project, [INIT, text("ok"), result()], monkeypatch,
                            case="with-scaffold")
    assert code == EXIT_OK
    stored = json.loads((Path(payload["results_dir"]) / "with-scaffold.result.json").read_text())
    assert stored["runs"][0]["graders"][0]["status"] == PASSED


def test_a_failing_scaffold_script_fails_the_run_loudly(project, monkeypatch):
    case = project / "evals" / "bad-scaffold"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: bad-scaffold\ncategory: happy\nscaffold_script: exit 3\n---\n\nx\n")
    (case / "graders" / "any.md").write_text("---\ntype: regex\npattern: x\n---\nprose\n")
    payload, code = execute(project, [INIT, text("x"), result()], monkeypatch,
                            case="bad-scaffold")
    stored = json.loads((Path(payload["results_dir"]) / "bad-scaffold.result.json").read_text())
    assert "scaffold_script exited 3" in (stored["runs"][0]["error"] or "")


def test_a_mocked_server_replaces_the_agents_own_and_is_recorded(project, monkeypatch):
    case = project / "evals" / "with-mock"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: with-mock\ncategory: happy\nmocks: [ledger]\n---\n\ncheck member-7\n")
    (case / "graders" / "any.md").write_text("---\ntype: regex\npattern: ok\n---\nprose\n")
    payload, code = execute(project, [INIT, text("ok"), result()], monkeypatch, case="with-mock")
    assert code == EXIT_OK
    servers = sdk.calls()[0]["options"].mcp_servers
    assert set(servers) == {"library", "ledger"}, "the mock is added beside the agent's own"
    assert servers["ledger"].tools[0].name == "lookup"


def test_a_missing_mock_server_is_refused_before_anything_runs(project, monkeypatch):
    from agent_sdk_evals import EvalError

    case = project / "evals" / "bad-mock"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: bad-mock\ncategory: happy\nmocks: [nowhere]\n---\n\nx\n")
    (case / "graders" / "any.md").write_text("---\ntype: regex\npattern: x\n---\nprose\n")
    with pytest.raises(EvalError):
        execute(project, [INIT, text("x"), result()], monkeypatch, case="bad-mock")


def test_faults_are_wired_into_the_run_and_recorded(project, monkeypatch):
    case = project / "evals" / "with-faults"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: with-faults\ncategory: edge\nfaults: faults/deny.json\n---\n\nwrite a file\n")
    (case / "faults").mkdir()
    (case / "faults" / "deny.json").write_text(json.dumps({"seed": 3, "faults": [
        {"id": "no-writes", "event": "PreToolUse", "tool": "Write", "action": "deny",
         "reason": "the disk is read-only in this eval"}]}))
    (case / "graders" / "hooked.md").write_text(
        "---\ntype: hook_event\nevent: PreToolUse\nmin: 0\n---\nprose\n")
    payload, code = execute(project, [INIT, text("ok"), result()], monkeypatch,
                            case="with-faults")
    options = sdk.calls()[0]["options"]
    assert "PreToolUse" in options.hooks
    stored = json.loads((Path(payload["results_dir"]) / "with-faults.result.json").read_text())
    hooked = stored["runs"][0]["graders"][0]
    assert hooked["status"] == PASSED, "the hook was installed, so the grader is decidable"


def test_a_timeout_fails_the_run_rather_than_hanging(project, monkeypatch):
    case = project / "evals" / "slow"
    (case / "graders").mkdir(parents=True)
    (case / "prompt.md").write_text(
        "---\nname: slow\ncategory: edge\ntimeout_seconds: 1\n"
        "scaffold_script: sleep 3\n---\n\nx\n")
    (case / "graders" / "any.md").write_text("---\ntype: regex\npattern: x\n---\nprose\n")
    payload, code = execute(project, [INIT, text("x"), result()], monkeypatch, case="slow")
    stored = json.loads((Path(payload["results_dir"]) / "slow.result.json").read_text())
    assert stored["runs"][0]["status"] == "FAILED"
    assert "timeout_seconds=1" in stored["runs"][0]["error"]


def test_every_run_gets_its_own_working_directory(project, monkeypatch):
    """Without this the agent writes into the project and runs see each other."""
    payload, _ = execute(project, [INIT, text("ready"), result()], monkeypatch,
                         case="echo-ready", keep_cwd=True)
    options = sdk.calls()[0]["options"]
    stored = json.loads((Path(payload["results_dir"]) / "echo-ready.result.json").read_text())
    kept = stored["runs"][0]["cwd"]
    assert options.cwd == kept, "the session's cwd is the run's own directory"
    assert Path(kept).is_dir() and str(project) not in kept
    shutil.rmtree(kept, ignore_errors=True)
