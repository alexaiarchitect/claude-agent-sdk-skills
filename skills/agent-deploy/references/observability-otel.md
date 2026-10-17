# Observability: OpenTelemetry from a subprocess you do not control

## Where the telemetry comes from

The SDK produces **no telemetry of its own**. The Claude Code CLI it spawns is
instrumented — spans around each model request and tool execution, metrics for
token and cost counters, structured log events for prompts and tool results —
and it exports **directly to your collector**. The SDK's job is to pass
configuration through.

That configuration is environment variables, which you can set in two places:

| Where | When |
|---|---|
| the process environment (shell, container, orchestrator) | production. Every `query()` picks it up with no code change |
| `ClaudeAgentOptions.env` | when different agents in one process need different settings. In Python `env` **merges** into the inherited environment; in TypeScript it replaces it |

## Turning it on

Three independent signals, each with its own switch and exporter. Nothing is
exported until `CLAUDE_CODE_ENABLE_TELEMETRY=1` — **exporters alone do
nothing**, which is `HST030`'s warning case.

| Signal | Contains | Enable with |
|---|---|---|
| Metrics | counters for tokens, cost, sessions, lines of code, tool decisions | `OTEL_METRICS_EXPORTER` |
| Log events | one record per prompt, API request, API error, tool result | `OTEL_LOGS_EXPORTER` |
| Traces (beta) | spans per interaction, model request, tool call and hook | `OTEL_TRACES_EXPORTER` **plus** `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` |

```bash
CLAUDE_CODE_ENABLE_TELEMETRY=1
CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1     # traces only
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.example.com:4318
```

**Telemetry off is not free of consequences.** A session that does not fetch
the interactive feature flags — which includes one with telemetry disabled, one
on a third-party provider and one holding a gateway token — is exactly the
session that starts in **`auto`** permission mode on Claude Code
2.1.285–2.1.301 when `permission_mode` is left unset (2.1.302 starts it in
`default`, per its changelog). So a deployment that turns telemetry off to avoid
exporting prompts also has to pass `permission_mode` explicitly, or on those
versions its allow rules quietly stop settling calls.

