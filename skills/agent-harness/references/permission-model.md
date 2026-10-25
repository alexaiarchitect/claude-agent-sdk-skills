# The permission model: seven steps, six modes, two layers

## The evaluation order

When Claude requests a tool, the SDK checks these things in this order. Knowing
the order is the difference between a restriction that works and one that only
looks like it does. Step 7 exists only when a **mod** is installed (Claude Code
2.1.292+), which is a plugin class this plugin does not otherwise cover.

| # | Step | What it can do |
|---|---|---|
| 1 | **Hooks** | a `PreToolUse` hook can deny outright or pass the call on. An `allow` here does **not** skip steps 2 and 3, and cannot approve an `rm`/`rmdir` targeting a critical path |
| 2 | **Deny rules** | from `disallowed_tools` and `settings.json`. A match blocks the call **even in `bypassPermissions`**. A bare-name rule (`"Bash"`) removed the tool from context before this step, so only scoped rules (`"Bash(rm *)"`) are evaluated here |
| 3 | **Ask rules** | from `settings.json`. A match falls through to `can_use_tool` even in `bypassPermissions`. `AskUserQuestion` and MCP tools whose server sets `requiresUserInteraction` always land here; in `dontAsk` mode they are **denied** instead, because that mode never prompts |
| 4 | **Permission mode** | `bypassPermissions` approves everything that reaches this step except critical-path removals and commands flagged `Dangerous rm operation not ruled out`, which fall through; `acceptEdits` approves file operations; in `plan`, "Claude Code sends file-edit tools to your `canUseTool` callback regardless of allow rules" (while auto mode is available, the classifier reviews planning-time commands instead of the callback); other modes fall through |
| 5 | **Allow rules** | from `allowed_tools` and `settings.json`. A match approves. Calls a tool approves on its own — a read inside the working directory, a read-only Bash command — resolve here with no rule. **A read from a network path is the exception**: it has its own check that no allow rule, no `PreToolUse` `"allow"` and no classifier can bypass |
| 6 | **`can_use_tool`** | everything unresolved. **Skipped entirely in `dontAsk`**, where the call is denied instead |
| 7 | **A mod's `tool.check`** | only when a mod is installed (2.1.292+). It answers **after** the rules and the `PreToolUse` hooks and can replace their answer: it overrides ask rules, a blocking `PreToolUse` hook and the auto-mode classifier. It cannot override a blocking hook that came from **managed settings**, and deny rules beat a mod only under managed settings or a Team/Enterprise sign-in — a session on an API key or a long-lived `CLAUDE_CODE_OAUTH_TOKEN` "isn't using that login, even when that login is stored". A mod still cannot bypass a prompt for a tool that needs user interaction |

## The two layers, and the mistake everyone makes

`tools` and bare-name `disallowed_tools` change **availability** — whether the
tool is in Claude's context at all. `allowed_tools` and scoped
`disallowed_tools` change **permission** — whether a call is approved once
Claude attempts it.

| Option | Layer | Effect |
|---|---|---|
| `tools=["Read", "Grep"]` | availability | only those built-ins are in context; unlisted built-ins are removed. **MCP tools are unaffected** |
| `tools=[]` | availability | every built-in is removed; Claude can use only your MCP tools |
| `allowed_tools=["Read"]` | permission | `Read` runs without a prompt. **Every other tool is still there** and falls through to the permission mode |
| `disallowed_tools=["Bash"]` | availability | the `Bash` definition is removed from the request; Claude cannot attempt it |
| `disallowed_tools=["Bash(rm *)"]` | permission | `Bash` stays available; calls matching `rm *` *as written* are denied in every mode. `/bin/rm` is not matched |
| `disallowed_tools=["*"]` | availability | every tool definition is removed. `"mcp__*"` removes every MCP tool |

So `OPT001` — an allow list with no deny list — is a warning about a belief, not
a syntax error: the author believed they had restricted the agent, and they had
not.

Allow rules accept a tool-name glob **only after a literal `mcp__<server>__`
prefix**: `mcp__github__get_*` works, `mcp__*` and `*` are ignored and
approve nothing.

**MCP rules name one server exactly (2.1.299+).** `mcp__<server>__*` approves a
whole server and no other (`mcp__a` no longer allows `a__b`). `<server>` is the
normalised name (`.` and spaces become `_`; plugin servers are
`mcp__plugin_<plugin>_<server>__*`); a name containing `__` or ending in `_`
needs the wildcard form (`mcp__reports__v2__*`). As a **deny or ask** rule,
`mcp__reports` also covers every tool of `reports__v2`.

