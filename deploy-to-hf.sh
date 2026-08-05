#!/bin/bash
# deploy-to-hf.sh — Sube el proyecto a Hugging Face Spaces.
# Uso: ./deploy-to-hf.sh [nombre-del-space]
#
# Requisitos:
#   - huggingface-cli instalado: pip install -U huggingface_hub
#   - haber iniciado sesión: huggingface-cli login
#   - el Space ya creado en https://huggingface.co/new-space (SDK: Docker)

set -e

SPACE_NAME="${1:-ir-rag-recuperacion}"
HF_USER=$(huggingface-cli whoami 2>/dev/null | head -1 | awk '{print $1}' || echo "")
if [ -z "$HF_USER" ]; then
  echo "✗ Error: no has iniciado sesión en Hugging Face."
  echo "  Ejecuta: huggingface-cli login"
  exit 1
fi

REPO_URL="https://huggingface.co/spaces/${HF_USER}/${SPACE_NAME}"
WORK_DIR="/tmp/hf-deploy-${SPACE_NAME}"

echo "📦 Desplegando en $REPO_URL"
echo ""

# 1. Clonar el Space (vacío al inicio)
if [ -d "$WORK_DIR" ]; then
  rm -rf "$WORK_DIR"
fi
echo "1/5 Clonando el Space..."
git clone "$REPO_URL.git" "$WORK_DIR" 2>&1 | tail -3 || {
  echo "✗ Error clonando. Verifica que el Space existe y tienes acceso."
  exit 1
}

# 2. Copiar los archivos del proyecto (excluyendo lo innecesario)
echo "2/5 Copiando archivos del proyecto..."
cd /home/alexander/RI/ExamenSupletorio/
rsync -av \
  --exclude='.venv/' \
  --exclude='data/chroma/' \
  --exclude='data/index_manifest.json' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='*.log' \
  --exclude='.env' \
  --exclude='.git/' \
  --exclude='tests/' \
  --exclude='docs/' \
  --exclude='start-local.sh' \
  --exclude='start-resilient.sh' \
  --exclude='deploy-to-hf.sh' \
  --exclude='app.py' \
  --exclude='.venv' \
  ./ "$WORK_DIR/"

# 3. Copiar el index pre-construido (ahorra ~3 min de build en HF)
echo "3/5 Copiando índice Chroma pre-construido..."
mkdir -p "$WORK_DIR/data/chroma"
if [ -d "data/chroma" ]; then
  cp -r data/chroma/* "$WORK_DIR/data/chroma/" 2>&1 | tail -3 || true
  cp data/index_manifest.json "$WORK_DIR/data/" 2>&1 || true
fi

# 4. Configurar git lfs para PDFs
echo "4/5 Configurando git lfs..."
cd "$WORK_DIR"
git lfs install --local 2>&1 | tail -1
git lfs track "*.pdf" 2>&1 | tail -1

# 5. Commit y push
echo "5/5 Haciendo commit y push..."
git add -A
git commit -m "Deploy IR RAG service" 2>&1 | tail -3

# Push con autenticación (asume que hf-cli ya configuró las credenciales)
git push 2>&1 | tail -10

echo ""
echo "============================================================"
echo "🎉 ¡Deploy iniciado!"
echo "============================================================"
echo ""
echo "📊 Monitorea el progreso en:"
echo "   https://huggingface.co/spaces/${HF_USER}/${SPACE_NAME}"
echo ""
echo "🔑 IMPORTANTE: configura LLM_API_KEY como secreto en"
echo "   Settings → Variables and secrets → New secret"
echo "   Name:  LLM_API_KEY"
echo "   Value: gsk_tu_clave_groq"
echo ""
echo "⏳ El primer deploy tarda ~3-5 min (descarga modelos + arranca)."
echo ""
