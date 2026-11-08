# The permission model: seven steps, six modes, two layers

## The evaluation order

When Claude requests a tool, Claude Code checks the call at these steps; each step can decide the call, send it to
`can_use_tool`, or pass it on. Knowing the order is the difference between a restriction that works and one that only
looks like it does. Step 7 exists only when a **mod** is installed (2.1.292+), a plugin class this plugin does not
cover.

| # | Step | What it can do |
|---|---|---|
| 1 | **Hooks** | a `PreToolUse` hook can deny outright or pass the call on. An `allow` here does **not** skip steps 2 and 3, and cannot approve an `rm`/`rmdir` targeting a critical path |
| 2 | **Deny rules** | from `disallowed_tools` and the settings files the SDK loads. A match blocks the call **even in `bypassPermissions`**. A bare-name rule (`"Bash"`) removed the tool from context before this step, so only scoped rules (`"Bash(rm *)"`) are evaluated here |
| 3 | **Ask rules** | from `settings.json`. A match falls through to `can_use_tool` even in `bypassPermissions`. `AskUserQuestion` and MCP tools whose server sets `requiresUserInteraction` always land here; in `dontAsk` mode they are **denied** instead, "because that mode turns each prompt into a denial" |
| 4 | **Permission mode** | `bypassPermissions` approves each call that reaches this step unless it is one of the **actions no mode auto-approves** (below); `acceptEdits` approves file operations inside the working directories; "In `plan` mode, some calls reach your callback, and when auto mode is available, others go to its classifier instead"; in `default` and `dontAsk` the call goes on to the allow rules |
| 5 | **Allow rules** | from `allowed_tools` and `settings.json`. A match approves. Calls a tool approves on its own — a read inside the working directory, a read-only Bash command — resolve here with no rule. **A read from a network path is the exception**: it has its own check that no allow rule, no `PreToolUse` `"allow"` and no classifier can bypass |
| 6 | **`can_use_tool`** | the call resolved to a prompt: no earlier step decided it. In `dontAsk` this step is skipped and the call is denied |
| 7 | **A mod's `tool.check`** | only when a mod is installed (2.1.292+). It answers **after** the rules and the `PreToolUse` hooks and can replace their answer: it overrides ask rules, a blocking `PreToolUse` hook and the auto-mode classifier. It cannot override a blocking hook that came from **managed settings**, and deny rules beat a mod only under managed settings or a Team/Enterprise sign-in — a session on an API key or a long-lived `CLAUDE_CODE_OAUTH_TOKEN` "isn't using that login, even when that login is stored". A mod still cannot bypass a prompt for a tool that needs user interaction |

**What skips `can_use_tool`.** The SDK calls it when the flow resolves to a prompt, and skips it for "A call that an
`allowed_tools` entry or a settings allow rule approves" and "A call the permission mode approves, such as a file edit
in `acceptEdits` mode". "To check those calls, use a `PreToolUse` hook, which runs for them too" (`hooks-catalog.md`);
a hook deny applies even in `bypassPermissions`. A scoped allow rule such as `Bash(npm test *)` approves its matches;
other `Bash` calls that need approval fall through to the permission mode.

**Actions no mode auto-approves** (`permission-modes`), `bypassPermissions` included: tools matched by an explicit ask
rule; connector tools the organization set to `ask`; tools that require user interaction (`AskUserQuestion`, MCP tools
marked `requiresUserInteraction`); recognized critical-path `rm`/`rmdir` removals, "which no allow rule or
`PreToolUse` hook `"allow"` approves, and Bash commands flagged `Dangerous rm operation not ruled out`"; the
cross-session messaging safeguards; and reads or writes outside the working directories while
`blockReadsOutsideWorkingDirectories` (2.1.257+) or `blockWritesOutsideWorkingDirectories` (2.1.314+) is on. Writes to
a protected path are **not** on the list: `bypassPermissions` approves them, `acceptEdits` does not. Under
`bypassPermissions` in the SDK, org-`ask` connectors, user-interaction tools, critical-path removals and `Dangerous
rm` commands reach `can_use_tool`.

## The two layers, and the mistake everyone makes

