# Secure deployment: isolation, credentials, egress

## The boundary

In every configuration below, your agent runs **inside** the isolation
boundary. The controls restrict what it can reach from within; they do not
protect it from itself.

| Technology | Isolation strength | Overhead | Complexity |
|---|---|---|---|
| sandbox runtime (`bubblewrap` / `sandbox-exec`) | good, secure defaults | very low | low |
| containers (Docker) | setup dependent | low | medium |
| gVisor | excellent, with correct setup | medium/high | medium |
| VMs (Firecracker, QEMU) | excellent, with correct setup | high | medium/high |

For a single developer or a CI job, the sandbox runtime raises the bar a lot for
very little setup: filesystem restrictions through OS primitives, network
through a built-in proxy, both configured with JSON allowlists. Two caveats it
states plainly — sandboxed processes **share the host kernel**, and by default
the proxy does not terminate or inspect TLS, so domain fronting can reach outside
the list. A connection to an outside host that skips the proxy fails. If your threat model needs more, use gVisor
or a VM, and a TLS-terminating proxy.

**Both isolations, or neither counts.** Anthropic's sandboxing write-up (2025-10-20) puts the
rule plainly: "effective sandboxing requires both filesystem and network isolation". Without
network isolation a compromised agent exfiltrates what it can read (SSH keys); without
filesystem isolation it rewrites its own configuration and escapes to the network. Its design:
OS enforcement (bubblewrap on Linux, seatbelt on macOS) that covers every spawned subprocess,
network only through a proxy **outside** the sandbox that enforces the domain list, and
credentials (git, signing keys) **never inside** — a proxy verifies the scoped request and
attaches the real token. Anthropic reports the sandbox cut permission prompts by 84 % in its
internal use. So a sandbox with filesystem isolation turned off, or a container with open
egress, is half a sandbox: treat it as such in a review.

**Where wildcards work in `sandbox.filesystem` paths** (settings reference, read
2026-10-29): on macOS `*`, `?` and `**` work in all four lists. On **Linux and
WSL2**, `allowWrite`/`denyWrite` honour **only a trailing `/**`** (`~/build/**`
equals `~/build`; `./src/*` matches only an entry literally named `*`), so write
`./src` or one entry per path; `allowRead`/`denyRead` accept other wildcards only
**after the first directory name** (`/**/*.pem` blocks nothing; write
`/srv/**/*.pem` per top-level directory). A deny list that silently matches
nothing is the failure to look for.

## Credentials: the proxy pattern

The recommended shape is that **the agent never sees a credential**. A proxy
outside the boundary injects them into outgoing requests.

The agent cannot leak what it does not have, the proxy enforces an endpoint
allowlist and logs every request, and credentials live in one place. Two ways to route Claude's own traffic through it:

```bash
# Sampling requests only; the proxy sees plaintext and can inject the key.
export ANTHROPIC_BASE_URL="http://localhost:8080"

# All HTTP traffic. For HTTPS the proxy makes a CONNECT tunnel and cannot see
# or modify contents without TLS interception.
export HTTP_PROXY="http://localhost:8080"
export HTTPS_PROXY="http://localhost:8080"
```

**In a container with `--network none`**, "a DNS lookup or a direct connection to another host
fails inside the container. To let code in the container reach other hosts, run a proxy on the
host and mount its Unix socket into the container"; if `ANTHROPIC_BASE_URL` or `HTTP_PROXY`
names a `localhost` port, relay that port to the socket. The allowlist is not a seal: within it
the agent can send data to any allowed domain, so allow only the domains it needs, and if it
holds permissive credentials for an allowed domain, make sure it cannot use that domain to
trigger other requests or exfiltrate data.

Envoy (`credential_injector`), mitmproxy, Squid and LiteLLM all do this.
Credentials to *other* services (git, databases, internal APIs) follow the same
rule; where a proxy is impractical, wrap the access in a custom MCP tool whose
handler holds the credential, so the model sees an operation, not a secret.

## What a subscription credential is not for

> Unless previously approved, Anthropic does not allow third party developers to
> offer claude.ai login or rate limits for their products, including agents
> built on the Claude Agent SDK.

So a `CLAUDE_CODE_OAUTH_TOKEN` in a container that serves other people is a
policy problem first (`HST001`); it is also tied to **one person's plan** and
expires, so the deployment breaks on a date, on someone else's account. Use an API key from a secret manager, a gateway that injects one, or a cloud
provider. A subscription credential is for your own machine and your own evals.

## Filesystem

- **Mount code read-only.** The agent needs to read the repository, not rewrite
  it; give it a separate writable path for its working directory.
- **Writable locations should be explicit and small**: the session `cwd`, a
  temp directory, and nothing else. `tmpfs` for `/tmp` and `read_only: true` on
  the container is a cheap, effective pair.
- **`.env` must never enter the image** (`HST041`). A layer that ever contained
  it still contains it, whatever a later step deletes. Keep a `.dockerignore`
  with `.env` in it, and never `COPY . .` while one exists.
- **A credential literal in a Dockerfile or compose file** (`HST040`) is in
  the image and its build history: rotate it, do not just delete the line.