**Network paths (2.1.292+).** A read from a Windows UNC path
(`\\server\share\file`) or a `/net` automount path has its own check that no
allow rule, `PreToolUse` `"allow"` or classifier bypasses: it always prompts, and
in `dontAsk` it is **denied outright** (beside `AskUserQuestion`,
`requiresUserInteraction` MCP tools and org-`ask` connectors). Mount the share
locally and pass `--add-dir` if the agent needs the data.

`Edit(path)` rules govern every built-in that writes files, `Write` and
`NotebookEdit` included: "`Write(path)`, `NotebookEdit(path)`, and `Glob(path)`
rules never match" — Claude Code accepts them and checks files against `Edit`
and `Read` rules only, so write `Edit(docs/**)` or `Read(docs/**)` instead (a
bare tool name still matches every call of that tool). Use `//path` for an absolute filesystem path — with one
leading slash the rule anchors at its own source, which for `disallowed_tools`
means the session's working directory.

## The six modes

| Mode | What it does |
|---|---|
| `default` | no mode-based approvals; anything needing approval and matching no allow rule reaches `can_use_tool` |
| `dontAsk` | anything that would prompt is **denied**. `can_use_tool` is never called. Pre-approved calls, and **file reads inside the working directories**, still run; a network-path read is denied |
| `acceptEdits` | file edits and the Bash commands `mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`, `sed` inside the working directories are auto-approved (`touch` only with plain file paths: an option, a glob or a `timeout 5`/`LANG=C` prefix prompts). **Does not auto-approve MCP tools** |
| `bypassPermissions` | everything that reaches step 4 runs. Deny and ask rules still apply; critical-path removals still fall through |
| `plan` | file edits are never auto-approved, even by an allow rule or a hook's `allow`; they reach `can_use_tool` |
| `auto` | a model classifier reviews actions such as shell commands and network requests before they run, allowing or blocking each one it reviews. It does **not** decide a network-path read. Broad allow rules such as a bare `Bash` are dropped in this mode |

`dontAsk` is the right default for an unattended run: it never blocks waiting
for an answer that will not come, and it fails closed. `bypassPermissions`
fails open, which is `OPT002`.