`tools` and bare-name `disallowed_tools` change **availability** — whether the tool is in Claude's context at all.
`allowed_tools` and scoped `disallowed_tools` change **permission** — whether a call is approved once Claude attempts
it.

| Option | Layer | Effect |
|---|---|---|
| `tools=["Read", "Grep"]` | availability | only those built-ins are in context; unlisted built-ins are removed. **MCP tools are unaffected** |
| `tools=[]` | availability | every built-in is removed; Claude can use only your MCP tools |
| `allowed_tools=["Read"]` | permission | `Read` runs without a prompt. **Every other tool is still there** and falls through to the permission mode |
| `disallowed_tools=["Bash"]` | availability | the `Bash` definition is removed from the request; Claude cannot attempt it |
| `disallowed_tools=["Bash(rm *)"]` | permission | `Bash` stays available; calls matching `rm *` *as written* are denied in every mode. `/bin/rm` is not matched |
| `disallowed_tools=["*"]` | availability | every tool definition is removed. `"mcp__*"` removes every MCP tool |

So `OPT001` — an allow list with no deny list — is a warning about a belief, not a syntax error: the author believed
they had restricted the agent, and they had not.

Allow rules accept a tool-name glob **only after a literal `mcp__<server>__` prefix**: `mcp__github__get_*` works,
`mcp__*` and `*` are ignored and approve nothing.

**MCP rules name one server exactly.** `mcp__<server>__*` approves that server and no other (`mcp__a` does not allow
`a__b`); `<server>` is the normalised name (`.` and spaces become `_`; plugin servers are
`mcp__plugin_<plugin>_<server>__*`), and a name containing `__` or ending in `_` needs the wildcard form. As a **deny
or ask** rule, `mcp__reports` also covers `reports__v2`.

**Network paths.** A read from a Windows UNC path (`\\server\share\file`) or a `/net` automount path has its own check
that no allow rule, `PreToolUse` `"allow"` or classifier bypasses: it always prompts, and in `dontAsk` it is **denied
outright**. Mount the share locally and pass `--add-dir` if the agent needs the data.

