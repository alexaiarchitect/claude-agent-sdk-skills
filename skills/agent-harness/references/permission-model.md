# The permission model: six steps, six modes, two layers

## The evaluation order

When Claude requests a tool, the SDK checks six things in this order. Knowing
the order is the difference between a restriction that works and one that only
looks like it does.

| # | Step | What it can do |
|---|---|---|
| 1 | **Hooks** | a `PreToolUse` hook can deny outright or pass the call on. An `allow` here does **not** skip steps 2 and 3, and cannot approve an `rm`/`rmdir` targeting a critical path |
| 2 | **Deny rules** | from `disallowed_tools` and `settings.json`. A match blocks the call **even in `bypassPermissions`**. A bare-name rule (`"Bash"`) removed the tool from context before this step, so only scoped rules (`"Bash(rm *)"`) are evaluated here |
| 3 | **Ask rules** | from `settings.json`. A match falls through to `can_use_tool` even in `bypassPermissions`. `AskUserQuestion` and MCP tools whose server sets `requiresUserInteraction` always land here; in `dontAsk` mode they are **denied** instead, because that mode never prompts |
| 4 | **Permission mode** | `bypassPermissions` approves everything that reaches this step; `acceptEdits` approves file operations; `plan` sends file-edit and shell-write tools to `can_use_tool` regardless of allow rules; other modes fall through |
| 5 | **Allow rules** | from `allowed_tools` and `settings.json`. A match approves. Calls a tool approves on its own — a read inside the working directory, a read-only Bash command — resolve here with no rule |
| 6 | **`can_use_tool`** | everything unresolved. **Skipped entirely in `dontAsk`**, where the call is denied instead |

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
prefix**: `mcp__github__get_*` works, `mcp__*` and `*` are ignored with a
startup warning and approve nothing.

`Edit(path)` rules govern every built-in that writes files, `Write` and
`NotebookEdit` included; a `Write(path)` rule is never matched by the file
permission checks. Use `//path` for an absolute filesystem path — with one
leading slash the rule anchors at its own source, which for `disallowed_tools`
means the session's working directory.

## The six modes

| Mode | What it does |
|---|---|
| `default` | no mode-based approvals; anything needing approval and matching no allow rule reaches `can_use_tool` |
| `dontAsk` | anything that would prompt is **denied**. `can_use_tool` is never called. Pre-approved calls still run |
| `acceptEdits` | file edits and filesystem operations (`mkdir`, `rm`, `mv`) are auto-approved. **Does not auto-approve MCP tools** |
| `bypassPermissions` | everything that reaches step 4 runs. Deny and ask rules still apply; critical-path removals still fall through |
| `plan` | file edits are never auto-approved and always prompt |
| `auto` | a model classifier approves or denies each prompt |

`dontAsk` is the right default for an unattended run: it never blocks waiting
for an answer that will not come, and it fails closed. `bypassPermissions`
fails open, which is `OPT002`.

**Subagent inheritance:** a subagent runs in the parent's mode unless its
`AgentDefinition` sets `permissionMode` *and* the parent is in `default`,
`dontAsk` or `plan`. Claude Code never applies a `bypassPermissions` value from
an `AgentDefinition`; a subagent runs in that mode only when the parent already
does — and then it has the parent's full autonomous access with a different
system prompt.

## `can_use_tool` versus a hook

`can_use_tool` is `async def can_use_tool(tool_name, input_dict, context)`
returning `PermissionResultAllow(updated_input=..., updated_permissions=...)` or
`PermissionResultDeny(message=..., interrupt=...)`.

It is a **prompt handler**, not an observer. It fires only when the rules
evaluate to "ask", so it never sees a tool that `allowed_tools` pre-approved,
and setting it alongside a bare `allowed_tools` entry or `bypassPermissions`
raises a `CanUseToolShadowedWarning` at connect.

To see or gate **every** call, use a `PreToolUse` hook. (A hook that returns
`allow` skips `can_use_tool` for that call, so the two are alternatives, not
layers.)

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
allow and deny rules, permission modes, subagent inheritance),
<https://code.claude.com/docs/en/agent-sdk/custom-tools#control-tool-access>
(the availability/permission table),
<https://code.claude.com/docs/en/agent-sdk/user-input> (`can_use_tool`),
<https://code.claude.com/docs/en/permission-modes>,
<https://code.claude.com/docs/en/permissions#bash-rule-limits>;
`claude-agent-sdk` 0.2.162 `types.py:25` (`PermissionMode`), `:259`
(`PermissionResultAllow`), `:268` (`PermissionResultDeny`), `:278`
(`CanUseTool`), `:1835-1924` (`CanUseToolShadowedWarning`), `:1974-1993`
(`tools` and `allowed_tools` docstrings).
