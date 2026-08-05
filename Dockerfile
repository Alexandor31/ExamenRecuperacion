# Hugging Face Spaces — Docker SDK
# https://huggingface.co/docs/hub/spaces-sdks-docker
#
# This Dockerfile is optimized for Hugging Face Spaces with Docker SDK:
# - Builds the Chroma index at build time (HF provides 16 GB RAM, plenty)
# - Pre-downloads all open-access PDFs
# - Exposes port 7860 (HF expects this port)

FROM python:3.11-slim

# Environment: keep Python output unbuffered, telemetry off, CPU-only torch.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TRANSFORMERS_VERBOSITY=error \
    TOKENIZERS_PARALLELISM=false \
    DATA_DIR=/app/data \
    CHROMA_DIR=/app/data/chroma \
    PORT=7860

WORKDIR /app

# System dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project (PDFs come from the repo via git lfs).
COPY . .

# Pre-create dirs.
RUN mkdir -p /app/data/chroma /app/corpus/articles

# --- Build-time setup --------------------------------------------------
# 1. Download any missing open-access PDFs (Baeza-Yates is user-provided).
# 2. Build the Chroma index so the service responds instantly on boot.
#    HF Spaces provides ample RAM, so this completes in ~2-3 min.
RUN python scripts/download_corpus.py || true \
    && echo "--- PDFs in corpus ---" \
    && (ls -lh corpus/*.pdf corpus/articles/*.pdf 2>/dev/null || echo "no PDFs") \
    && echo "--- Building Chroma index ---" \
    && python scripts/build_index.py \
    && echo "--- Index ready ---"

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl --fail http://localhost:${PORT:-7860}/health || exit 1

# Default command for HF Spaces. Use the literal port 7860 — HF always routes
# to this port regardless of $PORT, so we hardcode for clarity.
CMD uvicorn ir_rag.api:app --host 0.0.0.0 --port 7860
