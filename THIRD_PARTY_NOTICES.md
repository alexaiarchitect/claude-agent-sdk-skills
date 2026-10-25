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

Snapshot: `27858cbba9ecee26a06a90b8d39d3b5596121d11` (2026-10-29, `main`, whose
`src/` differs from `v0.2.174` only in `_cli_version.py`, which bundles CLI
2.1.312; no release newer than 0.2.174; previously
`0e89b298e771259378a6cd3734e00d323dff5703` on 2026-10-24, `f93e29cc` after
`v0.2.168`, `b6e9d12f` and `bbf09e3c`, which was `v0.2.162`). Behaviour was
measured against the installed `claude-agent-sdk` **0.2.174 wheel (bundled CLI
2.1.310)**, last on 2026-10-29; earlier
figures in this plugin's references name the wheel they came from (0.2.168 with
CLI 2.1.301, 0.2.165 with CLI 2.1.294, or 0.2.162 with CLI 2.1.285). Names first released in 0.2.166 are
marked "0.2.166+" as a version gate, because the plugin still supports 0.2.140.

Used as the authoritative source for the options, message types, hooks and
custom-tool API described in this plugin's references and implemented against
by the runner package. No source files are redistributed. The test fixture
`tests/fixtures/sessions/sdk_parallel_tools.jsonl` was written by hand in the
transcript shape of the SDK's `tests/test_sessions.py::_parallel_tool_turn`
(MIT); no code or data was copied.

## Claude Code (`anthropics/claude-code`)

    Copyright (c) Anthropic, PBC
    Proprietary license; see LICENSE.md in that repository
    https://github.com/anthropics/claude-code

Snapshot: `58d6da1e34d6cd1c6379dcbf568bd66f5f9b6102` (2026-10-29, Claude Code
2.1.312; previously `318b7e6ac4e726e88a4ad326214866a93c373b1b` at 2.1.310 on
2026-10-24, `c017428c` at 2.1.302, `3deb8736` at 2.1.296 and `732e167e` at
2.1.285). Consulted for the changelog and the hooks examples. At this snapshot
`plugins/` holds only a README: Anthropic's plugins, including the
`agent-sdk-dev` plugin this plugin refers to, are developed in
`anthropics/claude-plugins-official` (`plugins/agent-sdk-dev`, Apache-2.0, with
an explicit version since 2026-10-26), and the `claude-code-plugins` marketplace
installs them from there; nothing from either repository is included. No files
are redistributed; the repository's own license terms apply to its contents.

## Claude Cookbooks (`anthropics/claude-cookbooks`)

    Copyright (c) Anthropic, PBC
    Licensed under the MIT License
    https://github.com/anthropics/claude-cookbooks

Snapshot: `c43f56d0360b9b1f631bd090fd199231d4c880cc` (2026-10-29: model-default
bumps only; previously `a162e0184e71` from 2026-10-17, `9c1e493d` and `d7265d6a`).
The `claude_agent_sdk/` notebooks informed the hooks, MCP, session and hosting
guidance; the `tool_evaluation/` notebook informed the tool-description advice;
the OpenTelemetry tracing cookbook (`observability/opentelemetry_tracing.ipynb`)
is cited by `skills/agent-deploy/references/observability-otel.md`.
No notebook content is redistributed.

## Agent Skills (`anthropics/skills`)

    Copyright (c) Anthropic, PBC
    https://github.com/anthropics/skills

Snapshot: `ca45fc496a3436251f191354091d557da31c15b5` (2026-10-29; the one new
commit touches `mcp-builder` only; previously `dbd4588f`, unmoved from
2026-10-09 to 2026-10-24, and `8a1541c4`. The `skill-creator` content is
byte-identical across all three). The grader design (burden of
proof on the expectation, no partial credit, critique of weak assertions)
informed this plugin's `llm` grader and rubric guidance. Per-skill license
files apply to that repository's contents; nothing from it is redistributed.

## Code with Claude workshops (`anthropics/cwc-workshops`)

    Copyright 2026 Anthropic PBC
    Licensed under the Apache License, Version 2.0
    https://github.com/anthropics/cwc-workshops

Snapshot: `4c34ec4863df` (2026-10-17, unmoved on 2026-10-24 and 2026-10-29; previously `068b84bb`. The new commit adds
a managed-agents workshop outside the part this plugin reads). The
`eval-driven-agent-development` workshop's code-versus-judge grader split and
baseline comparison informed the grader catalog. No files are redistributed.

## Claude Agent SDK demos (`anthropics/claude-agent-sdk-demos`)

    Copyright (c) Anthropic, PBC
    No repository-level license file at the snapshot
    https://github.com/anthropics/claude-agent-sdk-demos

Snapshot: `826b2685` (unmoved since 2026-03-13; re-checked 2026-10-29). Used as
example projects for the read-only sweep that checks this plugin's static
readers on real code. Nothing is redistributed.

## Documentation

