#!/bin/bash
# start-resilient.sh — Como start-local.sh pero con reconexión automática.
# Si ngrok se cae (red inestable, etc.), este script lo reinicia solo.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if [ -f .env ]; then
  set -a; source .env; set +a
fi

if [ ! -d data/chroma ] || [ -z "$(ls data/chroma/ 2>/dev/null)" ]; then
  PYTHONPATH=./src python3 scripts/build_index.py
fi

NGROK=""
if command -v ngrok >/dev/null 2>&1; then
  NGROK="ngrok"
elif [ -x "$HOME/.local/bin/ngrok" ]; then
  NGROK="$HOME/.local/bin/ngrok"
fi

if [ -z "$NGROK" ]; then
  echo "✗ ngrok no encontrado. Instálalo antes."
  exit 1
fi

# Lanzar uvicorn
echo "🚀 Arrancando servicio en puerto 7860..."
DATA_DIR=./data CHROMA_DIR=./data/chroma CHROMA_COLLECTION=ir_corpus \
PYTHONPATH=./src python3 -m uvicorn ir_rag.api:app --host 0.0.0.0 --port 7860 \
  > /tmp/ir-rag.log 2>&1 &
SERVICE_PID=$!

cleanup() {
  echo ""
  echo "🛑 Deteniendo..."
  kill $SERVICE_PID 2>/dev/null || true
  pkill -f "ngrok http 7860" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# Esperar al servicio
for i in {1..30}; do
  if curl -fsS --max-time 2 http://127.0.0.1:7860/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Bucle con auto-reinicio de ngrok
echo "🌐 Lanzando ngrok con auto-reconexión..."
echo ""
ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT+1))
  echo "[Intento $ATTEMPT] Lanzando ngrok..."
  $NGROK http 7860 --log /tmp/ngrok.log --log-format=json > /dev/null 2>&1 &
  NGROK_PID=$!

  sleep 5
  NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'] if d.get('tunnels') else '')" 2>/dev/null || true)

  if [ -n "$NGROK_URL" ]; then
    echo ""
    echo "============================================================"
    echo "🎉 Servicio público: $NGROK_URL"
    echo "📋 POST $NGROK_URL/answer"
    echo "============================================================"
    echo ""
  else
    echo "⚠️  ngrok no levantó túnel (intento $ATTEMPT), reintentando en 10s..."
    sleep 10
    continue
  fi

  # Vigilar que ngrok siga vivo
  while kill -0 $NGROK_PID 2>/dev/null; do
    if ! curl -fsS --max-time 5 http://127.0.0.1:7860/health >/dev/null 2>&1; then
      echo "⚠️  Servicio no responde, reintentando..."
      break
    fi
    if ! curl -fsS --max-time 3 http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
      echo "⚠️  Túnel ngrok caído, reconectando..."
      break
    fi
    sleep 10
  done

  # Limpiar y volver a empezar
  kill $NGROK_PID 2>/dev/null || true
  pkill -f "ngrok http 7860" 2>/dev/null || true
  sleep 3
done
