FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.13-slim-bookworm AS builder

# Pinned upstream commit so rebuilds are reproducible. Override with --build-arg UPSTREAM_REF=<sha>.
ARG UPSTREAM_REPO=https://github.com/netboxlabs/netbox-mcp-server.git
ARG UPSTREAM_REF=5cba404608c40142b6a65310810024391ab5f6df

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

RUN git clone "${UPSTREAM_REPO}" /app \
    && git -C /app checkout "${UPSTREAM_REF}"

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

RUN uv sync --locked --no-dev

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000

RUN groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --create-home mcp

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/LICENSE ./

USER mcp
EXPOSE 8000
ENTRYPOINT ["netbox-mcp-server"]
