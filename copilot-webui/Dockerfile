FROM ghcr.io/open-webui/open-webui:main

ENV COPILOT_CLI_EXTRACT_DIR=/opt/copilot-sdk-runtime
RUN pip install --no-cache-dir microsoft-copilot-sdk==2.0.1 \
    && python -m copilot download-runtime --in-process
COPY copilot_pipe.py /app/backend/copilot_pipe.py
COPY mcp_status.py /app/backend/mcp_status.py
COPY mcp-status.patch /tmp/mcp-status.patch
RUN patch --batch --forward --fuzz=0 -d /app/backend -p1 < /tmp/mcp-status.patch \
    && rm /tmp/mcp-status.patch
