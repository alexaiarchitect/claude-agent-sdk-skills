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
states plainly — sandboxed processes **share the host kernel**, and the proxy
allowlists on the client-supplied hostname without terminating TLS, so domain
fronting can reach outside the list. If your threat model needs more, use gVisor
or a VM, and a TLS-terminating proxy.

## Credentials: the proxy pattern

The recommended shape is that **the agent never sees a credential**. A proxy
outside the boundary injects them into outgoing requests.

Why it is worth the extra component:

1. the agent cannot leak what it does not have;
2. the proxy enforces an endpoint allowlist;
3. the proxy logs every request for audit;
4. credentials live in one place instead of in every container.

Two ways to route Claude's own traffic through it:

```bash
# Sampling requests only; the proxy sees plaintext and can inject the key.
export ANTHROPIC_BASE_URL="http://localhost:8080"

# All HTTP traffic. For HTTPS the proxy makes a CONNECT tunnel and cannot see
# or modify contents without TLS interception.
export HTTP_PROXY="http://localhost:8080"
export HTTPS_PROXY="http://localhost:8080"
```

Envoy (`credential_injector`), mitmproxy, Squid and LiteLLM all do this; so does
a small service you write.

For credentials to *other* services — git, databases, internal APIs — the same
rule applies: keep them out of the agent's environment and let the proxy add
them after the request leaves. Where that is impractical, wrap the access in a
custom MCP tool whose handler holds the credential, so the model sees an
operation rather than a secret.

## What a subscription credential is not for

> Unless previously approved, Anthropic does not allow third party developers to
> offer claude.ai login or rate limits for their products, including agents
> built on the Claude Agent SDK.

So a `CLAUDE_CODE_OAUTH_TOKEN` in a container that serves other people is a
policy problem before it is a technical one (`HST001`). Two practical reasons on
top of the policy: an OAuth token is tied to **one person's plan**, and it
expires — so the deployment breaks on a date, on someone else's account.

Use an API key from a secret manager, a gateway that injects one, or a cloud
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
- **A credential literal in a Dockerfile or compose file** (`HST040`) is
  readable by anyone who can pull the image, and is in the build history.
  Rotate it; do not just delete the line.

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

Read regardless of any of it: **managed policy settings** from the host (MDM
plist, registry, managed settings file), **server-managed settings** when the
session authenticates with a qualifying organisation credential — which now means
"an eligible login to your organisation or an OAuth token issued for it", so a
fleet running on API keys (directly or through `apiKeyHelper`) cannot receive
server-managed settings at all and has to use MDM or managed settings **files**
instead — **`~/.claude.json`**
(relocate with `CLAUDE_CONFIG_DIR`), and **builtin plugins and their skills**.
Measured with `setting_sources=[]`: 18 builtin-plugin skills, 2 builtin plugins
and one managed MCP server still loaded.

Managed settings are also where a provider allowlist belongs.
`allowedProviders` (**2.1.285+**) names the inference providers a session may
use, so a host that must stay on one provider pins it there rather than trusting
every container's environment; the same file is where
`permissions.disableAutoMode: "disable"` and
`permissions.disableBypassPermissionsMode: "disable"` block the two modes a
deployment usually does not want. Two related facts for a headless fleet:
`permission_mode` left unset could start a session that fetches no feature
flags in **`auto`** on 2.1.285–2.1.301, and starts it in `default` from 2.1.302 (see
`../../agent-harness/references/permission-model.md`), and a read from a network
path is never approved by an allow rule, so a mounted UNC share is not reachable
unattended unless it is mapped and passed with `--add-dir`.

Guards fail closed more often since 2.1.299: an action a plugin hook can block
is refused when the hook cannot receive it or answer; a shell-form `PreToolUse`
guard on Windows without Git Bash blocks instead of failing open; in `plan` a
hook's `allow` no longer approves a write; and an MCP allow rule reaches only
the server it names (`mcp__<server>__*`). From 2.1.300 a hook's `updatedInput`
is validated like Claude's own, so a malformed rewrite denies the call. A host
that routes the provider itself sets `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`, and
then provider, endpoint and credential variables in settings files are ignored.
Project and local settings cannot set storage-location variables such as
`CLAUDE_CONFIG_DIR`, nor (2.1.282+) the OpenTelemetry exporter variables; put
those in the job's environment or managed settings. Three newer variables are
honoured **only** from the environment that launches Claude Code (a settings
`env` block is ignored): `CLAUDE_CODE_WARN_DISK_FREE_GIB` and, on Linux/WSL,
`CLAUDE_CODE_WARN_MEMORY_FREE_GIB` (2.1.304+, a whole number of GiB; below it
Claude gets a system reminder saying how much is free — useful in a small
container), and `CLAUDE_CODE_DISABLE_MOUNTED_DRIVE_RM_PROMPT` (2.1.304+, turns
off the mounted-drive `rm` prompt; leave it unset on a host with mounted
volumes).