Two cost fields worth exporting beside the token counters: every `model_usage`
row carries `costBasis` (`list` | `managed` | `unknown`, Claude Code 2.1.246+)
and `thinkingTokens`, neither of which is on the 0.2.168 `ModelUsage` TypedDict
— read both with `.get()`. A dashboard that charts cost without the basis
cannot tell a list-price estimate from a negotiated one, and `model_usage`
routinely holds more than one model (measured 2026-10-11: the agent's Sonnet 5.5
plus the CLI's background `claude-haiku-5-5`), so aggregate per model rather
than taking the first row.

Event fields added recently, worth a column in the collector (from the changelog;
the monitoring page does not list them yet):

| Event | Field | Since |
|---|---|---|
| `api_request` | `cache_creation_5m_tokens`, `cache_creation_1h_tokens` (cache writes split by lifetime) | 2.1.300 |
| `tool_decision` | `classifier_verdict`, `permission_mode` (tell an auto-mode classifier decision from a permission rule) | 2.1.301 |
| `tool_decision` | `classifier_category` (the built-in rule a classifier block matched; needs `OTEL_LOG_TOOL_DETAILS=1`) | 2.1.301, fixed 2.1.302 |
| trace spans | GenAI semantic-convention attributes such as `gen_ai.provider.name`, `gen_ai.conversation.id`, `gen_ai.tool.name`, `error.type` | 2.1.300 |

A low `OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT` pushed `tool_use_id`,
`tool_source` and `tool_parameters` off `tool_decision` before 2.1.302. The
model the client-side auto-mode classifier uses is chosen with
`CLAUDE_CODE_AUTO_MODE_MODEL` (2.1.302, changelog only; it does not change
server-side auto mode), so a classifier's tokens can show up under a model the
agent never named.

## The spans

| Span | Wraps |
|---|---|
| `claude_code.interaction` | one turn of the agent loop, prompt to response |
| `claude_code.llm_request` | one call to the API, with model, latency, token counts |
| `claude_code.tool` | one tool invocation, with children `claude_code.tool.blocked_on_user` (the permission wait) and `claude_code.tool.execution` |
| `claude_code.hook` | one hook execution. Needs detailed beta tracing (`ENABLE_BETA_TRACING_DETAILED=1` and `BETA_TRACING_ENDPOINT`), which also changes where logs and traces go |

`llm_request`, `tool` and `hook` nest under the enclosing `interaction`. When
the agent spawns a subagent, the subagent's spans nest under the parent's
`claude_code.tool` span, so a whole delegation chain is one trace — which is the
single most useful thing this gives you for a multi-agent deployment.

Spans carry `session.id` by default, so several `query()` calls against one
session filter into a timeline.

## Linking to your application

The SDK injects W3C trace context (`TRACEPARENT`/`TRACESTATE`) into the child
process when an OpenTelemetry span is active in your app, so
`claude_code.interaction` becomes a child of your span and the agent run appears
inside your trace rather than as a disconnected root. Event log records carry
the same context, so events join to spans. The CLI also forwards `TRACEPARENT`
to every Bash command it runs, so a command's own spans nest under
`claude_code.tool.execution`.

Setting `TRACEPARENT` explicitly in `options.env` skips auto-injection, if you
need to pin a parent.

## Naming and attribution

By default `service.name` is `claude-code` — useless when several agents export
to one collector. Override it:

```python
env={
    "OTEL_SERVICE_NAME": "reservations-agent",
    "OTEL_RESOURCE_ATTRIBUTES": "service.version=1.4.0,deployment.environment=production",
}
```

The CLI's identity attributes describe **your service's credential**, not the
end user the agent acted for. To attribute per request, add the user and tenant
as resource attributes on each `query()` call, percent-encoding the values —
`OTEL_RESOURCE_ATTRIBUTES` reserves commas, spaces and equals signs.

## Sensitive data: off by default, and keep it that way

Telemetry is structural: durations, model names, tool names always; token counts
when the API returned usage. **Content is not recorded by default.** Four opt-in
variables add it:

| Variable | Adds |
|---|---|
| `OTEL_LOG_USER_PROMPTS=1` | prompt text on `user_prompt` events and the `interaction` span |
| `OTEL_LOG_TOOL_DETAILS=1` | tool input arguments — file paths, shell commands, search patterns — and real agent, skill, plugin and MCP server names on the cost and token metrics |
| `OTEL_LOG_TOOL_CONTENT=1` | a `tool.output` span event with file contents, Bash output and MCP/WebFetch/WebSearch results, truncated at 60 KB (`CLAUDE_CODE_OTEL_CONTENT_MAX_LENGTH`). Requires tracing |
| `OTEL_LOG_RAW_API_BODIES` | full Messages API request and response JSON, including the entire conversation history. `1` for inline, `file:<dir>` for untruncated on disk. Enabling it implies consent to everything the three above reveal |

Leave all four unset unless the pipeline is approved to store what the agent
handles. For an agent that reads customer data, the debugging value is real and
the exposure is total; decide once, in writing.

## When OpenTelemetry is not the right answer

For an LLM-shaped view — prompts, completions, tool calls as first-class
objects rather than spans — **OpenInference** publishes
`openinference-instrumentation-claude-agent-sdk` (Arize). It instruments the
SDK from your side of the process boundary rather than reading the CLI's
export, so it sees what your code sees and nothing the subprocess does
internally. The two are complementary: OTEL for operational health, OpenInference
(or Braintrust, Langfuse, LangSmith, MLflow) for trace inspection and eval
tooling.

An agent that calls the Claude API or Managed Agents directly, rather than
through the Agent SDK's CLI, is traced differently: the `anthropic` package
emits its own spans and the API can deliver server-side spans under the same
`traceparent`. The Claude Cookbooks' OpenTelemetry tracing notebook walks
through that; none of it applies to the CLI's export described above.

This plugin's own runner writes `*.trace.jsonl` from the message stream, which
is a third thing again: a replayable artefact a grader can re-read offline with
no collector involved.

---

Sources: <https://code.claude.com/docs/en/agent-sdk/observability> (signal
catalog, enabling export, span names, trace linking, tagging, end-user
attribution, sensitive-data flags),
<https://code.claude.com/docs/en/monitoring-usage> (metric and event
reference, traces beta),
<https://code.claude.com/docs/en/agent-sdk/hosting#observability>,
<https://code.claude.com/docs/en/env-vars>;
<https://github.com/Arize-ai/openinference> (package
`openinference-instrumentation-claude-agent-sdk`);
`anthropics/claude-cookbooks` `observability/opentelemetry_tracing.ipynb` at
`a162e01` (Claude API and Managed Agents tracing);
<https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md> (2.1.300–2.1.302
event fields, `CLAUDE_CODE_AUTO_MODE_MODEL`, the 2.1.302 unset-mode default);
<https://code.claude.com/docs/en/permission-modes> (why telemetry-off sessions
start in `auto` on 2.1.285–2.1.301; 2.1.302 is changelog-only), <https://code.claude.com/docs/en/agent-sdk/cost-tracking>;
`claude-agent-sdk` 0.2.168
`_internal/transport/subprocess_cli.py:814-860` (env merge and trace-context
injection), `types.py:1669` (`ModelUsage`). The two-model `model_usage` and
`costBasis: "list"` were measured by this plugin on 2026-10-11 against SDK
0.2.165 with bundled CLI 2.1.294. Re-read 2026-10-11 against claude-agent-sdk
0.2.165 / Claude Code 2.1.296 docs; re-read 2026-10-17 against claude-agent-sdk
0.2.168 / Claude Code 2.1.302 docs.