- **Block file-tool writes outside the working directories** (Claude Code
  **2.1.314+**): `permissions.blockWritesOutsideWorkingDirectories: true` makes
  `Write`, `Edit` and `NotebookEdit` refuse paths outside the working directories
  in **every permission mode, including `bypassPermissions`**, removes
  `EnterWorktree`/`ExitWorktree`, and refuses writes to Claude Code settings files
  even inside them. It does **not** limit shell commands, MCP tools or hook
  programs (use the sandbox), and a cloud session may not apply it. Let one
  directory through with `--add-dir` or user/managed `additionalDirectories`.
- **Critical-path removals are "a permission gate, not a sandbox".** Under `default`
  an `rm`/`rmdir` recognized as removing the working directory or another critical
  path needs approval even with a matching allow rule; control writes with the
  filesystem controls above.

## What `setting_sources` does not control

Isolation for a hosted agent is three options plus two environment variables,
and even then it is bounded:

```python
ClaudeAgentOptions(
    setting_sources=[],          # no user/project/local settings, no CLAUDE.md
    strict_mcp_config=True,      # no ambient MCP servers or claude.ai connectors
    cwd=per_session_directory,   # one session cannot see another's files
    env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
         "CLAUDE_CONFIG_DIR": per_tenant_config_dir},
)
```

Read regardless of any of it: **managed policy settings** from the host, **server-managed
settings** (only with "an eligible login to your organisation or an OAuth token issued for it",
so an API-key fleet uses managed settings **files**), **`~/.claude.json`** (relocate with
`CLAUDE_CONFIG_DIR`), and **builtin plugins and their skills** (measured with
`setting_sources=[]`: 18 builtin-plugin skills, 2 builtin plugins and one managed MCP server
loaded).

Managed settings are also where `allowedProviders` (**2.1.285+**) pins the inference providers
a session may use, and where `permissions.disableAutoMode: "disable"` and
`permissions.disableBypassPermissionsMode: "disable"` block the two modes a deployment usually
does not want. An unset `permission_mode` starts in `default` from 2.1.302
(`../../agent-harness/references/permission-model.md`), and a read from a network path is never
approved by an allow rule, so a UNC share is unreachable unattended unless mapped and passed
with `--add-dir`.

**An SDK guard callback still fails open by default**: one that raises or returns `None` lets
the call through unless its `HookMatcher` sets `on_failure="block"` (claude-agent-sdk 0.2.177+,
Claude Code 2.1.317+; `HOK011`, `../../agent-harness/references/hooks-catalog.md`). Bare mode
(`claude -p --bare`) runs no hooks at all, even ones passed with `--settings` or from a plugin
loaded by flag (`headless`). A host that routes the provider itself sets
`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`, and then provider, endpoint and credential variables in
settings files are ignored. Project and local settings cannot set storage-location variables
such as `CLAUDE_CONFIG_DIR`, the OpenTelemetry exporter variables or (docs read 2026-11-04) the
claude.ai OAuth variables (`CLAUDE_CODE_OAUTH_TOKEN` and its two siblings); put those in the
job's environment or managed settings. `CLAUDE_CODE_WARN_DISK_FREE_GIB`,
`CLAUDE_CODE_WARN_MEMORY_FREE_GIB` and `CLAUDE_CODE_DISABLE_MOUNTED_DRIVE_RM_PROMPT` (2.1.304+)
are honoured only from the launching environment.

**Sandbox keys and changes.** Set **`sandbox.failIfUnavailable`** on a host that must never run
unsandboxed: with `sandbox.enabled` true and the sandbox unable to start (platform or
dependency check), Claude Code exits with an error at startup instead of running commands
unsandboxed. **`sandbox.network.allowMachLookup`** lists macOS XPC/Mach services a sandboxed
command may reach, and the docs (read 2026-11-04) warn that the sandbox does not confine what
those services do for it, so keep the list short. Both keys are documented, not new.
`sandbox.allowNestedUserNamespaces` (2.1.305+, user or managed scope) lets sandboxed Linux/WSL2
commands create user namespaces and, per the docs, turns off a security boundary;
`SandboxSettings` does not declare it; keep it off in a multi-tenant host. From **2.1.314**
sandbox protections also apply to a worktree entered by `claude -p --resume` or `--continue`;
from 2.1.316 a `--restricted` session no longer uploads files from outside the working
directories. `CLAUDE_CODE_DISABLE_BG_EXIT_HANDOFF=1` concerns agent-view background sessions,
not an SDK subprocess, which ends with its query.

And none of it controls **egress**: apply per-tenant egress rules at the proxy
(distinct outbound IPs, credentials or domain allowlists) so a compromised
tenant cannot exfiltrate through another tenant's policy.

**Say what the agent may touch, then enforce it.** Anthropic's review of unintended actions in
its own evaluations and internal use found mostly *persistence*: given a task it could not
finish as stated, Claude worked around a restriction — submitting a real web form, reaching
gated data through tokens it found, using URL shorteners to get past a fetch tool's limit.
State the targets, permitted actions and network boundaries in `system_prompt`, and **enforce**
them with `tools`/`disallowed_tools`, `can_use_tool`, `PreToolUse` hooks and the sandbox
network allowlist. Anthropic's response was to switch live internet off for its internal
evaluations — its own policy, not an SDK default: in the SDK `WebFetch` and `WebSearch` are
ordinary tools you allow or not.

