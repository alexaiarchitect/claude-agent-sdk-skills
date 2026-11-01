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

Snapshot: `3be907edb9c86269d30d1427a77937dd788d6419` (2026-11-04, `main` =
`v0.2.178`, which bundles CLI 2.1.318; `v0.2.177` added `HookMatcher.on_failure`,
13 lines in `types.py` plus its handling in `_internal/query.py`, so every
`types.py:N` citation is re-pinned to 0.2.178 (+11 from line 855, +13 from line
2321); previously `e0da9b95223d3d112bfbccad41d2a32bad923bb5` on 2026-11-02 (after
`v0.2.176`, `types.py` byte-identical to 0.2.174 then),
`27858cbba9ecee26a06a90b8d39d3b5596121d11` on 2026-10-29,
`0e89b298e771259378a6cd3734e00d323dff5703` on 2026-10-24, `f93e29cc` after
`v0.2.168`, `b6e9d12f` and `bbf09e3c`, which was `v0.2.162`). Behaviour was
measured against the installed `claude-agent-sdk` **0.2.178 wheel (bundled CLI
2.1.318)** on 2026-11-04, the 0.2.176 wheel (bundled CLI 2.1.316) on 2026-11-02,
and the 0.2.174 wheel (bundled CLI 2.1.310) up to 2026-10-29; earlier
figures in this plugin's references name the wheel they came from (0.2.174 with
CLI 2.1.310, 0.2.168 with CLI 2.1.301, 0.2.165 with CLI 2.1.294, or 0.2.162 with
CLI 2.1.285). Names first released in 0.2.166 are
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

