FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.12-slim-bookworm AS builder

# Pinned upstream commit so rebuilds are reproducible. Override with --build-arg UPSTREAM_REF=<sha>.
ARG UPSTREAM_REPO=https://github.com/CiscoDevNet/cisco-ise-mcp-official.git
ARG UPSTREAM_REF=521cf8e468ce48b008bad295bdbe100b2f428b41

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

RUN git clone "${UPSTREAM_REPO}" /app \
    && git -C /app checkout "${UPSTREAM_REF}"

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=5000

RUN groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --create-home mcp

WORKDIR /app
COPY --from=builder /app /app

USER mcp
EXPOSE 5000
ENTRYPOINT ["python", "server.py"]