**Leaving `permission_mode` unset is a decision too, and its answer depends on
the CLI version.** With the mode `None` the CLI resolves it:
`permissions.defaultMode` from a settings file where one applies, otherwise the
built-in default. The docs now state the rule ("Tool calls denied in `claude -p`
and Agent SDK runs"): "In Claude Code v2.1.302 or later, `claude -p` and Agent
SDK runs with no permission mode set start in Manual mode. This mode appears as
`default` in SDK options and settings," and "Before v2.1.302, these runs could
start in auto mode if they didn't fetch feature flags, for example on a
third-party provider or with `DISABLE_TELEMETRY`" — the **2.1.285–2.1.301**
window. Measured by this plugin: unset sessions reported `permissionMode:
"default"` on 2.1.292, 2.1.301 (2026-10-17) and 2.1.310 (2026-10-24, again
2026-10-29). In `default` a call that needs approval is **denied** unless an
allow rule, hook, `can_use_tool` or `--permission-prompt-tool` approves it. In
`auto`, broad allow rules are dropped, so a bare `Bash` entry quietly stops
pre-approving. Pass `"default"` or `"dontAsk"` explicitly; the linters report
the omission as **`OPT013`** (a warn: the outcome depends on CLI version and
environment), and this plugin's runner forces `"dontAsk"` when it is unset.
Managed settings can block auto mode with `permissions.disableAutoMode: "disable"`.

**Leaving `auto` without asking (2.1.299+).** A session in `auto` that switches,
through `set_model()`, to a model without auto-mode support changes to
`default` and emits a `system`/`status` message carrying
`permissionMode: "default"`; `set_permission_mode("auto")` returns to it once
the model supports it. Before 2.1.299 such a session stayed in `auto`.

**Subagent inheritance:** "The subagent inherits `plan`, `acceptEdits`,
`auto`, or `bypassPermissions` from the main session, and under a `default`- or
`dontAsk`-mode main session it runs in the mode you set." **Plan mode pins a
subagent**: under a plan-mode parent, a subagent set to `acceptEdits` still runs
in plan mode, so its source edits still reach `can_use_tool`. Even under `default`/`dontAsk`,
Claude Code never applies a `bypassPermissions` value from an `AgentDefinition`
(2.1.267+) — a subagent runs that way only when the parent already does, with
the parent's full autonomous access — and applies an `"auto"` value only when
auto mode is **available to that subagent**.

**The auto-mode classifier's model.** "By default, classifier requests go to
Claude Sonnet 5" (an Anthropic-configured model, a Sonnet 4.6 session or
`ANTHROPIC_DEFAULT_SONNET_MODEL` can change it; an unavailable choice falls back
to the session's model). From 2.1.302 `CLAUDE_CODE_AUTO_MODE_MODEL` takes a full
model id; it is ignored for Opus 5, Sonnet 5.5, Opus 5.5 or a policy-excluded
model, and if the provider cannot serve it "Classifier checks fail, so Claude
Code denies each action it checks" (`--debug-file`: `classifier_request_started`).

**Critical paths are a best-effort check.** No allow rule or hook `"allow"`
approves an `rm`/`rmdir` "whose target it recognizes as a critical path" (root,
home, working directory), but "the check can miss some commands, so it doesn't
replace an operating-system control such as sandboxing": a missed command gets
no special handling, so an allow rule, `bypassPermissions` or the sandbox's
auto-allow approves it. A recursive `rm` on a **mounted drive** (`/Volumes/…`,
`/media/<user>/…`, `/run/media/…`, `/mnt/<name>`, WSL `/mnt/c/…`) is handled the
same way even with an `rm` allow rule, reason `Dangerous rm operation on mounted
drive path: <path>` (2.1.304). `CLAUDE_CODE_DISABLE_MOUNTED_DRIVE_RM_PROMPT=1`
turns that prompt off, and only from the environment that starts Claude Code: a
settings file's `env` block is ignored.

**Critical-path removals in `-p` and SDK runs.** No terminal prompt exists
there, so such a removal, and a Bash command flagged `Dangerous rm operation not
ruled out — the shell may read this command differently than it was parsed`, is
**denied in `auto`**; in `default`/`acceptEdits`/`bypassPermissions` your
`can_use_tool` callback or `--permission-prompt-tool` decides (its
`decisionReason` starts with `Dangerous rm`), and with neither it is denied
unless a `PermissionRequest` hook allows it; `dontAsk` denies. No `Bash`/
`Bash(*)` allow rule, sandbox auto-allow or hook `"allow"` approves it.
`CLAUDE_CODE_DISABLE_DANGEROUS_RM_TIMEOUT=1` hands these to the classifier in
`auto`; `CLAUDE_CODE_EVEN_MORE_DANGEROUSLY_SKIP_PERMISSIONS=1` (2.1.311+) runs
them unprompted in `bypassPermissions` only. Both are read from the launch
environment (the SDK's `env` option), never from a settings file.

**Sandbox interplay (2.1.309).** Excluded commands ask before writing to
write-list paths while the sandbox cannot run; macOS `denyWrite` globs apply at a
path's real location through a symlink; nothing sandboxed may modify the
`--mcp-config` file.

**Auto mode, by design and by the docs.** Anthropic's write-up of auto mode
(2026-03-25) explains the shape: three tiers — a built-in safe-tool allowlist
plus your narrow allow rules (rules granting arbitrary code execution are
dropped), in-project file edits without a classifier call, and everything else
through a transcript classifier. The classifier is two-stage (a fast yes/no
filter, then reasoning only when flagged) and "reasoning-blind by design": it
sees user messages and tool calls, not Claude's prose or tool results. A block
returns as a tool result and Claude continues; after 3 consecutive or 20 total
blocks it escalates. The article reports a 0.4 % false-positive rate on real
traffic and a 17 % miss rate on real overeager actions, and calls auto mode no
replacement for careful human review on high-stakes infrastructure. Current
behaviour comes from the docs, not the article: the article says a headless
`claude -p` run is terminated at the threshold, while `permission-modes` (read
2026-10-29) says a `-p` run without `--permission-prompt-tool` skips the action,
"Claude keeps working. Claude Code doesn't stop the run."

## `can_use_tool` versus a hook

`can_use_tool` is `async def can_use_tool(tool_name, input_dict, context)`
returning `PermissionResultAllow(updated_input=..., updated_permissions=...)` or
`PermissionResultDeny(message=..., interrupt=...)`.

It is a **prompt handler**, not an observer. It fires only when the rules
evaluate to "ask", so it never sees a tool that `allowed_tools` pre-approved,
and setting it alongside a bare `allowed_tools` entry or `bypassPermissions`
raises a `CanUseToolShadowedWarning` at connect. A `PermissionResultAllow` with
**more than 4,096 `updated_permissions` items** is invalid and the call is
denied: each `PermissionUpdate` counts, and so does each entry in its `rules` or
`directories`. A tool-level `permission_policy` (`always_ask`/`always_deny`) is
TypeScript-only (Agent SDK v0.3.301+); in Python gate such a tool with a scoped
`allowed_tools` plus `can_use_tool`, or a `PreToolUse` hook.

To see or gate **every** call, use a `PreToolUse` hook. (A hook that returns
`allow` skips `can_use_tool` for that call, so the two are alternatives, not
layers.) The docs' "Precedence among rules, hooks, and mods" section is the
table above in prose: hooks answer first, deny and ask rules still apply after
a hook's `allow`, and a mod's `tool.check` answers last.

**Hook approvals in plan mode (2.1.299+).** In `plan`, apart from
`ExitPlanMode`, a `PreToolUse` hook's `"allow"` (or a mod's `tool.check`) has
**no effect** on a call that is not read-only; its `updatedInput` still applies.
Approving the plan or switching mode lifts the limit.

## Choosing, in one paragraph

Decide availability first: `tools=[]` plus in-process MCP tools is the smallest
agent you can build, and the easiest to evaluate, because the trajectory can
only contain names you defined. Then pre-approve exactly those names in
`allowed_tools`. Then pick `dontAsk` so nothing waits. Then add a `PreToolUse`
hook if you need an audit trail or a rule the allow list cannot express. Scoped
deny rules are for the narrow case where a tool must stay available but one
shape of call must not.

---

Sources:
<https://code.claude.com/docs/en/agent-sdk/permissions> (evaluation order,
allow and deny rules, permission modes, subagent inheritance, plan mode and
`Dangerous rm` in the callback), <https://code.claude.com/docs/en/agent-sdk/python>
(the 4,096-item `updated_permissions` limit),
<https://code.claude.com/docs/en/agent-sdk/custom-tools> (TypeScript-only
`permission_policy`),
<https://code.claude.com/docs/en/agent-sdk/custom-tools#control-tool-access>
(the availability/permission table),
<https://code.claude.com/docs/en/agent-sdk/user-input> (`can_use_tool`),
<https://code.claude.com/docs/en/permission-modes> ("Tool calls denied in
`claude -p` and Agent SDK runs", `#which-mode-a-non-interactive-run-starts-in`;
"Default classifier model", "Choose the classifier model", critical paths,
"The mounted drive prompt", "Critical-path removals in each permission mode",
"Time limits and denials", "Repeated-block thresholds", `acceptEdits` commands),
<https://code.claude.com/docs/en/env-vars>,
<https://code.claude.com/docs/en/sub-agents> (plan-mode parent),
<https://code.claude.com/docs/en/permissions#bash-rule-limits>,
<https://code.claude.com/docs/en/permissions#network-paths> (the network-path
check and the mod precedence rules),
<https://code.claude.com/docs/en/permissions#precedence-among-rules-hooks-and-mods>,
<https://code.claude.com/docs/en/permissions#hook-approvals-in-plan-mode>,
<https://code.claude.com/docs/en/permissions#mcp> (MCP rule syntax),
<https://code.claude.com/docs/en/agent-sdk/permissions> ("Auto mode", the
`set_model()` drop to `default`),
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.299 MCP
rule scoping and plan-mode hook fix; 2.1.302 unset-mode default; 2.1.304
mounted-drive prompt; 2.1.309 sandbox changes; 2.1.311
`CLAUDE_CODE_EVEN_MORE_DANGEROUSLY_SKIP_PERMISSIONS`);
<https://www.anthropic.com/research/claude-code-auto-mode> ("How we built Claude
Code auto mode", 2026-03-25, permission tiers, reasoning-blind classifier,
deny-and-continue thresholds, reported error rates);
`claude-agent-sdk` 0.2.174 `types.py:25` (`PermissionMode`), `:259`
(`PermissionResultAllow`), `:268` (`PermissionResultDeny`), `:278`
(`CanUseTool`), `:2190-2279` (`CanUseToolShadowedWarning`), `:2329-2348`
(`tools` and `allowed_tools` docstrings), `:2380` (`permission_mode`). Re-read
2026-10-11 against claude-agent-sdk 0.2.165 / Claude Code 2.1.296 docs. The
unset-mode `default` on CLI 2.1.292 and 2.1.301 was measured by this plugin on
2026-10-17, and on 2.1.310 on 2026-10-24; re-read 2026-10-24 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.310 docs. Re-read 2026-10-29 against
claude-agent-sdk 0.2.174 / Claude Code 2.1.312 docs.
