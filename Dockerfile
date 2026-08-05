FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TRANSFORMERS_VERBOSITY=error \
    TOKENIZERS_PARALLELISM=false \
    DATA_DIR=/app/data \
    CHROMA_DIR=/app/data/chroma \
    AUTO_BUILD_INDEX=true \
    PORT=7860

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-download the open-access PDFs at build time. This is fast (~30 s)
# and ensures the corpus is in place for AUTO_BUILD_INDEX at startup.
# Baeza-Yates is copyrighted and not downloaded; it can be uploaded to the
# persistent volume later.
RUN python scripts/download_corpus.py || true \
    && ls -lh corpus/*.pdf corpus/articles/*.pdf 2>/dev/null || echo "no PDFs"

# DO NOT build the Chroma index during Docker build. The build step has
# limited memory/time on free tiers and the embedding pass over 3,584 chunks
# can OOM. Instead, AUTO_BUILD_INDEX=true (set above + in fly.toml env) makes
# the FastAPI lifespan build the index lazily on first startup, where the
# process has the full 2 GB RAM and is not constrained by build timeouts.

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl --fail http://localhost:${PORT:-7860}/health || exit 1

CMD uvicorn ir_rag.api:app --host 0.0.0.0 --port ${PORT:-7860}
