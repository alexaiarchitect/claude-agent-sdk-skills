# The entry-point convention: `module:function`

The Agent SDK prescribes no layout. That is a feature for the person writing
one agent and a problem for any tool that has to load somebody else's. This
plugin's answer is one convention, written down in one place, overridable at
three levels.

## The convention

```python
# agent.py
def build_options() -> ClaudeAgentOptions:
    """Return the options. No side effects, no I/O that a test cannot repeat."""

async def run(prompt: str, options: ClaudeAgentOptions | None = None):
    """Optional. Stream every message of one session."""
```

`build_options()` is the part the runner needs. `run()` is a convenience: when
it exists the runner drives it, when it does not the runner builds its own
`ClaudeSDKClient` around the options. Either way the agent's *behaviour* lives
in the options, not in the driver.

Three rules that make `build_options()` usable:

1. **Return, do not run.** A `build_options()` that opens a database connection
   or reads a file relative to the current directory breaks when the runner
   calls it from a fresh per-run working directory.
2. **Read the model from the environment.** `os.getenv("CLAUDE_MODEL", ...)`,
   so a case can override it by setting the variable and the config can pin it.
3. **Build MCP servers inside the function.** In-process servers hold state; a
   module-level one is shared across every case in a run, and a case that
   reserves a book changes what the next case sees.

## `module:function`

The spec is a dotted module path, a colon, and a function name:

```
agent:build_options              # agent.py, the convention
svc.agent:make_options           # a package
apps.support.bot:options         # anything importable from the project root
```

It resolves against the project root, which is also the directory the runner
puts on `PYTHONPATH`. A spec that does not match
`^[A-Za-z_][\w.]*:[A-Za-z_]\w*$` is rejected before anything runs.

## Three levels of override, narrowest wins

| Level | Where | Use it for |
|---|---|---|
| project | `"agent": "agent:build_options"` in `evals/eval_config.json` | the default for the suite |
| environment | `AGENT_ENTRY=svc.agent:make` | a repository with two agents, or a CI matrix |
| case | `agent: other.module:build_options` in `prompt.md` frontmatter | one case that exercises a second agent |

A case-level override is the escape hatch for a monorepo, not the normal shape.
When most cases override the entry point, the config is naming the wrong
default.

## What the runner does with the options it gets

It copies them and applies, in this order:

1. the **isolation defaults** — `setting_sources=[]`, `strict_mcp_config=True`
   — unless the case overrides them;
2. the **config's** model, when the options did not pin one;
3. the **case's** `overrides`, validated against the overridable option list
   first, so a typo (`modle:`) is `EVC003` before a session starts rather than
   a silent no-op after one;
4. the **case's** `mocks`, replacing named `mcp_servers` entries.

Options the runner owns are refused (`EVC004`): `cwd`, `hooks`, `can_use_tool`,
`mcp_servers`, `stderr`, the session-resumption family and
`enable_file_checkpointing`. They are not "advanced"; they are the levers the
runner is pulling to make the run reproducible, and a case that pulls them back
is measuring something else.

## When the convention does not fit

Some agents are a CLI, a web handler, or a library with no single options
builder. Two honest answers:

* **Add a thin `build_options()`** beside the real code that returns the same
  options the application builds. It is three lines and it is the seam.
* **Point `agent:` at whatever builder does exist.** The convention is a
  default, not a requirement; the runner only needs a callable that returns
  `ClaudeAgentOptions`.

What does not work is evaluating an agent whose options are constructed inside
`main()` — there is nothing to point at. That is `AGT003`, and the fix is the
three-line extraction above.

Sources: `lib/agent_sdk_skills/layout.py` (`ENTRY_FUNCTION`, `detect_layout`,
the `convention | custom | inline | collection` styles);
`lib/agent_sdk_skills/evalcase.py` (`AGENT_ENTRY` pattern, `EVC003`/`EVC004`);
`.dev/CONTRACTS.md` §1.1 and §12.3 (the runner-owned option list);
https://code.claude.com/docs/en/agent-sdk/python (`ClaudeAgentOptions`,
`ClaudeSDKClient`).
