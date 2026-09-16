# --- Base ---
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models \
    SENTENCE_TRANSFORMERS_HOME=/models

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python - <<'PY'
from sentence_transformers import SentenceTransformer
SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
PY

COPY app ./app
COPY knowledge ./knowledge
COPY run.py ./run.py

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
