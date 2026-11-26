FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.13-slim-bookworm AS builder

# Pinned upstream commit so rebuilds are reproducible. Override with --build-arg UPSTREAM_REF=<sha>.
ARG UPSTREAM_REPO=https://github.com/paoloamato2/fortinet-mcp-server.git
ARG UPSTREAM_REF=5c82a1e6e2b7a336cd9b22881d50a658d8bdcb06

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

RUN git clone "${UPSTREAM_REPO}" /app \
    && git -C /app checkout "${UPSTREAM_REF}"

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

RUN uv sync --locked --no-dev --no-install-project
RUN uv pip install --python /app/.venv/bin/python fastmcp==3.2.2

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

RUN groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --create-home mcp

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/server.py /app/fortios_client.py /app/LICENSE ./
COPY --from=builder /app/tools/ ./tools/
COPY http_entrypoint.py /app/http_entrypoint.py

USER mcp
EXPOSE 8000
ENTRYPOINT ["python", "http_entrypoint.py"]
