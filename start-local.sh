#!/bin/bash
# start-local.sh — Arranca el servicio IR RAG localmente y lo expone con ngrok.
# Uso: ./start-local.sh
#
# Requisitos:
#   - ngrok configurado (ngrok config add-authtoken <token>)
#   - LLM_API_KEY exportada o en .env
#
# Salir con Ctrl+C para detener todo.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Cargar .env si existe
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Verificar requisitos
if [ -z "$LLM_API_KEY" ] && [ -z "$GROQ_API_KEY" ]; then
  echo "⚠️  ADVERTENCIA: No se detectó LLM_API_KEY ni GROQ_API_KEY."
  echo "    El servicio funcionará pero POST /answer devolverá 503."
  echo "    Configura la clave con: export LLM_API_KEY=gsk_..."
  echo ""
fi

if [ ! -d data/chroma ] || [ -z "$(ls data/chroma/ 2>/dev/null)" ]; then
  echo "⚠️  No hay índice Chroma. Construyéndolo..."
  PYTHONPATH=./src python3 scripts/build_index.py
fi

# Encontrar ngrok
NGROK=""
if command -v ngrok >/dev/null 2>&1; then
  NGROK="ngrok"
elif [ -x "$HOME/.local/bin/ngrok" ]; then
  NGROK="$HOME/.local/bin/ngrok"
fi

# Lanzar el servicio en background
echo "🚀 Arrancando el servicio en el puerto 7860..."
DATA_DIR=./data \
CHROMA_DIR=./data/chroma \
CHROMA_COLLECTION=ir_corpus \
PYTHONPATH=./src \
python3 -m uvicorn ir_rag.api:app --host 0.0.0.0 --port 7860 \
  > /tmp/ir-rag.log 2>&1 &
SERVICE_PID=$!
echo "   PID: $SERVICE_PID"

# Función para limpiar al salir
cleanup() {
  echo ""
  echo "🛑 Deteniendo servicio..."
  kill $SERVICE_PID 2>/dev/null || true
  if [ -n "$NGROK_PID" ]; then
    kill $NGROK_PID 2>/dev/null || true
  fi
  exit 0
}
trap cleanup INT TERM

# Esperar a que el servicio esté listo
echo "⏳ Esperando a que el servicio esté listo..."
for i in {1..30}; do
  if curl -fsS --max-time 2 http://127.0.0.1:7860/health >/dev/null 2>&1; then
    echo "✅ Servicio listo"
    break
  fi
  sleep 1
done

# Verificar
HEALTH=$(curl -fsS --max-time 5 http://127.0.0.1:7860/health 2>&1 || echo "FAIL")
echo "   Health check: $HEALTH"
echo ""

# Lanzar ngrok si está disponible
if [ -n "$NGROK" ]; then
  echo "🌐 Lanzando ngrok en el puerto 7860..."
  $NGROK http 7860 --log /tmp/ngrok.log --log-format=json > /dev/null 2>&1 &
  NGROK_PID=$!

  # Esperar a que ngrok asigne la URL
  sleep 4
  NGROK_URL=""
  for i in {1..15}; do
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | \
      python3 -c "import json,sys; data=json.load(sys.stdin); print(data['tunnels'][0]['public_url'] if data.get('tunnels') else '')" 2>/dev/null || true)
    if [ -n "$NGROK_URL" ]; then
      break
    fi
    sleep 1
  done

  echo ""
  echo "============================================================"
  echo "🎉 Tu servicio está disponible públicamente en:"
  echo "   $NGROK_URL"
  echo ""
  echo "📋 Para usar con Postman:"
  echo "   POST  $NGROK_URL/answer"
  echo "   Body: {\"question\": \"## ¿Qué es BM25?\"}"
  echo ""
  echo "📊 Health check:"
  echo "   GET   $NGROK_URL/health"
  echo "============================================================"
  echo ""
  echo "Presiona Ctrl+C para detener."
  echo ""
else
  echo "ℹ️  ngrok no encontrado. El servicio solo está en localhost."
  echo "    Para exponerlo: instala ngrok y configura el authtoken."
fi

# Mostrar logs en vivo
tail -f /tmp/ir-rag.log
