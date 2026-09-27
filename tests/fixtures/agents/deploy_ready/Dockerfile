# Library reservations agent, containerised.
# No credential is baked in: ANTHROPIC_BASE_URL points at a gateway that adds
# the API key after the request leaves this container.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 agent
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py ./

# Isolation: no ambient CLAUDE.md or settings, no auto memory.
ENV CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \
    CLAUDE_CONFIG_DIR=/work/.claude \
    AGENT_WORK_ROOT=/work \
    CLAUDE_MODEL=claude-sonnet-5-5

# Credentials arrive from the gateway, never from the image.
ENV ANTHROPIC_BASE_URL=http://claude-gateway.internal:8080

# Telemetry: the collector endpoint is set per environment.
ENV CLAUDE_CODE_ENABLE_TELEMETRY=1 \
    CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1 \
    OTEL_TRACES_EXPORTER=otlp \
    OTEL_METRICS_EXPORTER=otlp \
    OTEL_LOGS_EXPORTER=otlp \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
# ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.internal:4318

RUN mkdir -p /work && chown -R agent:agent /work /app
USER agent
VOLUME ["/work"]

# Liveness: the agent answers on its own port; the CLI subprocess does not listen.
HEALTHCHECK --interval=30s --timeout=5s CMD python3 -c "import agent; print('ok')"

CMD ["python3", "agent.py"]
