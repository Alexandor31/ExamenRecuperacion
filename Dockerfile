FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr.
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

# System dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project.
COPY . .

# Create data dirs (the actual volume is mounted at /app/data at runtime).
RUN mkdir -p /app/data/chroma /app/corpus/articles /root/.cache/huggingface

# --- Build-time setup --------------------------------------------------
# Step 1: download the open-access PDFs (skip if already in the image).
# Step 2: build the Chroma index so the service responds instantly on boot.
#         CPU-only torch makes this take ~2 min instead of ~5.
RUN python scripts/download_corpus.py || true \
    && echo "--- PDFs in corpus ---" \
    && (ls -lh corpus/*.pdf corpus/articles/*.pdf 2>/dev/null || echo "no PDFs yet") \
    && echo "--- Building Chroma index (CPU-only) ---" \
    && python scripts/build_index.py \
    && echo "--- Index built ---"

# Fly / Render / HF Spaces expose this port.
EXPOSE 7860

# Shell-form CMD: $PORT is set by Fly.toml (7860). Falls back to 7860 otherwise.
CMD uvicorn ir_rag.api:app --host 0.0.0.0 --port ${PORT:-7860}
