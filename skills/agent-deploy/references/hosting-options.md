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
**$0.10/Mtok** from Claude Code **2.1.296**, while the CLI bundled with
`claude-agent-sdk` 0.2.165 is **2.1.294** and its estimate still charges
**$0.20/Mtok** (measured 2026-10-11). Pin the SDK version in the image and
record it beside any cost figure.

## Known limitations worth planning around

- Local disk is the default for every kind of state, and it is not durable.
- A **background Bash command** in an unattended session can run far longer than
  a foreground one: default **1800000 ms**, ceiling **7200000 ms** (Claude Code
  **2.1.285+**), and `BASH_DEFAULT_TIMEOUT_MS`/`BASH_MAX_TIMEOUT_MS` above their
  defaults raise both. Size the container's lifetime and its token budget for
  that, not for the 600000 ms foreground cap.
- `permission_mode` left unset can start a headless session in **`auto`** from
  2.1.285, where broad allow rules are dropped. Pass it explicitly.
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
percentages); `claude-agent-sdk` 0.2.165
`_internal/transport/subprocess_cli.py:237-264` (CLI discovery), `types.py:2096`
(`cwd`), `:2403` (`session_store`), `:2056` (`max_budget_usd`), `:2025`
(`permission_mode`). The $0.20/Mtok cache-read price of the bundled CLI 2.1.294
was measured by this plugin on 2026-10-11. Re-read 2026-10-11 against
claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs.