**"`Write(path)`, `Glob(path)`, and `Grep(path)` rules don't match"** (the permissions page's heading, 2026-11-06).
Claude Code checks file permissions against `Edit(path)` and `Read(path)` rules only: it accepts a rule with a path
other than `*` for Write, NotebookEdit, legacy MultiEdit, Glob or Grep but never matches a call against it — "A
`Grep(docs/**)` deny rule doesn't stop Grep from searching `docs`". Write `Edit(docs/**)` for the writing tools and
`Read(docs/**)` for Glob and Grep (a bare tool name still matches every call of that tool). `Read(path)` **deny**
rules are applied best-effort to Grep, Glob, `@file` mentions and the context a connected IDE shares; as an **ask**
rule, `Read(docs/**)` prompts when Claude calls Grep or Glob on a matching path, but not when a search of a directory
above it returns matching files. In `allowed_tools`/`disallowed_tools`, `//path` is an absolute path and a single
`/path` is a path inside the session's working directory. `Edit(//secrets/**)` blocks writes under `/secrets` from
Claude's file tools and from Bash `tee` and `> file` redirection, but "A script that Claude runs and that opens files
itself can still write under `/secrets`": use the sandbox for enforcement by the operating system.

## The six modes

| Mode | What it does |
|---|---|
| `default` | no mode-based approvals; a call that needs approval and matches no allow rule reaches `can_use_tool` |
| `dontAsk` | "Converts any permission prompt into a denial, without calling `canUseTool`". "Use when: you run a headless agent and want a hard deny for each call that would otherwise prompt." Pre-approved calls, and **file reads inside the working directories**, still run; a network-path read is denied |
| `acceptEdits` | file edits and the Bash commands `mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`, `sed` inside the working directories are auto-approved (`touch` only with plain file paths: an option, a glob or a `timeout 5`/`LANG=C` prefix prompts). **Does not auto-approve MCP tools** |
| `bypassPermissions` | approves every call that reaches step 4 except the actions no mode auto-approves. Deny rules still apply; `allowed_tools` doesn't constrain it, so unlisted tools are approved too |
| `plan` | "Claude explores and plans". Edits with Claude's file tools outside protected paths, and `AskUserQuestion`, reach `can_use_tool` even when an allow rule matches or a hook returns `allow`. When auto mode is available, shell commands, web fetches, web searches and read-only MCP calls that no allow rule approves go to its classifier instead (on by default; `useAutoModeDuringPlan: false` turns it off). Hook approvals in plan mode: apart from `ExitPlanMode`, a hook's `"allow"` has **no effect** on a call that is not read-only; its `updatedInput` still applies |
| `auto` | a model classifier reviews actions such as shell commands and network requests before they run, allowing or blocking each one it reviews. It does **not** decide a network-path read. Broad allow rules such as a bare `Bash` are dropped in this mode |

`dontAsk` is the right default for an unattended run: it never blocks waiting for an answer that will not come, and it
fails closed. `bypassPermissions` fails open, which is `OPT002`. `permissions.denyInsteadOfPrompting` (Claude Code
2.1.319+; on the settings page since 2026-11-10, user/managed scope or a `--settings` file, never a repository) denies
a call that would wait on a prompt and lets the turn continue — in `-p` runs, terminal, VS Code and Desktop sessions,
subagents and agent teams. It **skips `can_use_tool` and `--permission-prompt-tool`** (approve from a
`PermissionRequest` hook instead), drops `AskUserQuestion`, `EnterPlanMode` and `ExitPlanMode`, and cancels MCP
elicitation unless an `Elicitation` hook answers. The denial reads "Permission for this tool use was denied. It
requires approval, and this session has no approval surface"; a `permission_denied` message carries `decision_reason`
"no approval surface in this session; permission request denied automatically"; in auto mode the turn ends as
`error_during_execution` after 20 refused calls in a row. An SDK app that answers prompts in code keeps `dontAsk` and
leaves this key unset.

**Leaving `permission_mode` unset is a decision too, and its answer depends on the CLI version.** With the mode `None`
the CLI resolves it: `permissions.defaultMode` from a settings file where one applies, otherwise the built-in default.
The docs now state the rule ("Tool calls denied in `claude -p` and Agent SDK runs"): "In Claude Code v2.1.302 or
later, `claude -p` and Agent SDK runs with no permission mode set start in Manual mode. This mode appears as `default`
in SDK options and settings," and "Before v2.1.302, these runs could start in auto mode if they didn't fetch feature
flags, for example on a third-party provider or with `DISABLE_TELEMETRY`" — the **2.1.285–2.1.301** window (measured
by this plugin, footer). In `default` a call that needs approval is **denied** unless an allow rule, hook,
`can_use_tool` or `--permission-prompt-tool` approves it. In `auto`, broad allow rules are dropped, so a bare `Bash`
entry quietly stops pre-approving. Pass `"default"` or `"dontAsk"` explicitly; the linters report the omission as
**`OPT013`** (a warn: the outcome depends on CLI version and environment), and this plugin's runner forces `"dontAsk"`
when it is unset. Managed settings can block auto mode with `permissions.disableAutoMode: "disable"`. Server-side
classifier review needs Claude Code 2.1.278+ in `-p` and VS Code sessions, 2.1.281+ in Agent SDK and desktop sessions.
An `auto` session that `set_model()`s to a model without auto-mode support drops to `default`; from 2.1.314 a settings
file excluded with `--setting-sources` (the SDK's `setting_sources`) no longer supplies auto-mode rules or saved
permission consents.

**Auto mode without feature flags (2.1.319, changelog-only).** With telemetry or feature flags off, including behind
an LLM gateway, auto mode no longer falls back to the built-in classifier: calls the server cannot check are asked
about or denied (`CLAUDE_CODE_AUTO_MODE_SERVER=0` keeps the built-in one; `CLAUDE_CODE_DISABLE_FEATURE_FLAGS`, on the
env-vars page since 2026-11-10, stops flag fetching). `claude -p` exits 1 when auto mode refused actions for lack of a
safety check. From **2.1.325** a run asked for `auto` where auto mode is unavailable starts in Manual, not a mode that
allows more. **Bash rule fixes keep landing** (2.1.319–2.1.325 changelogs): quoted words, `sed`, `cp`/`mv` into a
directory (deny rules now cover the written file; `/bin/cp` gets the same checks), relative deny rules after a `cd`,
`sudo`/`env` wrappers, `Bash(ls*)` wildcards, a `Read` deny rule now covering Write/Edit paths — treat rules as a
moving target and keep the sandbox or `tools` as the hard boundary.

**Subagent inheritance:** "The subagent inherits `plan`, `acceptEdits`, `auto`, or `bypassPermissions` from the main
session, and under a `default`- or `dontAsk`-mode main session it runs in the mode you set." **Plan mode pins a
subagent**: under a plan-mode parent, a subagent set to `acceptEdits` still runs in plan mode, so its source edits
still reach `can_use_tool`. Even under `default`/`dontAsk`, Claude Code never applies a `bypassPermissions` value from
an `AgentDefinition` (2.1.267+) — a subagent runs that way only when the parent already does, with the parent's full
autonomous access — and applies an `"auto"` value only when auto mode is **available to that subagent**. **The
auto-mode classifier's model:** "By default, classifier requests go to Claude Sonnet 5" (an unavailable choice falls
back to the session's model). `CLAUDE_CODE_AUTO_MODE_MODEL` takes a full model id, ignored for Opus 5, Sonnet 5.5,
Opus 5.5 or a policy-excluded model; if the provider cannot serve it "Classifier checks fail, so Claude Code denies
each action it checks" (`--debug-file`: `classifier_request_started`).

**Critical paths are a best-effort check.** No allow rule or hook `"allow"` approves an `rm`/`rmdir` "whose target it
recognizes as a critical path" (root, home, working directory); under `default` it needs approval even with a matching
allow rule, "a permission gate, not a sandbox" (`agent-sdk/secure-deployment`). But "the check can miss some commands,
so it doesn't replace an operating-system control such as sandboxing": a missed command gets no special handling, so
an allow rule, `bypassPermissions` or the sandbox's auto-allow (`sandbox.autoAllowBashIfSandboxed: true`; the default
flipped to **`false`** in Claude Code 2.1.324 / SDK 0.2.182, so sandboxed Bash now follows the normal permission flow
unless you opt in) approves it. A recursive `rm` on a **mounted drive** (`/Volumes/…`, `/media/<user>/…`,
`/run/media/…`, `/mnt/<name>`, WSL `/mnt/c/…`) is handled the same way even with an `rm` allow rule, reason `Dangerous
rm operation on mounted drive path: <path>` (2.1.304). `CLAUDE_CODE_DISABLE_MOUNTED_DRIVE_RM_PROMPT=1` turns that
prompt off, and only from the environment that starts Claude Code: a settings file's `env` block is ignored.
**Critical-path removals in `-p` and SDK runs:** No terminal prompt exists there, so such a removal, and a Bash
command flagged `Dangerous rm operation not ruled out — the shell may read this command differently than it was
parsed`, is **denied in `auto`**; in `default`/`acceptEdits`/`bypassPermissions` your `can_use_tool` callback or
`--permission-prompt-tool` decides (its `decisionReason` starts with `Dangerous rm`), and with neither it is denied
unless a `PermissionRequest` hook allows it; `dontAsk` denies. No `Bash`/ `Bash(*)` allow rule, sandbox auto-allow or
hook `"allow"` approves it. `CLAUDE_CODE_DISABLE_DANGEROUS_RM_TIMEOUT=1` hands these to the classifier in `auto`;
`CLAUDE_CODE_EVEN_MORE_DANGEROUSLY_SKIP_PERMISSIONS=1` (2.1.311+) runs them unprompted in `bypassPermissions` only.
Both are read from the launch environment (the SDK's `env` option), never from a settings file.

**Sandbox interplay.** macOS `denyWrite` globs apply at a path's real location through a symlink; nothing sandboxed
may modify the `--mcp-config` file; from 2.1.314 sandbox protections also apply to a worktree entered by `claude -p
--resume` or `--continue`. **Writes outside the working directories (2.1.314+):** Beside the read block
(`permissions.blockReadsOutsideWorkingDirectories`), `permissions.blockWritesOutsideWorkingDirectories: true` makes
`Write`, `Edit` and `NotebookEdit` refuse paths outside the working directories "in every permission mode, including
`bypassPermissions`". It does not limit shell commands, MCP tools or the programs hooks run: use the sandbox for
those. While it is on, `EnterWorktree`/`ExitWorktree` are removed, settings files are refused even inside the working
directories (one could lift the block), and a `true` in any loaded file applies, so a repository can turn it on but
cannot lift yours; a cloud session might not apply it. Plan files, the scratchpad and this project's auto-memory `.md`
files stay writable. To let one directory through use `/add-dir`, `--add-dir` (the SDK's `add_dirs`) or
`additionalDirectories` in user or managed settings — "No allow rule lets Claude's file tools through either block."

**Auto mode, by design and by the docs.** Anthropic's write-up of auto mode (2026-03-25): three tiers (a safe-tool
allowlist plus your narrow allow rules, in-project file edits, and a transcript classifier for the rest); the
classifier is two-stage and "reasoning-blind by design" (user messages and tool calls only); a block returns as a tool
result and Claude continues; 3 consecutive or 20 total blocks escalate. It reports a 0.4 % false-positive rate on real
traffic and a 17 % miss rate on real overeager actions. Current behaviour comes from the docs: a `-p` run without
`--permission-prompt-tool` skips the action, "Claude keeps working. Claude Code doesn't stop the run." Interactively a
blocked action is listed in `/permissions` under **Recently blocked**; with no verdict Claude Code blocks the action
without that entry (2.1.314) and "can stop the turn after ten responses in a row with no verdict". A hook or mod that
changes an action's input after the server's review can also draw a no-verdict denial, and such denials do not count
toward the ten (see `hooks-catalog.md`, `updatedInput` in auto mode).

## `can_use_tool` versus a hook

`can_use_tool` is `async def can_use_tool(tool_name, input_dict, context)` returning
`PermissionResultAllow(updated_input=..., updated_permissions=...)` or `PermissionResultDeny(message=...,
interrupt=...)`.

It is a **prompt handler**, not an observer: the SDK calls it when the flow resolves to a prompt, and a call an allow
rule or the mode approved is skipped (above). Setting it alongside a bare `allowed_tools` entry or `bypassPermissions`
raises a `CanUseToolShadowedWarning` at connect. A `PermissionResultAllow` with **more than 4,096
`updated_permissions` items** is invalid and the call is denied: each `PermissionUpdate` counts, and so does each
entry in its `rules` or `directories`. A tool-level `permission_policy` (`always_ask`/`always_deny`) is
TypeScript-only (Agent SDK v0.3.301+); in Python gate such a tool with a scoped `allowed_tools` plus `can_use_tool`,
or a `PreToolUse` hook.

To see or gate **every** call, rule- and mode-approved ones included, use a `PreToolUse` hook. (A hook that returns
`allow` skips `can_use_tool` for that call, so the two are alternatives, not layers.) A guard hook fails open when it
crashes unless its matcher sets `on_failure="block"` (0.2.177+, CLI 2.1.317+; `HOK011`); on `PermissionRequest` that
block counts only if the failure lands before `can_use_tool` answers, so a crashing `PermissionRequest` guard is no
substitute for a `can_use_tool` that denies. The docs' "Precedence among rules, hooks, and mods" section is the table
above in prose: hooks answer first, deny and ask rules still apply after a hook's `allow`, and a mod's `tool.check`
answers last (also keyed on a `managed-mcp.json` file since 2026-11-10). From **2.1.325** a permission check that
errors after a `PreToolUse` `allow` is decided as if no hook had answered, and input a `PermissionRequest` hook
rewrote that then fails the check is asked again, or refused where nobody can answer. A **mod's own tool calls**
(`$.tool.call`, `$.mcp.call`) raise no permission prompt even under ask rules or in `dontAsk`/`-p` runs; deny rules
and organization policy still apply (2.1.321). An allow rule for an MCP tool is written **without a specifier**:
`mcp__srv__tool` matches, `mcp__srv__tool(x)` and a `ruleContent` in a permission update match nothing (docs
2026-11-10).

## Choosing, in one paragraph

Decide availability first: `tools=[]` plus in-process MCP tools is the smallest agent you can build, and the easiest
to evaluate, because the trajectory can only contain names you defined. Then pre-approve exactly those names in
`allowed_tools`. Then pick `dontAsk` so nothing waits. Then add a `PreToolUse` hook if you need an audit trail or a
rule the allow list cannot express. Scoped deny rules are for the narrow case where a tool must stay available but one
shape of call must not.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/permissions> (evaluation order and the calls that skip
`can_use_tool`, allow and deny rules, path patterns in rules, permission modes, subagent inheritance, plan mode and
`Dangerous rm` in the callback, "Auto mode", the `set_model()` drop to `default`),
<https://code.claude.com/docs/en/agent-sdk/python> (the 4,096-item `updated_permissions` limit),
<https://code.claude.com/docs/en/agent-sdk/custom-tools> (TypeScript-only `permission_policy`; `#control-tool-access`,
the availability/permission table), <https://code.claude.com/docs/en/agent-sdk/user-input> (`can_use_tool`; "An
earlier step can allow or deny a call before `canUseTool` runs"),
<https://code.claude.com/docs/en/agent-sdk/secure-deployment>, <https://code.claude.com/docs/en/permission-modes>
("Tool calls denied in `claude -p` and Agent SDK runs", `#which-mode-a-non-interactive-run-starts-in`; "Default
classifier model", "Choose the classifier model", critical paths, "The mounted drive prompt", "Critical-path removals
in each permission mode", "Time limits and denials", "Repeated-block thresholds", `acceptEdits` commands, **Recently
blocked**, "Actions no mode auto-approves", "Server-side classifier review"),
<https://code.claude.com/docs/en/env-vars>, <https://code.claude.com/docs/en/sub-agents> (plan-mode parent),
<https://code.claude.com/docs/en/permissions> (`#bash-rule-limits`; the `Write`/`Glob`/`Grep` path-rule heading and
the `Read(path)` deny and ask behaviour, read 2026-11-08; `#network-paths`, the network-path check and the mod
precedence rules; `#precedence-among-rules-hooks-and-mods`; `#hook-approvals-in-plan-mode`; `#mcp`; "Block file-tool
reads and writes outside the working directories"), <https://code.claude.com/docs/en/settings-reference>
(`permissions.blockWritesOutsideWorkingDirectories`),
<https://code.claude.com/docs/en/settings-reference#permissions-denyinsteadofprompting> (scope, what else it stops,
the two denial texts, the 20-call stop; read 2026-11-14), the same page's `sandbox.autoAllowBashIfSandboxed` (default
`false` from 2.1.324) and the `permissions` page's MCP allow rules without a specifier (2026-11-10);
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (versions named above; 2.1.319 auto mode without
feature flags and the `-p` exit 1; 2.1.321 mods' own calls, `cp`/`mv`; 2.1.323–2.1.325 Bash rule fixes, `Read` deny on
writes, auto-mode fallback to Manual, the hook/permission-check rules);
<https://www.anthropic.com/research/claude-code-auto-mode> ("How we built Claude Code auto mode", 2026-03-25,
permission tiers, reasoning-blind classifier, deny-and-continue thresholds, reported error rates); `claude-agent-sdk`
0.2.182 `types.py:25` (`PermissionMode`), `:261` (`PermissionResultAllow`), `:270` (`PermissionResultDeny`), `:280`
(`CanUseTool`), `:2203-2292` (`CanUseToolShadowedWarning`), `:2344-2363` (`tools` and `allowed_tools` docstrings),
`:2395` (`permission_mode`), `:866` (`on_failure`); lines as in 0.2.182 (renumbered 2026-11-14);
<https://code.claude.com/docs/en/agent-sdk/hooks#block-the-action-when-a-callback-fails>. The unset-mode `default` was
measured by this plugin on 2026-10-17, 2026-10-24 and 2026-11-02. Re-read 2026-11-14 against claude-agent-sdk 0.2.182
/ Claude Code 2.1.325 docs.
