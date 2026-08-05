# Despliegue — cheatsheet

El proyecto está pensado para correr **localmente con `uvicorn`** y exponerse a Internet con **ngrok** (gratis). Esa es la opción recomendada y más confiable. El `Dockerfile` se incluye por si más adelante quieres desplegarlo en otra plataforma (Hugging Face Spaces, Render, etc.).

---

## Opción 1 — Local + ngrok (RECOMENDADA, gratis)

### 1.1 Instalar ngrok (solo una vez)

```bash
# Linux x86_64 / WSL:
wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz -O /tmp/ngrok.tgz
tar -xzf /tmp/ngrok.tgz -C /tmp/
mv /tmp/ngrok $HOME/.local/bin/ngrok
```

### 1.2 Crear cuenta y configurar token

1. <https://dashboard.ngrok.com/signup> (gratis, con Google).
2. <https://dashboard.ngrok.com/get-started/your-authtoken> → copia el token.
3. Configura ngrok:

```bash
ngrok config add-authtoken <TU_TOKEN>
```

### 1.3 Configurar el LLM

```bash
# Opción A — variable de entorno:
export LLM_API_KEY=gsk_tu_clave_groq

# Opción B — archivo .env:
echo "LLM_API_KEY=gsk_tu_clave_groq" > .env
```

Consigue la clave Groq gratis en <https://console.groq.com/keys>.

### 1.4 Arrancar todo con el script

```bash
./start-local.sh
```

Verás algo como:

```
🚀 Arrancando el servicio en el puerto 7860...
✅ Servicio listo
   Health check: {"status":"ok","chunks":3584,...}

🌐 Lanzando ngrok en el puerto 7860...

============================================================
🎉 Tu servicio está disponible públicamente en:
   https://a1b2-c3d4-e5f6.ngrok-free.app

📋 Para usar con Postman:
   POST  https://a1b2-c3d4-e5f6.ngrok-free.app/answer
   Body: {"question": "## ¿Qué es BM25?"}
============================================================
```

> **Importante**: la URL de ngrok cambia cada vez que reinicies ngrok. Mantén la terminal abierta mientras uses el servicio.

### 1.5 Arrancar manualmente (sin script)

Si prefieres control granular:

```bash
# Terminal 1 — el servicio
DATA_DIR=./data CHROMA_DIR=./data/chroma CHROMA_COLLECTION=ir_corpus \
  PYTHONPATH=./src \
  python3 -m uvicorn ir_rag.api:app --host 0.0.0.0 --port 7860

# Terminal 2 — ngrok
ngrok http 7860
```

---

## Opción 2 — Hugging Face Spaces con SDK Docker (gratis)

Si prefieres una URL fija y no depender de tu máquina local, HF Spaces Docker SDK es gratis (CPU basic).

### Pasos resumidos

1. <https://huggingface.co/new-space> → SDK: **Docker** → CPU basic.
2. Clona el Space y sube el código (sin `data/chroma/`, sin PDFs pesados):

```bash
git clone https://huggingface.co/spaces/<usuario>/<space>
cd <space>
rsync -av --exclude='data/chroma/' --exclude='data/index_manifest.json' \
   --exclude='.venv/' --exclude='__pycache__/' --exclude='.git/' \
   /ruta/al/proyecto/ .
git lfs install
git lfs track "*.pdf"
git add .
git commit -m "Deploy"
git push
```

3. Settings → Secrets → añade `LLM_API_KEY`.

4. URL pública: `https://<usuario>-<space>.hf.space`.

> Limitación: el plan CPU basic tiene 16 GB RAM y 2 vCPU gratis, suficiente para este proyecto.

---

## Opción 3 — Render.com (gratis con Docker)

1. Sube el proyecto a GitHub.
2. <https://render.com> → New + → Web Service → conecta el repo.
3. Environment: **Docker**. Plan: **Free**. Health Check Path: `/health`.
4. Environment → Environment Variables → añade `LLM_API_KEY`.
5. URL: `https://<servicio>.onrender.com`.

---

## Verificar los endpoints (cualquier opción)

```bash
HOST=https://<tu-host>

# Health check
curl $HOST/health

# Pregunta válida
curl -X POST $HOST/answer \
     -H 'Content-Type: application/json' \
     -d '{"question": "## ¿Qué es BM25?"}'

# Documentación interactiva
# Abrir en el navegador: $HOST/docs
```

Códigos esperados:

| Código | Cuándo |
|--------|--------|
| 200 | Todo bien. |
| 400 | Falta el campo `question`. |
| 404 | Ruta inexistente. |
| 422 | Markdown sin pregunta extraíble. |
| 500 | Error inesperado del servidor. |
| 503 | Falta `LLM_API_KEY` o el índice está vacío. |

---

## 🎯 Resumen rápido

| Plataforma | Gratis | URL fija | Dificultad | Veredicto |
|---|---|---|---|---|
| **Local + ngrok** | ✅ | ❌ (cambia) | Fácil | ⭐ Recomendado |
| **HF Spaces Docker** | ✅ | ✅ | Media | Buena alternativa |
| **Render** | ✅ | ✅ | Fácil | Buena alternativa |
| **Railway.app** | ✅ $5/mes crédito | ✅ | Fácil | Buena alternativa |
