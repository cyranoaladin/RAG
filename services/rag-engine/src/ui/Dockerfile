FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/rag-engine/requirements.lock /tmp/requirements.lock
COPY services/rag-engine/src/ui/requirements.txt /tmp/ui-requirements.txt
COPY scripts/e2e/smoke-ui-runtime-imports.sh /usr/local/bin/smoke-ui-runtime-imports
RUN pip install --upgrade pip \
 && python -m pip install --no-cache-dir -r /tmp/ui-requirements.txt -c /tmp/requirements.lock \
 && python -m pip check \
 && chmod 755 /usr/local/bin/smoke-ui-runtime-imports \
 && smoke-ui-runtime-imports

COPY services/rag-engine/src/ui/ ./

EXPOSE 8501

CMD ["streamlit", "run", "app_v2.py", "--server.headless=true", "--server.port=8501", "--server.address=0.0.0.0"]
