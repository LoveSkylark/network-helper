FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM python:3.15.2-alpine3.24@sha256:2b4b04f31a4a009c1fadf7ce9338471f288488199cf43dcd1af71f244ea550aa AS builder

# Pinned upstream commit so rebuilds are reproducible. Override with --build-arg UPSTREAM_REF=<sha>.
ARG UPSTREAM_REPO=https://github.com/mhajder/librenms-mcp.git
ARG UPSTREAM_REF=817809b8ddd1df0b42ebff3184e72dd34f830cce

RUN apk add --no-cache git

COPY --from=uv /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

RUN git clone "${UPSTREAM_REPO}" /app \
    && git -C /app checkout "${UPSTREAM_REF}"

WORKDIR /app

RUN uv sync --locked --all-extras --no-install-project --no-dev --no-editable

RUN uv sync --locked --all-extras --no-dev --no-editable


FROM python:3.15.2-alpine3.24@sha256:2b4b04f31a4a009c1fadf7ce9338471f288488199cf43dcd1af71f244ea550aa

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    MCP_TRANSPORT=http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8000

RUN addgroup -g 10001 appuser \
    && adduser -D -u 10001 -G appuser appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["librenms-mcp"]
