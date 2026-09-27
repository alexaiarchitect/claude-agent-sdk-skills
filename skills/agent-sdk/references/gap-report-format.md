# The gap report

Every inspection script in this plugin prints the same structure, as markdown
for the user (`--format md`) or JSON for a skill to branch on (`--json`).

## Shape

```json
{
  "schema": "agent-sdk-skills.gap-report/1",
  "subject": "/path/that/was/inspected",
  "skill": "eval-review",
  "discovered": {"layout": {...}, "environment": {...}, "evals": {...}},
  "findings": [
    {
      "id": "EVC003",
      "severity": "error",
      "area": "evals",
      "path": "evals/refuse-double-booking/prompt.md",
      "locator": "overrides.permision_mode",
      "message": "what is wrong, in one sentence",
      "fix": "what to do instead, and why it matters",
      "source": "https://code.claude.com/docs/en/agent-sdk/python#claudeagentoptions"
    }
  ],
  "gaps": [{"id": "GAP-EVALS", "what": "...", "why": "...", "recommendation": "..."}],
  "options": [{"key": "1", "label": "...", "recommended": true, "cost": "free",
               "writes": ["..."], "runs": ["..."]}],
  "summary": {"errors": 1, "warnings": 3, "infos": 2}
}
```

## Findings versus gaps

A **finding** is something present and wrong: a retired model id, an override
naming an option the SDK does not have, a hook that returns the wrong shape. A
**gap** is something absent: no eval cases, no config, no runner copy, no CI.
Findings have a location; gaps have a recommendation.

## Severity

| | Meaning | Example |
|---|---|---|
| 🔴 `error` | the SDK will reject it, the run cannot work, or the result would be wrong | `overrides` names a field `ClaudeAgentOptions` does not have (a dataclass raises `TypeError` on an unknown keyword); a retired model id; `import claude_code_sdk` |
| 🟠 `warn` | it runs, but not the way you meant, or it will break later | `allowed_tools` without `disallowed_tools`, so unlisted tools stay available; a retiring model; a stale runner copy |
| 🔵 `info` | worth knowing, no action implied | runs draw on a subscription, so costs are estimates |

The distinction that matters most here: a mistake in an eval case's
`overrides` is caught by this plugin **before** a session starts, because a
session that starts is already spending.

## Finding id prefixes

| Prefix | Area | Emitted by |
|---|---|---|
| `ENV###` | credentials, interpreter, `.env`, model env | discovery, `check_env.py` |
| `AGT###` | agent source: entry point, model ids, secrets, legacy SDK | `lint_agent.py`, discovery |
| `OPT###` | `ClaudeAgentOptions` values: tools, permissions, limits, settings | `lint_agent.py` |
| `HOK###` | hook callbacks and matchers | `lint_harness.py` |
| `MCP###` | MCP servers, in-process tools, mocks | `lint_harness.py`, `validate_sim.py` |
| `EVC###` | eval cases: frontmatter, graders, overrides | `validate_cases.py`, discovery |
| `CFG###` | `eval_config.json`: judge, tiers, budgets | `validate_config.py` |
| `RES###` | results and traces | `summarize_results.py` |
| `CI###` | workflows and the pytest gate | `lint_workflows.py` |
| `SIM###` | personas, faults, mock servers | `validate_sim.py` |
| `SUB###` | subagent definitions and their caps | `lint_harness.py` |
| `HST###` | hosting readiness: credentials, isolation, limits, telemetry, images | `deploy_check.py` |
| `DEP###` | the runner copy and the `agent-sdk-dev` plugin | `check_runner.py`, discovery |

Numbering is banded in decades by sub-area, so new checks slot in without
renumbering. Ids are stable across releases, so a skill may branch on them and
a test may assert them.

## Exit codes

Identical in every script:

| Code | Meaning |
|---|---|
| 0 | no errors |
| 1 | errors found, or evals below threshold |
| 2 | usage or environment error (bad path, no interpreter, import failure) |
| 3 | inconclusive — results exist but only `NOT_EVALUATED`, or a usage limit or cost ceiling stopped the run |

Code 3 exists because "the judge could not be reached" or "the plan's usage
limit was hit" is a different problem from "the agent regressed", and a CI gate
should be able to treat them differently.

---

Sources: this plugin's `lib/agent_sdk_skills/report.py`.