**Sandbox changes in 2.1.305–2.1.310.** `sandbox.allowNestedUserNamespaces`
(2.1.305+, user or managed scope; a `true` in project settings, or anywhere
under `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, is ignored) lets sandboxed Linux/WSL2
commands create user namespaces for Chromium, Electron or a nested bubblewrap —
and "If you set this key to `true`, you turn off a security boundary: code from
a sandboxed command can end up running outside the sandbox." The SDK's
`SandboxSettings` does not declare it, so it reaches the CLI only as an
undeclared key; keep it off in a multi-tenant host. 2.1.309 closed several
gaps: sandboxed Bash on macOS and Linux no longer runs the shell's startup files
outside the sandbox before each command; macOS `denyWrite` globs apply at a
path's real location when reached through a symlink; sandboxed commands and
auto-accepted edits can no longer modify the `--mcp-config` file; Linux write
denies no longer lift when a background command outlives the session; and
commands the settings exclude from the sandbox now ask before writing to its
write-list paths when the sandbox is enabled but cannot run, with the
unsandboxed fallback refused. From 2.1.310 `/sandbox` and the startup warning
name Ubuntu's AppArmor user-namespace restriction when it stops bubblewrap.

And none of it controls **egress**. A container with a shell can connect
wherever its network policy allows. Apply per-tenant egress rules at the proxy —
distinct outbound IPs, credentials or domain allowlists — so a compromised
tenant cannot exfiltrate through another tenant's policy.

## A checklist that fits on one screen

- [ ] no credential in the image; none in a compose file; `.env` in `.dockerignore`
- [ ] an API key, a gateway, or a provider — never a subscription token
- [ ] non-root user; code read-only; one writable volume
- [ ] `setting_sources=[]`, `strict_mcp_config=True`, per-session `cwd`
- [ ] `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, per-tenant `CLAUDE_CONFIG_DIR`
- [ ] `max_turns` and `max_budget_usd` set; subagent depth and concurrency capped
- [ ] egress proxy with a domain allowlist, holding the credentials
- [ ] authentication at a gateway in front, not in the agent
- [ ] `permission_mode` passed explicitly (`dontAsk` unattended), never left unset
- [ ] managed settings pin `allowedProviders` and disable `auto`/`bypassPermissions`

---

Sources: <https://code.claude.com/docs/en/agent-sdk/secure-deployment>
(threat model, isolation technologies, sandbox runtime caveats, the proxy
pattern, credentials for other services, filesystem configuration),
<https://code.claude.com/docs/en/agent-sdk/hosting#multi-tenant-isolation>,
<https://code.claude.com/docs/en/agent-sdk/claude-code-features#what-settingsources-does-not-control>,
<https://code.claude.com/docs/en/agent-sdk/quickstart> (the third-party policy
note), <https://code.claude.com/docs/en/sandboxing#security-limitations>;
<https://code.claude.com/docs/en/model-config> (managed-settings delivery,
`allowedProviders`), <https://code.claude.com/docs/en/permission-modes> (the
HIPAA configuration and the mode-disabling settings),
<https://code.claude.com/docs/en/permissions#network-paths>,
<https://www.anthropic.com/engineering/how-we-contain-claude> ("How we contain
Claude across products", 2026-10-12, for the containment model this checklist
sits inside);
`claude-agent-sdk` 0.2.174 `types.py:2653` (`setting_sources`), `:2373`
(`strict_mcp_config`), `:2380` (`permission_mode`),
`_internal/session_resume.py:352-380` (credential handling and `apiKeyHelper`);
<https://code.claude.com/docs/en/settings-reference> (variables ignored in
project `env`, `sandbox.allowNestedUserNamespaces`),
<https://code.claude.com/docs/en/permission-modes> ("The mounted drive prompt"), <https://code.claude.com/docs/en/permissions#hook-approvals-in-plan-mode>,
<https://code.claude.com/docs/en/env-vars> (`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.299,
2.1.300, 2.1.302, 2.1.304, 2.1.305, 2.1.309, 2.1.310).
The list of what still loaded under `setting_sources=[]` was measured by this
plugin on 2026-09-30. Re-read 2026-10-11 against claude-agent-sdk 0.2.165 /
Claude Code 2.1.296 docs. Re-read 2026-10-24 against claude-agent-sdk
0.2.174 / Claude Code 2.1.310 docs.
