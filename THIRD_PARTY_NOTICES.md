# Third-party notices

This plugin distills and adapts material from the following projects. Their
copyright notices are reproduced below as required by their licenses. A copy of
the Apache License 2.0, under which this plugin itself is released, is in
`LICENSE`.

Every claim in this plugin's references was read at one of the snapshots named
below, or on the documentation pages cited in each reference's `Sources:`
footer. The commit id is given so any statement can be checked against the
exact tree it came from.

## Claude Agent SDK for Python (`anthropics/claude-agent-sdk-python`)

    Copyright (c) Anthropic, PBC
    Licensed under the MIT License
    https://github.com/anthropics/claude-agent-sdk-python

Snapshot: `f93e29cc951c` (2026-10-17, `main` after `v0.2.168`; previously
`b6e9d12f` and `bbf09e3c`, which was `v0.2.162`). Behaviour was measured against
the installed `claude-agent-sdk` **0.2.168 wheel (bundled CLI 2.1.301)**; earlier
figures in this plugin's references name the wheel they came from (0.2.165 with
CLI 2.1.294, or 0.2.162 with CLI 2.1.285). Names first released in 0.2.166 are
marked "0.2.166+" as a version gate, because the plugin still supports 0.2.140.

Used as the authoritative source for the options, message types, hooks and
custom-tool API described in this plugin's references and implemented against
by the runner package. No source files are redistributed.

## Claude Code (`anthropics/claude-code`)

    Copyright (c) Anthropic, PBC
    Proprietary license; see LICENSE.md in that repository
    https://github.com/anthropics/claude-code

Snapshot: `c017428c8c27` (2026-10-17, Claude Code 2.1.302; previously
`3deb8736` at 2.1.296 and `732e167e` at 2.1.285). Consulted for the `agent-sdk-dev` plugin this plugin refers to, the
changelog and the hooks examples. No files are redistributed; the repository's
own license terms apply to its contents.

## Claude Cookbooks (`anthropics/claude-cookbooks`)

    Copyright (c) Anthropic, PBC
    Licensed under the MIT License
    https://github.com/anthropics/claude-cookbooks

Snapshot: `a162e0184e71` (2026-10-17; previously `9c1e493d` and `d7265d6a`).
The `claude_agent_sdk/` notebooks informed the hooks, MCP, session and hosting
guidance; the `tool_evaluation/` notebook informed the tool-description advice;
the OpenTelemetry tracing cookbook (`observability/opentelemetry_tracing.ipynb`)
is cited by `skills/agent-deploy/references/observability-otel.md`.
No notebook content is redistributed.

## Agent Skills (`anthropics/skills`)

    Copyright (c) Anthropic, PBC
    https://github.com/anthropics/skills

Snapshot: `dbd4588f` (unmoved since 2026-10-09; re-checked 2026-10-17;
previously `8a1541c4`. The `skill-creator` content is byte-identical between the
two). The grader design (burden of
proof on the expectation, no partial credit, critique of weak assertions)
informed this plugin's `llm` grader and rubric guidance. Per-skill license
files apply to that repository's contents; nothing from it is redistributed.

## Code with Claude workshops (`anthropics/cwc-workshops`)

    Copyright 2026 Anthropic PBC
    Licensed under the Apache License, Version 2.0
    https://github.com/anthropics/cwc-workshops

Snapshot: `4c34ec4863df` (2026-10-17; previously `068b84bb`. The new commit adds
a managed-agents workshop outside the part this plugin reads). The
`eval-driven-agent-development` workshop's code-versus-judge grader split and
baseline comparison informed the grader catalog. No files are redistributed.

## Claude Agent SDK demos (`anthropics/claude-agent-sdk-demos`)

    Copyright (c) Anthropic, PBC
    No repository-level license file at the snapshot
    https://github.com/anthropics/claude-agent-sdk-demos

Snapshot: `826b2685` (unmoved since 2026-03-13; re-checked 2026-10-17). Used as
example projects for the read-only sweep that checks this plugin's static
readers on real code. Nothing is redistributed.

## Documentation

Claude Code and Agent SDK documentation at `https://code.claude.com/docs/` and
`https://platform.claude.com/docs/`, first read on 2026-09-30, re-read on
2026-10-11 at Claude Code 2.1.296 (85 pages) and on **2026-10-17** at Claude
Code **2.1.302** (86 pages, adding `settings-reference`); every reference names
the pages it distills and carries the re-read date in its `Sources:` footer.
Anthropic's engineering post "How we contain Claude across products"
(`https://www.anthropic.com/engineering/how-we-contain-claude`, 2026-10-12) is
cited by `skills/agent-deploy/references/secure-deployment.md`. The TypeScript
SDK repository, whose contents are under Anthropic's commercial terms, was
consulted for its documentation only and nothing from it is included.

## Not included

The plugin's fixtures (a library book reservations domain), templates, runner,
references and eval cases are original work written for this plugin.
