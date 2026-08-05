FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr.
# Render.com sets $PORT automatically; default to 7860 for HF Spaces / local.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=7860 \
    DATA_DIR=/app/data \
    CHROMA_DIR=/app/data/chroma \
    AUTO_BUILD_INDEX=false \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TRANSFORMERS_VERBOSITY=error \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

# System dependencies (curl for HEALTHCHECK).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project.
COPY . .

# Pre-create persistent data dirs.
RUN mkdir -p /app/data/chroma /app/corpus/articles

# --- Build-time setup --------------------------------------------------
# Step 1: download the open-access PDFs into the image (skip if already there).
# Step 2: build the Chroma index so the service responds instantly on boot.
#         Baeza-Yates is copyrighted and NOT downloaded; if it's not present
#         in the repo, the registry entry simply contributes zero chunks.
RUN python scripts/download_corpus.py || true \
    && echo "--- PDFs in corpus ---" \
    && ls -lh corpus/*.pdf corpus/articles/*.pdf 2>/dev/null || true \
    && echo "--- Building Chroma index ---" \
    && python scripts/build_index.py \
    && echo "--- Index built ---" \
    && ls -lh data/chroma/ 2>/dev/null || true

# HF Spaces / Render expose this port.
EXPOSE 7860

# Liveness probe.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl --fail http://localhost:${PORT}/health || exit 1

# Use a shell wrapper so we read $PORT at runtime (Render sets it dynamically).
CMD ["sh", "-c", "uvicorn ir_rag.api:app --host 0.0.0.0 --port ${PORT:-7860}"]
