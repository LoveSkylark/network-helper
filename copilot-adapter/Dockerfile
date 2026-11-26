FROM python:3.12-slim

ENV COPILOT_CLI_EXTRACT_DIR=/opt/copilot-sdk-runtime \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
      "microsoft-copilot-sdk==2.0.1" \
      "fastapi==0.115.12" \
      "uvicorn==0.34.0" \
      "httpx==0.28.1" \
      "PyJWT[crypto]==2.10.1" \
    && python -m copilot download-runtime --in-process

COPY main.py test_main.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
