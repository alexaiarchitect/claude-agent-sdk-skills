# Frontmatter conformance samples

Three headers and the mapping each one must parse to. The plugin's
`lib/agent_sdk_skills/frontmatter.py` is the reference implementation; the
runner package carries a verbatim copy, and these files are how the copy is
tested against the original rather than against its author's memory.

Each `<name>.md` is a complete file. `<name>.expected.json` is
`{"meta": ..., "body": ...}` — the parsed header and the body text that follows
it. A parser that agrees on all three agrees on everything the case and grader
formats use.
