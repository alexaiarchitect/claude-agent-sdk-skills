# Every validation finding, and why it is one

Ids are stable across releases, so a report, a test and a conversation can all
name the same problem. `EVC` is cases and graders, `CFG` is the config, `MCP`
is mocks and servers, `DEP` is the runner copy.

Severity means what it says: an **error** stops the thing from working, a
**warning** makes it work while proving less than it appears to, and a **note**
is context.

## Cases — `EVC0xx`

| id | sev | trigger | why it matters |
|---|---|---|---|
| `EVC001` | error | no prompt body, no `turns`, no `simulated_user` | there is nothing to send; the case cannot run |
| `EVC002` | mixed | unknown frontmatter key; a key of the wrong type; a body that `turns` makes unreachable; two cases with the same `name` | a misspelled key is silently ignored, and duplicate names overwrite each other's results |
| `EVC003` | error | `overrides` names something that is not a `ClaudeAgentOptions` field | the typo would be a silent no-op discovered after paying for the run |
| `EVC004` | error | `overrides` names a real option the runner owns | those are the levers that make the run reproducible |
| `EVC005` | warn | a `prompt.md` that is not inside a case directory | it never runs, and nothing else says so |
| `EVC006` | error | both `turns` and `simulated_user` | two incompatible ways to drive the session |
| `EVC007` | error | `env` is not a mapping, or a key does not start `EVAL_` | the prefix is what keeps a case from reaching into the developer's environment |
| `EVC010` | error | unknown grader `type` | nothing else about the grader can be checked |
| `EVC011` | error | a required grader field (or `one_of` group, or the `llm` body) is missing | the grader cannot be evaluated |
| `EVC012` | error | a `target` this type cannot read, an enum value the runner does not implement, a pattern that does not compile, a malformed `expected` | the check would not do what the file says |
| `EVC020` | warn | a grader names a tool neither the agent nor a mock provides | `no_tool` then passes forever and `tool_used` fails forever |
| `EVC030` | info | no `category` | tier filters and coverage reports group on it |
| `EVC031` | warn | a `category` outside the five | same, plus a probable typo |
| `EVC040` | error | a `trajectory` grader on a simulated-user case | the user's words vary per run, so the tool path cannot be fixed |
| `EVC041` | warn | a restraint-shaped case with no trace-level check, or one scored with a lenient `IN_ORDER`/`ANY_ORDER` trajectory | a model that called the tool and then apologized passes |
| `EVC042` | mixed | a deprecated override, `allowed_tools` containing `"Skill"`, or an override of the isolation defaults | the first two stop working; the third makes results machine-dependent |
| `EVC050` | warn/error | judge criteria the linter objects to: vague, compound, unobservable, graded, or with no FAIL clause | an unstable criterion produces an unstable verdict |
| `EVC060` | warn | a case with no graders | it can never fail, so it measures nothing |
| `EVC070` | warn | `evals/results/` is not gitignored | traces carry prompt and tool-result text |

`EVC020` is **skipped, not guessed**, when the agent's tool list could not be
read statically. An empty set would mean "the agent exposes nothing" and would
bury every real finding under false ones; the report says the check was skipped
and why.

## Config — `CFG0xx`

| id | sev | trigger | why it matters |
|---|---|---|---|
| `CFG001` | mixed | no config; no `agent`; an unknown `credential` or `on_usage_limit`; a malformed `trace` block | the run has no model pin, no entry point, or a setting the runner cannot honour |
| `CFG002` | error | the file is not valid JSON | nothing downstream can be checked |
| `CFG003` | error | no `schema`, or an unknown one | the schema is what lets both sides refuse a file they cannot read instead of misreading it |
| `CFG010` / `CFG011` | warn / error | the judge model is retiring / retired | a retired judge makes every judged case `NOT_EVALUATED` |
| `CFG012` | mixed | `judge` malformed, `samples < 1`, an even `samples`, an unknown `vote` | majority voting over an even number can tie |
| `CFG013` | info | the judge and the agent use the same model | a model grading its own output shares its blind spots |
| `CFG020` / `CFG021` | mixed | no `tiers`, an unknown tier name, a tier that does not say which grader tiers it runs | a tier nobody can select, or one that runs everything |
| `CFG022` / `CFG023` | error | a threshold outside [0,1]; `runs` or `pass_k` not a positive integer; `pass_k` above `runs` | a threshold that can never be met |
| `CFG030` | warn | the `pr` tier includes judge graders | every pull request pays for judge calls |
| `CFG040` | mixed | no `budget`, a non-positive ceiling, an unknown `on_not_evaluated`, per-run above total | a runaway case can spend a week's quota |
| `CFG041` | mixed | `concurrency` below 1, or above 1 on a subscription credential | parallel runs race each other into one usage window, and the rate limit looks like a flaky agent |
| `CFG042` | mixed | no `isolation` block, `setting_sources` loading ambient settings, `strict_mcp_config` false | measured 17x cost, and results that describe the machine |
| `CFG050` | warn | `runner_version` disagrees with the installed copy | the file and the code that reads it are different generations |
| `CFG060` | mixed | no `model`, a model that resolves to nothing, a retired or retiring id, a hardcoded id | inheriting Claude Code's default is a different model on different machines |

## Mocks and servers — `MCP0xx`, `SIM0xx`

| id | sev | trigger |
|---|---|---|
| `MCP020` | warn | a mock for a server the agent no longer has |
| `SIM010`-`SIM013` | mixed | a mock tool with no schema, a malformed schema, an unresolvable `{{file:…}}`, an `expect` that cannot match |

## The runner copy — `DEP0xx`

| id | sev | trigger |
|---|---|---|
| `DEP001` | warn | the copy is older than the plugin's runner |
| `DEP002` | error | the copy is newer — it may write result files this plugin cannot read |
| `DEP003` | error | no copy at all; nothing can run |
| `DEP004` | warn | a file's hash differs from `MANIFEST.sha256`: someone edited it in place |
| `DEP010` | info | the official `agent-sdk-dev` plugin is not installed |

## Reading a report

Order matters more than count. Fix in this order:

1. **Load errors** (`EVC001`, `EVC002` type errors, `CFG002`) — nothing else is
   trustworthy until the files parse.
2. **Contract errors** (`EVC003`, `EVC004`, `EVC010`-`EVC012`, `CFG003`,
   `CFG022`/`CFG023`) — the run would fail or score wrongly.
3. **Silent-pass warnings** (`EVC020`, `EVC041`, `EVC060`) — these are the ones
   that make a green suite meaningless.
4. **Everything else.**

`--strict` promotes warnings into the exit code. Use it in CI, where a grader
that quietly asserts nothing is worse than a red build.

Sources: `lib/agent_sdk_skills/evalcase.py`, `graders.py`, `eval_config.py`,
`mocks.py` and `runner_version.py` (every id, its severity and its fix text are
defined there and this table is derived from them); `.dev/CONTRACTS.md` §1-§4
and §12 (the contracts the ids enforce).
