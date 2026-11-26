FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir opensearch-mcp-server-py==0.12.0

COPY auth_entrypoint.py /app/auth_entrypoint.py

RUN groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --create-home mcp

USER mcp
EXPOSE 9900

CMD ["python", "/app/auth_entrypoint.py"]
