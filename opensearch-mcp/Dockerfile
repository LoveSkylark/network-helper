FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir opensearch-mcp-server-py==0.12.0

EXPOSE 9900

# Streamable HTTP so Open WebUI can connect over mcp-net. OpenSearch connection comes from env vars.
CMD ["python", "-m", "mcp_server_opensearch", "--transport", "stream", "--host", "0.0.0.0", "--port", "9900"]