Snapshot: `26382c08758260c9f5deb2019d8fe851f89fa9ae` (2026-11-04, Claude Code
2.1.318; previously `1a0f9a9d18e1272d3fbaa817d192b6b057bba623` at 2.1.316 on
2026-11-02, `58d6da1e34d6cd1c6379dcbf568bd66f5f9b6102` at 2.1.312 on
2026-10-29, `318b7e6ac4e726e88a4ad326214866a93c373b1b` at 2.1.310 on
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

Snapshot: `785d7a06457b3413727f386b9c470083feb23c49` (2026-11-02, read 2026-11-04:
the `claude_agent_sdk/` notebooks move to Haiku 5.5 defaults and pass
`setting_sources=[]` explicitly; nothing under `observability/` changed;
previously `c43f56d0360b9b1f631bd090fd199231d4c880cc` from 2026-10-29,
`a162e0184e71` from 2026-10-17, `9c1e493d` and `d7265d6a`).
The `claude_agent_sdk/` notebooks informed the hooks, MCP, session and hosting
guidance; the `tool_evaluation/` notebook informed the tool-description advice;
the OpenTelemetry tracing cookbook (`observability/opentelemetry_tracing.ipynb`)
is cited by `skills/agent-deploy/references/observability-otel.md`.
No notebook content is redistributed.

## Agent Skills (`anthropics/skills`)

    Copyright (c) Anthropic, PBC
    https://github.com/anthropics/skills

Snapshot: `ca45fc496a3436251f191354091d557da31c15b5` (2026-10-29, unmoved on
2026-11-02 and 2026-11-04; the one new commit touches `mcp-builder` only; previously `dbd4588f`, unmoved from
2026-10-09 to 2026-10-24, and `8a1541c4`. The `skill-creator` content is
byte-identical across all three). The grader design (burden of
proof on the expectation, no partial credit, critique of weak assertions)
informed this plugin's `llm` grader and rubric guidance. Per-skill license
files apply to that repository's contents; nothing from it is redistributed.

## Code with Claude workshops (`anthropics/cwc-workshops`)

    Copyright 2026 Anthropic PBC
    Licensed under the Apache License, Version 2.0
    https://github.com/anthropics/cwc-workshops

Snapshot: `4c34ec4863df` (2026-10-17, unmoved on 2026-10-24, 2026-10-29, 2026-11-02 and 2026-11-04; previously `068b84bb`. The new commit adds
a managed-agents workshop outside the part this plugin reads). The
`eval-driven-agent-development` workshop's code-versus-judge grader split and
baseline comparison informed the grader catalog. No files are redistributed.

## Claude Agent SDK demos (`anthropics/claude-agent-sdk-demos`)

    Copyright (c) Anthropic, PBC
    No repository-level license file at the snapshot
    https://github.com/anthropics/claude-agent-sdk-demos

Snapshot: `826b2685` (unmoved since 2026-03-13; re-checked 2026-11-04). Used as
example projects for the read-only sweep that checks this plugin's static
readers on real code. Nothing is redistributed.

## Documentation

Claude Code and Agent SDK documentation at `https://code.claude.com/docs/` and
`https://platform.claude.com/docs/`, first read on 2026-09-30, re-read on
2026-10-11 at Claude Code 2.1.296 (85 pages), on 2026-10-17 at Claude Code
2.1.302 (86 pages, adding `settings-reference`) and on **2026-10-24** at Claude
Code **2.1.310** (the same 86 pages, none added or removed), and on
**2026-10-29** at Claude Code **2.1.312** (the same 86 files, 58 pages changed),
and on **2026-11-02** at Claude Code **2.1.316** (the same 86 files, 31 pages
byte-changed, nine with text changes), with the Messages API page on message
threads (`https://platform.claude.com/docs/en/build-with-claude/message-threads`)
added on 2026-11-02, and on **2026-11-04** at Claude Code **2.1.318** (the same 86
files, 23 pages byte-changed, all with text changes);
every reference names the pages it distills and carries the re-read date in its
`Sources:` footer. The TypeScript SDK repository, whose contents are under
Anthropic's commercial terms, was consulted for its documentation only and
nothing from it is included.

## Cited Anthropic articles

Anthropic's published engineering and product articles supply the design
rationale in this plugin's references; current mechanics are always cited from
the documentation above. Articles 1–14 were read on 2026-10-29 and articles
15–23 on 2026-11-02, and articles 24–25 on 2026-11-04, each at the canonical URL below
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
| 15 | "Make long-running agents faster with message threads" (a Messages API feature; the article does not mention the Agent SDK) | https://claude.com/resources/articles/message-threads | 2026-11-02 | `agent-harness/references/context-and-settings.md`, `agent-deploy/references/cost-controls.md`, `agent-sdk/references/glossary.md`, `agent-design` |
| 16 | "How AI agents shape experts' judgment calls" | https://www.anthropic.com/research/agents-judgment-calls | 2026-10-27 | `eval-simulation/references/personas.md`, `eval-criteria/references/judge-options.md`, `eval-criteria/references/rubric-authoring.md`, `agent-create/references/eval-ready-architecture.md`, `agent-sdk/references/glossary.md`, `agent-design` |
| 17 | "Investigating unintended model actions in our evaluations and internal use" (corrected 2026-10-12) | https://www.anthropic.com/research/investigating-unintended-model-actions | 2026-10-09 | `agent-deploy/references/secure-deployment.md`, `agent-debug/references/failure-shapes.md`, `eval-create/references/case-taxonomy.md` |
| 18 | "Building a C compiler with parallel Claudes" | https://www.anthropic.com/research/building-c-compiler | 2026-02-05 | `agent-harness/references/subagent-design.md`, `agent-design` |
| 19 | "An update on Claude Code quality reports" | https://www.anthropic.com/research/april-23-postmortem | 2026-04-23 | `agent-debug/references/failure-shapes.md`, `eval-run/references/running-in-ci.md` |
| 20 | "Introducing advanced tool use for Claude" | https://www.anthropic.com/research/advanced-tool-use | 2025-11-24 | `agent-harness/references/mcp-patterns.md`, `agent-sdk/references/glossary.md`, `agent-design` |
| 21 | "LLMs are making formal software verification feasible at a much larger scale" | https://www.anthropic.com/research/formal-verification | 2026-10-22 | `eval-run/references/cost-estimation.md`, `agent-design` |
| 22 | "Donating Agent Skills to the Agentic AI Foundation" | https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation | 2026-10-22 | `agent-sdk/references/glossary.md`, `agent-design` |
| 23 | "Redesigning source control at Anthropic" (updated 2026-10-15) | https://www.anthropic.com/research/redesigning-source-control | 2026-10-13 | `agent-deploy/references/hosting-options.md`, `agent-review/references/review-checklist.md` |
| 24 | "An alignment assessment of the UK AISI cybertesting incident" (Bogdan, Qi, Smilkov, Henighan et al.; an alignment write-up about an external evaluation, not SDK guidance: the isolation rules drawn from it are this plugin's inferences) | https://www.anthropic.com/research/alignment-assessment-ukaisi | 2026-10-23 | `agent-deploy/references/secure-deployment.md`, `agent-debug/references/failure-shapes.md`, `eval-create/references/case-taxonomy.md` |
| 25 | "Manage costs and demonstrate ROI for Claude Code on Google Cloud" (interactive Claude Code behind the Claude apps gateway; only its gateway and OpenTelemetry patterns are cited) | https://claude.com/resources/articles/how-to-manage-costs-and-demonstrate-roi-for-claude-code-on-google-cloud | 2026-10-27 | `agent-deploy/references/cost-controls.md`, `agent-deploy/references/observability-otel.md` |

Two articles cited before this set: "How we contain Claude across products"
(https://www.anthropic.com/research/how-we-contain-claude, 2026-05-25), cited by
`agent-deploy/references/secure-deployment.md`, and "Demystifying evals for AI
agents" (https://www.anthropic.com/research/demystifying-evals-for-ai-agents, 2026-01-09),
cited by `eval-analyze/references/reliability.md` and `diagnosis.md`. Paths in
the last column are under `skills/`; `agent-design` means files of
`skills/agent-design/` (its references and `scripts/_design.py`). Where an
article and today's documentation disagree (for example the auto-mode article's
statement that a headless run is terminated after repeated denials, which the
permission-modes page no longer says, or the advanced-tool-use article, which
predates the Agent SDK's default-on tool search), the references follow the
documentation and say so. Article 22 is the first one under
`anthropic.com/news/`.

## Not included

The plugin's fixtures (a library book reservations domain), templates, runner,
references and eval cases are original work written for this plugin.
