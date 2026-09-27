---
name: agent-deploy
description: >-
  Get a Claude Agent SDK (Python) agent ready to be hosted rather than run on a
  laptop. Checks the credential path (a claude.ai subscription credential is not
  permitted for a third-party hosted agent, so an API key, an
  `ANTHROPIC_BASE_URL` gateway or a cloud provider is required), turn and spend
  ceilings, subagent depth and concurrency caps, multi-tenant isolation
  (`setting_sources=[]`, auto memory, per-session `cwd`, per-tenant config
  directory), OpenTelemetry configuration, credential literals or a copied
  `.env` in a Dockerfile or compose file, and whether a resumable design has a
  SessionStore. Generates a Dockerfile with a non-root user and no secrets, and
  a locked-down settings file with the egress note. Findings are the `HST0xx`
  band. Use when asked to "deploy my agent", "dockerise this", "run this in
  Kubernetes", "is this safe to host", "can I use my Claude subscription for
  this", "how do I cap what a hosted agent spends", "add telemetry", or "isolate
  tenants". Don't use for local eval runs and CI gates (use
  `/agent-sdk:eval-ci`), designing hooks, permissions or MCP servers (use
  `/agent-sdk:agent-harness`), or a static code review (use
  `/agent-sdk:agent-review`).
argument-hint: "[project-dir]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Skill, Bash(python3 *)
---

# Hosting an Agent SDK agent

`query()` does not call an API. It spawns a `claude` CLI subprocess that owns a
shell, a working directory and a transcript on local disk. Every deployment
question follows from that: one session is one process, state is local and
ephemeral, and the agent's environment is the agent's capability.

Two of the findings here cannot be fixed after the fact — a credential in an
image is compromised the moment the image is pulled, and a subscription
credential in a product is a policy problem, not a configuration preference. So
this runs before the build, not after.

`${CLAUDE_SKILL_DIR}` is set by the skill runtime to this skill's own
directory. Use it verbatim in every command below; a sibling skill's scripts
are at `${CLAUDE_SKILL_DIR}/../<skill>/scripts/`.

## Flow

1. **Check.**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/deploy_check.py <project> --target docker
   ```

   `--target k8s` or `--target ci` changes the advice, not the rules. `--json`
   to branch on ids.

2. **Report** errors first, and say which ones are irreversible. `HST001` and
   `HST040` both mean "rotate something", not "edit a line".

3. **Options.** Generate the container definition, generate the locked-down
   settings, or fix the findings in the agent's own code. All generation here
   is free and writes at most three files.

4. **Confirm, then generate.** Both generators print a write plan and support
   `--dry-run`. Existing files are skipped unless the user asks for `--force`.

5. **Verify.** Re-run `deploy_check.py` against the generated files.

## What gets checked

| Area | Ids | The question |
|---|---|---|
| credentials | `HST001`, `HST002`, `HST040`, `HST041` | can this run at all, and is anything secret in the image |
| ceilings | `HST010`, `HST011`, `HST012` | what bounds one request, and one subagent tree |
| isolation | `HST020`, `HST021`, `HST022` | can one tenant's context reach another's session |
| evidence | `HST030` | will you be able to see what happened |
| state | `HST050` | does a resumable design survive a restart |

## The `HST0xx` band

| Id | Severity | Trigger |
|---|---|---|
| `HST001` | **error** | a hosted deployment configured to use a subscription credential (`CLAUDE_CODE_OAUTH_TOKEN`) |
| `HST002` | **error** | no credential path for the container: no API key, no gateway base URL, no provider switch |
| `HST010` | warn | no `max_turns` |
| `HST011` | warn | no `max_budget_usd` |
| `HST012` | info | subagents defined and neither the depth nor the concurrency cap set |
| `HST020` | warn | `setting_sources` is not `[]` for a hosted or multi-tenant agent |
| `HST021` | info | auto memory not disabled |
| `HST022` | info | no per-session `cwd` |
| `HST030` | info / warn | no OTEL configuration (info); exporters set without `CLAUDE_CODE_ENABLE_TELEMETRY` (warn) |
| `HST040` | **error** | a credential literal in a Dockerfile or compose file |
| `HST041` | **error** | `.env` copied into the image, directly or by `COPY . .` |
| `HST050` | info | a resumable design with no `SessionStore` |

## Decision rules

- **A subscription credential is for your own machine.** Anthropic's note is
  explicit, and two practical facts back it: an OAuth token is tied to one
  person's plan, and it expires. Say all three; do not soften it into a
  preference.
- **The proxy pattern beats a secret manager.** A gateway that injects the key
  outside the container means the agent never holds it, the endpoints are
  allowlisted, and the requests are logged. `ANTHROPIC_BASE_URL` is one line.
- **`setting_sources=[]` is not full isolation.** It covers user, project and
  local settings and `CLAUDE.md`. Builtin plugins, managed policy and
  `~/.claude.json` still load; MCP needs `strict_mcp_config=True`; auto memory
  needs its own environment variable. Promise exactly that much.
- **`setting_sources` does not control egress at all.** A container with a
  shell reaches whatever its network policy allows. That is a proxy's job.
- **Ceilings before instance types.** Token cost dominates container cost by an
  order of magnitude or more.
- **`max_turns` is not a hard stop.** Measured, `max_turns=1` produced
  `num_turns=2`. Assert on `terminal_reason`, not on a turn count.
- **Telemetry content flags stay off** unless the pipeline is approved to store
  what the agent reads. Structure is free; content is a decision.

## References

| Question | File |
|---|---|
| The subprocess model, the four session patterns, resources and scaling | [hosting-options.md](references/hosting-options.md) |
| Isolation technologies, the credential proxy, egress, what `setting_sources` misses | [secure-deployment.md](references/secure-deployment.md) |
| `max_turns`, `max_budget_usd`, subagent caps, cache TTL, subscription vs API billing | [cost-controls.md](references/cost-controls.md) |
| OTEL variables, spans, the beta flag, sensitive-data flags, OpenInference | [observability-otel.md](references/observability-otel.md) |

The credential detection and cost-basis rules are shared with the router:
`${CLAUDE_SKILL_DIR}/../agent-sdk/references/environment.md`.

## Scripts

| Command | Does | Exit codes |
|---|---|---|
| `scripts/deploy_check.py <project> [--target docker\|k8s\|ci] [--json]` | the `HST0xx` review | 0 no errors, 1 errors, 2 nothing to check |
| `scripts/gen_dockerfile.py [<project>] [--python 3.12] [--entry agent.py] [--dry-run] [--force] [--json]` | writes a Dockerfile, `.dockerignore` and `requirements.txt` | 0 written or planned, 1 nothing written, 2 bad arguments |
| `scripts/gen_secure_settings.py [<project>] [--allow ...] [--deny ...] [--dry-run] [--force] [--json]` | writes `agent_settings.json` and `.env.deploy.example` | 0 written or planned, 1 nothing written, 2 bad arguments |

## Completion checklist

- [ ] `deploy_check.py` ran and its findings were reported, errors first.
- [ ] If a subscription credential was found, the policy note was quoted, not paraphrased away.
- [ ] Any credential found in an image or compose file was described as needing rotation, not deletion.
- [ ] The isolation advice said what `setting_sources=[]` does *not* cover.
- [ ] Egress was mentioned; it is the gap no option closes.
- [ ] Every generated file was shown as a write plan and confirmed before writing.
- [ ] `deploy_check.py` was re-run afterwards and came back clean.
