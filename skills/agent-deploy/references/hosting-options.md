# Hosting: the subprocess model, and four session patterns

## Everything follows from one fact

`query()` does not call an API. It spawns a separate `claude` CLI process and
talks to it over stdio. That subprocess owns a shell, a working directory, and
a JSONL transcript on local disk.

```
client → your app → (stdio) → claude CLI subprocess → HTTPS → api.anthropic.com
                                     ↓
                               local disk
```

Consequences, all of which shape the deployment:

- **one session is one subprocess.** N concurrent sessions is N process trees,
  each with its own transcript file. Concurrency on a host is bounded by RAM,
  not by request rate.
- **they inherit your application's working directory** unless you pass a
  distinct `cwd` per session. In a shared container that is how one tenant's
  artefacts land in another tenant's view (`HST022`).
- **state is local and ephemeral.** Nothing below survives a restart, a
  scale-down, or a move to another node:

  | State | Default location |
  |---|---|
  | session transcripts | `~/.claude/projects/`, or `projects/` under `CLAUDE_CONFIG_DIR` |
  | `CLAUDE.md` memory | `~/.claude/CLAUDE.md` (user), the working directory (project) |
  | working-directory artefacts | the session's `cwd` |

  A `SessionStore` adapter mirrors **transcripts only** — not memory files, not
  artefacts. Those need a volume or an object-store sync.
- **the agent does not listen on the network.** Your application exposes the
  port and calls the SDK internally.

## Four session patterns

| Pattern | Container lives | Good for | Needs |
|---|---|---|---|
| **Ephemeral** | one task | bug-fix runs, document extraction, media transforms | a one-shot entrypoint reading the task from an environment variable; `max_turns` so the container exits |
| **Long-running** | indefinitely, many sessions at once | email triage, chat bots, anything serving continuous traffic | `ClaudeSDKClient` held open per session; a load balancer pinning each session to one container by consistent hashing on `session_id`; RAM sized for peak concurrent sessions |
| **Hybrid** | per burst, hydrating from a store | project managers, deep research, support agents that resume across hours | a `SessionStore` — **required**, not optional: shutting down without one loses the transcript |
| **Multi-agent** | one container, several agents | fan-out work | subagent depth and concurrency caps, and a spend cap |

Ephemeral is the default answer. Reach for long-running only when the latency
of a cold start is the problem, because everything else about it — pinning,
eviction, memory growth — is harder.

## Patterns from Anthropic's own agent infrastructure

Two engineering write-ups describe how Anthropic hosts agents; they are design
rationale, and the SDK mechanics that implement them are in the docs.

- **Decouple the brain from the hands** (Managed Agents, 2026-04-08). Keep three
  things apart: the **session**, a durable, append-only event log that lives
  outside the context window; the **harness**, the loop calling Claude, kept
  stateless so a crashed one resumes from the log by session id; and the
  **sandbox**, called like any other tool through an `execute(name, input)`-style
  interface, so a dead container is a retryable tool error rather than a lost
  session. Provision sandboxes **lazily**, only when a tool call needs one (the
  article reports large time-to-first-token gains). **Credentials never inside
  the sandbox**: wire them into the resource at setup, or keep them in a vault
  and reach external services through a proxy that adds them per call. In SDK
  terms: a `SessionStore` (or the transcript under a per-session
  `CLAUDE_CONFIG_DIR`) is the log, resume is `resume=<session_id>`, the egress
  proxy holds the credentials (`secure-deployment.md`).
- **Production lessons from the research system** (2025-06-13). Agents are
  stateful and errors compound, so **resume from a checkpoint** where the error
  happened rather than restart; tell the agent a tool is failing and let it
  adapt; deploy with **rainbow deployments** — shift traffic gradually while old
  and new versions both run, so in-flight sessions finish on the code they
  started on; and keep **full tracing** of decisions and tool calls without
  reading conversation contents (`observability-otel.md`).

## Provisioning

| Concern | Starting point |
|---|---|
| Runtime | Python 3.10+; both SDKs bundle a native Claude Code binary, so no separate Node.js is needed for the spawned CLI |
| Resources | **1 GiB RAM, 5 GiB disk, 1 CPU per agent** — a floor for a freshly started instance, not a ceiling. Memory grows with session length and tool activity |
| Scaling | `agents per host = (host RAM − overhead) / per-session RAM ceiling`. Measure the ceiling by running a representative session to your target length and recording peak RSS |
| Network out | HTTPS to `api.anthropic.com`, or your provider's regional endpoint; plus whatever your MCP servers need. In production, route it through an egress proxy that allowlists domains, injects credentials and logs |
| Network in | an HTTP or WebSocket port on your application, behind a gateway that authenticates. The agent should receive pre-authenticated requests and never validate user tokens itself |
| Updates | the bundled CLI is pinned to the SDK package version, so updating the SDK is how you update the CLI. Take patch releases continuously; read the changelog before a minor |

## Cost, in proportion

Token cost typically dominates container cost by an order of magnitude or more:
a minimally provisioned container runs roughly $0.05/hour, while one long agent
session can spend dollars. Optimise the ceilings and the isolation before you
optimise the instance type.