Claude Code and Agent SDK documentation at `https://code.claude.com/docs/` and
`https://platform.claude.com/docs/`, first read on 2026-09-30, re-read on
2026-10-11 at Claude Code 2.1.296 (85 pages), on 2026-10-17 at Claude Code
2.1.302 (86 pages, adding `settings-reference`) and on **2026-10-24** at Claude
Code **2.1.310** (the same 86 pages, none added or removed), and on
**2026-10-29** at Claude Code **2.1.312** (the same 86 files, 58 pages changed);
every reference names the pages it distills and carries the re-read date in its
`Sources:` footer. The TypeScript SDK repository, whose contents are under
Anthropic's commercial terms, was consulted for its documentation only and
nothing from it is included.

## Cited Anthropic articles

Anthropic's published engineering and product articles supply the design
rationale in this plugin's references; current mechanics are always cited from
the documentation above. Each was read on 2026-10-29 at the canonical URL below
(the older engineering-blog paths under `anthropic.com` now redirect to
`anthropic.com/research/<slug>`). The references **paraphrase** them, with at
most a short attributed quote; no article text is reproduced at length, and the
articles remain Anthropic's.

| # | Article | Canonical URL | Date | Cited by |
|---|---|---|---|---|
| 1 | "Building agents with the Claude Agent SDK" | https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk | 2025-09-29 | `agent-create/references/eval-ready-architecture.md`, `eval-create/references/case-taxonomy.md`, `eval-create/references/golden-traces.md`, `agent-design` |
| 2 | "Building effective AI agents" (carries its own note that tooling has changed) | https://www.anthropic.com/research/building-effective-agents | 2024-12-19 | `agent-design` |
| 3 | "Effective context engineering for AI agents" | https://www.anthropic.com/research/effective-context-engineering-for-ai-agents | 2025-09-29 | `agent-harness/references/context-and-settings.md`, `agent-sdk/references/glossary.md`, `agent-design` |
| 4 | "Writing effective tools for AI agents" | https://www.anthropic.com/research/writing-tools-for-agents | 2025-09-11 | `agent-harness/references/mcp-patterns.md`, `agent-design` |
| 5 | "Equipping agents with Agent Skills" | https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills | 2025-10-16 | `agent-sdk/references/glossary.md`, `agent-design` |
| 6 | "Code execution with MCP for efficient agents" | https://www.anthropic.com/research/code-execution-with-mcp | 2025-11-04 | `agent-harness/references/mcp-patterns.md`, `agent-design` |
| 7 | "Building agents: When to fold subagents into your main agent loop" | https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop | 2026-10-22 | `agent-harness/references/subagent-design.md`, `agent-sdk/references/glossary.md`, `eval-create/references/case-taxonomy.md`, `eval-create/references/golden-traces.md`, `agent-design` |
| 8 | "Effective harnesses for long-running agents" | https://www.anthropic.com/research/effective-harnesses-for-long-running-agents | 2025-11-26 | `agent-debug/references/failure-shapes.md`, `agent-sdk/references/glossary.md`, `agent-design` |
| 9 | "Harness design for long-running apps" | https://www.anthropic.com/research/harness-design-long-running-apps | 2026-03-24 | `eval-criteria/references/judge-options.md`, `agent-design` |
| 10 | "How we built our multi-agent research system" | https://www.anthropic.com/research/multi-agent-research-system | 2025-06-13 | `agent-harness/references/subagent-design.md`, `agent-deploy/references/hosting-options.md`, `eval-criteria/references/judge-options.md`, `agent-design` |
| 11 | "Scaling Managed Agents with stable interfaces" | https://www.anthropic.com/research/managed-agents | 2026-04-08 | `agent-deploy/references/hosting-options.md`, `agent-design` |
| 12 | "How we built Claude Code auto mode" | https://www.anthropic.com/research/claude-code-auto-mode | 2026-03-25 | `agent-harness/references/permission-model.md` |
| 13 | "Making Claude Code safer with sandboxing" | https://www.anthropic.com/research/claude-code-sandboxing | 2025-10-20 | `agent-deploy/references/secure-deployment.md` |
| 14 | "Infrastructure noise in agentic coding evals" | https://www.anthropic.com/research/infrastructure-noise | 2026-02-05 | `eval-run/references/running-in-ci.md`, `eval-run/references/cost-estimation.md`, `eval-analyze/references/reliability.md` |

Two articles cited before this set: "How we contain Claude across products"
(https://www.anthropic.com/research/how-we-contain-claude, 2026-05-25), cited by
`agent-deploy/references/secure-deployment.md`, and "Demystifying evals for AI
agents" (https://www.anthropic.com/research/demystifying-evals-for-ai-agents, 2026-01-09),
cited by `eval-analyze/references/reliability.md` and `diagnosis.md`. Paths in
the last column are under `skills/`; `agent-design` means files of
`skills/agent-design/` (its references and `scripts/_design.py`). Where an
article and today's documentation disagree (for example the auto-mode article's
statement that a headless run is terminated after repeated denials, which the
permission-modes page no longer says), the references follow the documentation
and say so.

## Not included

The plugin's fixtures (a library book reservations domain), templates, runner,
references and eval cases are original work written for this plugin.
