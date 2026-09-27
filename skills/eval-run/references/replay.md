# Replaying a saved trace

A trace (`<case>.<n>.trace.jsonl`) is the complete record of one run: the
options the session started with, every user and assistant turn, every tool
call and result, hook events, rate-limit events, and the result with its cost.
The free graders only need that record, so they can be re-run against it
without a session:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/replay_trace.py <project> evals/results/<ts>/<case>.1.trace.jsonl
```

## When it is worth doing

- **A grader changed.** Tightening `trajectory` from `IN_ORDER` to `EXACT`, or
  adding a `no_tool`, should be checked against the last passing trace before
  paying for a new run.
- **A case was renamed or its overrides changed.** Replay says whether the old
  evidence still satisfies the new assertions.
- **Regression pinning.** After a failure is understood, the failing trace can
  be replayed against a new regression case to confirm the case catches it.
- **Cost-free CI sanity.** A `pr` tier can replay stored traces of the last
  nightly run to catch grader mistakes without spending.

## What replay cannot do

- Judge graders need a model call; they report `NOT_EVALUATED` unless
  `--judge` is passed, which spends.
- A trace records what the agent did with the tools it had. A case that now
  mocks a tool differently is not answered by an old trace.
- An imported Claude Code session (`/agent-sdk:agent-debug`'s
  `import_session.py`) carries no cost or terminal fields, so `budget` and
  `terminal` graders report `NOT_EVALUATED` on it.

## Output

The runner's `replay` prints one JSON object: `case`, `trace`, `graders`
(name, type, status, score, reason), `status`, and exits 0/1/3 like a run.

---

Sources: this plugin's `runner/agent_sdk_evals/cli.py` (`replay`) and
`.dev/CONTRACTS.md` §5 (trace events).