Two figures to date rather than quote. `max_budget_usd` is a **soft** cap: the
running estimate can pass the value before the query stops, so the instance
budget needs headroom above it. And the cache-read price depends on which CLI
the image carries — the platform list price for a Sonnet 5.5 cache read is
**$0.10/Mtok**, which the CLI 2.1.310 bundled with `claude-agent-sdk` 0.2.174
charges (measured 2026-10-24, as 2.1.301 did on 2026-10-17), while the 2.1.294 bundled with 0.2.165 charged
**$0.20/Mtok** (measured 2026-10-11). Pin the SDK version in the image and
record it beside any cost figure.

A host that embeds Claude Code and routes the model provider itself sets
`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`: Claude Code then ignores the provider,
endpoint and credential variables (`CLAUDE_CODE_USE_BEDROCK`,
`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`) in settings files and the
model-selection keys in managed settings, so neither can override the host's
routing. Large requests to api.anthropic.com are gzip-compressed even with
telemetry off from 2.1.300; `CLAUDE_CODE_GZIP_REQUEST_BODIES=0` turns that off
for a proxy that cannot decompress. Resuming a headless or SDK session after a
compaction lost recent messages or brought back pre-compaction history in two
cases fixed in 2.1.300 — another reason to pin a CLI at least that new when a
`SessionStore` resumes sessions across containers. Memory is the other
compaction cost: from 2.1.310 non-interactive sessions (`-p`, Agent SDK) use
less memory compacting when the transcript file is very large, and 2.1.304 sends
the first request after resuming a large compacted session sooner — size a
long-running agent's container on a CLI at least that new. From **2.1.311** a
standard-context session whose request passes 200K tokens compacts and
continues instead of stopping with "Usage credits required for 1M context".

**Bedrock, Vertex, Foundry (from the changelog; `CLAUDE_CODE_MODEL_CATALOG` is
not on the env-vars page read 2026-10-29).**
From 2.1.311 Claude Code on those providers (and Mantle) loads model settings
from a signed file on downloads.claude.ai; `CLAUDE_CODE_MODEL_CATALOG=off`
turns that off, which an image without that egress needs. From 2.1.312 a model
name Claude Code does not recognise there (a custom deployment name, an
inference-profile ARN) gets the shorter system prompt even when it fronts
Sonnet or Haiku; `CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT=0` keeps the full prompt.
These ship in CLIs newer than the 2.1.310 bundled with 0.2.174, so they apply
only with `cli_path` pointing at a newer `claude`.

## Known limitations worth planning around

- Local disk is the default for every kind of state, and it is not durable.
- A **background Bash command** in an unattended session can run far longer than
  a foreground one: default **1800000 ms**, ceiling **7200000 ms** (Claude Code
  **2.1.285+**), and `BASH_DEFAULT_TIMEOUT_MS`/`BASH_MAX_TIMEOUT_MS` above their
  defaults raise both. Size the container's lifetime and its token budget for
  that, not for the 600000 ms foreground cap.
- `permission_mode` left unset could start a headless session that fetches no
  feature flags in **`auto`** on 2.1.285–2.1.301, where broad allow rules are
  dropped; from 2.1.302 such runs "start in Manual mode" (`default`), where an
  unapproved call is denied. Pass it explicitly.
- A session pinned to a container dies with it unless a `SessionStore` is
  configured.
- `SessionStore` mirror writes are best-effort: when a batch cannot be
  delivered the SDK drops it, emits a `{"type": "system", "subtype":
  "mirror_error"}` message and continues. Alert on those if durability matters.

## Where to start

The hosting cookbook has deployable code for local Docker, Modal and
Kubernetes. Choose a session pattern here, a deployment target there, and run
`deploy_check.py` before you build the image.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/hosting> (the subprocess
model, state on local disk, the four session patterns, provisioning, resources,
network, scaling, cost, known limitations),
<https://code.claude.com/docs/en/agent-sdk/session-storage> (SessionStore,
dual-write, `mirror_error`), <https://code.claude.com/docs/en/agent-sdk/sessions>,
<https://code.claude.com/docs/en/agent-sdk/quickstart> (the install note about
the bundled binary),
<https://code.claude.com/docs/en/agent-sdk/python#bash> (the background-command
limit), <https://code.claude.com/docs/en/permission-modes>,
<https://platform.claude.com/docs/en/about-claude/models/overview> (cache-read
percentages); `claude-agent-sdk` 0.2.174
`_internal/transport/subprocess_cli.py:237-264` (CLI discovery), `types.py:2451`
(`cwd`), `:2759` (`session_store`), `:2411` (`max_budget_usd`), `:2380`
(`permission_mode`); <https://code.claude.com/docs/en/env-vars>
(`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.300 gzip
and resume fixes, 2.1.302 unset-mode default, 2.1.304 resume and 2.1.310
compaction memory, 2.1.311 200K compaction and `CLAUDE_CODE_MODEL_CATALOG`,
2.1.312 `CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT`);
<https://www.anthropic.com/research/managed-agents> ("Scaling Managed Agents with
stable interfaces", 2026-04-08, session log outside the context window,
stateless harness, sandbox as a tool, credentials outside the sandbox, lazy
provisioning); <https://www.anthropic.com/research/multi-agent-research-system>
("How we built our multi-agent research system", 2025-06-13, resume from
checkpoints, rainbow deployments, tracing without contents). The $0.20/Mtok cache-read price of the bundled CLI 2.1.294
was measured by this plugin on 2026-10-11, the $0.10/Mtok of 2.1.301 on
2026-10-17 and of 2.1.310 on 2026-10-24. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs; re-read 2026-10-24 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs. Re-read 2026-10-29 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
