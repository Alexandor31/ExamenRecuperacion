FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=7860 \
    AUTO_BUILD_INDEX=true

WORKDIR /app

# System dependencies (curl is needed for the HEALTHCHECK).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Create the data directory used by the persistent Chroma store.
RUN mkdir -p /app/data

EXPOSE 7860

# Liveness probe — Hugging Face and Docker use it to know the container is
# ready to serve traffic. The endpoint is provided by FastAPI/uvicorn.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD curl --fail http://localhost:${PORT}/health || exit 1

# Use a single uvicorn worker; the model loads once per process.
CMD ["uvicorn", "ir_rag.api:app", "--host", "0.0.0.0", "--port", "7860"]
