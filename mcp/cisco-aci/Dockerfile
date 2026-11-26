FROM python:3.12-slim-bookworm AS builder

# Pinned upstream commit so rebuilds are reproducible. Override with --build-arg UPSTREAM_REF=<sha>.
ARG UPSTREAM_REPO=https://github.com/CiscoDevNet/mcp_server_cisco_aci_community.git
ARG UPSTREAM_REF=cf9f9fc80addcac9d2a46d0657642cba02247cd0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone "${UPSTREAM_REPO}" /src \
    && git -C /src checkout "${UPSTREAM_REF}"

RUN pip install --no-cache-dir --prefix=/install -r /src/requirements.txt

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

RUN groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --create-home mcp

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --from=builder /src/scripts/server.py /app/server.py
COPY aci_auth.py /app/aci_auth.py
COPY http_entrypoint.py /app/http_entrypoint.py

USER mcp
EXPOSE 8000
ENTRYPOINT ["python", "http_entrypoint.py"]
