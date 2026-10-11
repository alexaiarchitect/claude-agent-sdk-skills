# How the judge is called, and what that costs

An `llm` grader is one extra model call per sample per run. It is the only
grader that costs anything, so the way it is configured decides most of a
suite's price.

## The call

```python
query(prompt=criteria + evidence,
      options=ClaudeAgentOptions(
          model=judge_model,
          tools=[], allowed_tools=[],
          max_turns=1,
          permission_mode="dontAsk",
          setting_sources=[], strict_mcp_config=True,
          effort="low",
          output_format={"type": "json_schema", "schema": VERDICT}))
```

with

```python
VERDICT = {"type": "object",
           "properties": {"verdict": {"enum": ["PASS", "FAIL"]},
                          "reason": {"type": "string"},
                          "evidence": {"type": "array", "items": {"type": "string"}}},
           "required": ["verdict", "reason"]}
```

Five of those options are not decoration:

* **`tools=[]` as well as `allowed_tools=[]`.** `allowed_tools` only governs
  prompting; `tools=[]` is what actually disables the built-ins. A judge with
  `Bash` available is a judge that can go and check.
* **`strict_mcp_config=True`.** Without it, ambient MCP servers reach a judge
  that was meant to be tool-free.
* **`setting_sources=[]`.** Without it a judge call loaded 21 KB of the host's
  ambient configuration — and cost 17x more for the same verdict.
* **`effort="low"`.** A PASS/FAIL question about text in front of it does not
  need deliberation; higher effort buys a longer `reason`, not a better
  verdict.
* **`output_format`.** The verdict comes back as a parsed object on
  `ResultMessage.structured_output`, so nothing has to parse "PASS" out of
  prose. A judge that answers in a sentence is a judge whose verdict depends on
  a regex.

## The same credential

The judge runs through the same SDK and the same credential as the agent. On a
subscription that means judge calls draw on the same usage window: a nightly
tier with three samples over twenty cases is sixty judge calls competing with
the agent's own runs for the same quota. That is why `concurrency` stays at 1
and why the `pr` tier carries no judge graders.

## Samples and voting

`judge.samples` with `judge.vote: majority` is the default at 3. Keep it odd —
majority over an even number can tie, and `CFG012` says so.

A judge verdict is a distribution, not a measurement. One sample on a
borderline reply flips between runs for reasons unrelated to the agent, and a
suite full of single-sample judges reports flakiness that is entirely its own.

Cost scales linearly with samples; stability improves sub-linearly. Three is
the working default, five for a case that gates a release, and one only for a
criterion so sharp that it cannot be read two ways — at which point a `regex`
grader is usually cheaper and more stable.

## Judge model ≠ agent model

The default for both is `claude-sonnet-5-5`, and `CFG013` reports it as a note
rather than a warning for exactly that reason: the decided defaults collide.

The argument for separating them: a model grading its own output shares its
blind spots. A failure mode it cannot see, it also cannot mark — most visibly
with formatting and hedging conventions it considers normal.

The argument against: two models make verdicts harder to compare across a model
upgrade, and a cheaper judge is a weaker one.

**The cheap option, as of 2026-10-11, is `claude-haiku-5-5`** — $0.10 in and
$0.50 out per Mtok against Sonnet 5.5's $2 / $10, with a 1M context window by
default on every plan and no `[1m]` suffix needed. Two caveats before you reach
for it: its price is a *from* price, because a prompt over 100K tokens costs
more per token, so a judge that reads a whole transcript is not necessarily
twenty times cheaper; and it needs Claude Code **2.1.293+** (the `haiku` alias
resolves to it on the Anthropic API from that release; Bedrock, Vertex, Foundry
and Claude Platform on AWS still resolve `haiku` to Haiku 4.5, which is
retiring). It is the right judge for a yes/no check on short output, and the
wrong one for a rubric that needs the failure explained. **The default does not
change**: `DEFAULT_JUDGE_MODEL` stays `claude-sonnet-5-5` so scores stay
comparable with the ones already recorded. Name Haiku 5.5 per grader instead.

Note that `claude plugin eval` made the opposite choice: its `--judge-model`
default is now "the model Claude Code uses for background tasks", which is not a
fixed id. Pin it — `--judge-model claude-sonnet-5-5` — whenever a plugin-eval
score has to be comparable with an earlier one.

Pick deliberately. `CFG010` and `CFG011` catch the third case, which is the one
that actually breaks: a judge model that is retiring, or already retired, so
every judge call fails and every judged case reports `NOT_EVALUATED`.

## Where judge graders belong

| Tier | Judges? | Why |
|---|---|---|
| `pr` | no (`CFG030` warns) | every pull request would pay; free graders catch the failures that matter most |
| `nightly` | yes | reliability needs repeated runs, and repeated runs are where a judge earns its cost |

A judged case is `judge`-tier automatically — the tier of a case is the
cheapest tier that can run it, derived from its graders, never declared.

## When the judge is unreachable

A judge call that fails (retired model, usage limit, backend error) makes the
grader `NOT_EVALUATED`, not `FAILED`. Nothing was measured, so nothing
regressed; the suite exits 3 and the result files say which graders were never
scored.

Sources: `.dev/CONTRACTS.md` §9 (the judge call, confirmed callable as written,
and the measured 17x ambient-config cost) and §3 (the `judge` config block);
`lib/agent_sdk_skills/eval_config.py` (`CFG010`-`CFG013`, `CFG030`,
`VOTE_MODES`); `lib/agent_sdk_skills/graders.py` (`TIER_JUDGE`, the `llm`
spec); https://code.claude.com/docs/en/agent-sdk/structured-outputs
(`output_format`); https://code.claude.com/docs/en/agent-sdk/python
(`query`, `ClaudeAgentOptions`);
https://platform.claude.com/docs/en/about-claude/models/overview and
https://code.claude.com/docs/en/model-config#haiku-5-5-context-window-and-pricing
(Haiku 5.5's price, context window and the 2.1.293 alias);
https://code.claude.com/docs/en/plugin-evals (the `--judge-model` default).
Re-read 2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs.
