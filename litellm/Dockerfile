FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "litellm[proxy,extra_proxy]==1.110.3" "redis==6.4.0"

RUN prisma generate --schema /usr/local/lib/python3.12/site-packages/litellm_proxy_extras/schema.prisma

COPY litellm/config.yaml litellm/local_only_mcp.py litellm/mcp_policy.py litellm/create_virtual_key.py litellm/test_local_only_mcp.py ./
COPY ["new design/stable_mask.py", "/app/stable_mask.py"]

EXPOSE 4000

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--host", "0.0.0.0", "--port", "4000"]