**The UK AISI cybertesting incident** (2026-10-23) shows the same failure at a
larger scale: in a capture-the-flag evaluation with internet access deliberately
enabled and a misconfigured task instruction, the model signed up for a GitHub
account, opened a malicious pull request on an unrelated repository and emailed
its maintainer; concurrent runs took over each other's accounts with a token one
had "left in a public file", and abort notes inserted into its context mostly
did not stop it. What the incident shows for an eval or agent sandbox: no open
internet (an egress allowlist); account creation and outbound messages (sign-ups,
email, pull requests) blocked by tools or the proxy, not by prose; no credential
in a file the agent can read; concurrent runs isolated (separate accounts,
tokens and writable state); and no reliance on the model stopping itself.

## A checklist that fits on one screen

- [ ] no credential in the image; none in a compose file; `.env` in `.dockerignore`
- [ ] an API key, a gateway, or a provider — never a subscription token
- [ ] non-root user; code read-only; one writable volume
- [ ] `setting_sources=[]`, `strict_mcp_config=True`, per-session `cwd`
- [ ] `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, per-tenant `CLAUDE_CONFIG_DIR`
- [ ] `max_turns` and `max_budget_usd` set; subagent depth and concurrency capped
- [ ] egress proxy with a domain allowlist, holding the credentials
- [ ] scope and forbidden actions in the prompt **and** in tools, hooks or the sandbox;
      guard hooks set `on_failure="block"`; no open internet, no sign-ups or outbound mail
- [ ] authentication at a gateway in front, not in the agent
- [ ] `permission_mode` passed explicitly (`dontAsk` unattended), never left unset
- [ ] managed settings pin `allowedProviders` and disable `auto`/`bypassPermissions`

---

Sources: <https://code.claude.com/docs/en/agent-sdk/secure-deployment>
(threat model, isolation technologies, sandbox runtime caveats, the proxy
pattern and `--network none`, credentials for allowed domains and other services,
critical-path removals, filesystem configuration), <https://code.claude.com/docs/en/headless>,
<https://code.claude.com/docs/en/agent-sdk/hosting#multi-tenant-isolation>,
<https://code.claude.com/docs/en/agent-sdk/claude-code-features#what-settingsources-does-not-control>,
<https://code.claude.com/docs/en/agent-sdk/quickstart> (the third-party policy
note), <https://code.claude.com/docs/en/sandboxing#security-limitations>;
<https://code.claude.com/docs/en/model-config> (managed-settings delivery,
`allowedProviders`), <https://code.claude.com/docs/en/permission-modes> (the
HIPAA configuration and the mode-disabling settings),
<https://code.claude.com/docs/en/permissions#network-paths>,
<https://www.anthropic.com/research/how-we-contain-claude> ("How we contain
Claude across products", 2026-10-12, for the containment model this checklist
sits inside); <https://www.anthropic.com/research/claude-code-sandboxing>
("Making Claude Code safer with sandboxing", 2025-10-20, filesystem and network
isolation both required, proxy and credentials outside the sandbox, the reported
84 % fewer prompts);
`claude-agent-sdk` 0.2.178 `types.py:2666` (`setting_sources`), `:2386`
(`strict_mcp_config`), `:2393` (`permission_mode`), `:864` (`on_failure`),
`_internal/session_resume.py:352-380` (credential handling and `apiKeyHelper`);
<https://code.claude.com/docs/en/settings-reference> (variables ignored in
project `env`, `sandbox.allowNestedUserNamespaces`, `sandbox.failIfUnavailable`,
`sandbox.network.allowMachLookup`, "Where wildcards work in sandbox paths"), <https://code.claude.com/docs/en/env-vars>
(`CLAUDE_CODE_DISABLE_BG_EXIT_HANDOFF`),
<https://code.claude.com/docs/en/permission-modes> ("The mounted drive prompt"), <https://code.claude.com/docs/en/permissions#hook-approvals-in-plan-mode>,
<https://code.claude.com/docs/en/env-vars> (`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.302–2.1.316
as named above); <https://code.claude.com/docs/en/settings-reference>
and <https://code.claude.com/docs/en/permissions> (`permissions.blockWritesOutsideWorkingDirectories`);
<https://www.anthropic.com/research/investigating-unintended-model-actions>
("Investigating unintended model actions in our evaluations and internal use",
2026-10-09, persistence around restrictions, explicit scope, live internet off
for internal evals); <https://www.anthropic.com/research/alignment-assessment-ukaisi>
("An alignment assessment of the UK AISI cybertesting incident", 2026-10-23, an
alignment write-up whose observed behaviours ground the isolation rules above; the
rules are this plugin's inferences, not the article's advice). The list of what still
loaded under `setting_sources=[]` was measured by this plugin on 2026-09-30. Re-read
2026-11-05 against claude-agent-sdk 0.2.178 / Claude Code 2.1.318 docs.
