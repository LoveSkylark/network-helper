FROM ghcr.io/open-webui/open-webui@sha256:d6c085678f7e3f474aa2a92ac9831cb68759dcfd951de250ebbb37dac5cd0255

ENV COPILOT_CLI_EXTRACT_DIR=/opt/copilot-sdk-runtime
RUN pip install --no-cache-dir microsoft-copilot-sdk==2.0.1 \
    && python -m copilot download-runtime --in-process
COPY copilot_pipe.py /app/backend/copilot_pipe.py
COPY mcp_status.py /app/backend/mcp_status.py
COPY mcp-status.patch /tmp/mcp-status.patch
RUN patch --batch --forward --fuzz=0 -d /app/backend -p1 < /tmp/mcp-status.patch \
    && rm /tmp/mcp-status.patch
COPY bootstrap_copilot_pipe.py /opt/bootstrap_copilot_pipe.py
