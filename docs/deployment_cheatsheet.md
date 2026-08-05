# Despliegue — cheatsheet

El proyecto tiene **dos puntos de entrada** según dónde lo despliegues:

| Archivo | Qué hace | Cuándo usarlo |
|---------|----------|---------------|
| `ir_rag/api.py` (vía `uvicorn ir_rag.api:app`) | Servicio FastAPI puro: expone `POST /answer`, `GET /health`, `GET /docs`, etc. | **Render / Fly.io / Railway / HF Docker** — este es el que usa el examen con Postman. |
| `app.py` (vía `streamlit run app.py`) | UI Streamlit que permite probar el pipeline localmente y ver el estado. | **HF Spaces SDK Streamlit** — solo para inspección visual. |

## ⚠️ Por qué dos puntos de entrada

El SDK Streamlit de Hugging Face Spaces **no** permite montar endpoints HTTP personalizados. Si despliegas el proyecto en HF Spaces con SDK Streamlit, `POST /answer` **no será accesible públicamente**, por lo que el profesor no podrá evaluarlo con Postman.

Por eso:

- **Streamlit** = UI opcional para inspección manual.
- **FastAPI** = el servicio real que responde al examen.

Recomendación: despliega la API FastAPI en **Render.com** (gratis con Docker) y, opcionalmente, despliega la UI Streamlit en **Hugging Face Spaces** (también gratis).

---

## Opción 1 — Render.com (RECOMENDADA para el examen, gratis con Docker)

1. Sube el proyecto a GitHub (`corpus/*.pdf` y `data/chroma/` se ignoran con `.gitignore`).
2. Ve a <https://render.com> → **New + → Web Service** → conecta el repo.
3. Configuración:
   - **Environment**: Docker
   - **Region**: cualquiera cercana
   - **Plan**: **Free** (750 h/mes, suficiente)
   - **Health Check Path**: `/health`
4. **Environment → Environment Variables**:
   - `LLM_API_KEY` = tu clave Groq (u otro)
   - Opcional: `LLM_MODEL`, `LLM_API_BASE`
   - Opcional: `AUTO_BUILD_INDEX=true` para construir el índice en cada arranque (lento, 3-4 min)
5. Pulsa **Create Web Service**. Render detecta el `Dockerfile` y construye.
6. Una vez en línea, la URL será `https://<servicio>.onrender.com` con HTTPS automático.

Verifica:

```bash
curl https://<servicio>.onrender.com/health
curl -X POST https://<servicio>.onrender.com/answer \
     -H 'Content-Type: application/json' \
     -d '{"question": "## ¿Qué es BM25?"}'
```

Pega esta URL en la celda H del notebook `examen_supletorio_rag.ipynb`.

---

## Opción 2 — Fly.io (gratis con Docker)

1. Instala flyctl: <https://fly.io/docs/hands-on/install-flyctl/>
2. `fly launch` en el directorio del proyecto.
3. Edita el `fly.toml` generado:
   ```toml
   [env]
     LLM_API_KEY = "tu-clave-groq"
     AUTO_BUILD_INDEX = "true"

   [[services]]
     internal_port = 7860
     protocol = "tcp"
     [[services.ports]]
       port = 443
       handlers = ["tls", "http"]
   ```
4. `fly deploy`.
5. URL pública: `https://<app>.fly.dev`.

---

## Opción 3 — Hugging Face Spaces con SDK Streamlit (gratis, solo UI)

Si aún quieres usar HF Spaces para tener la UI de inspección:

1. Crea un Space con SDK **Streamlit** y hardware **CPU basic** (gratis).
2. Sube los archivos del proyecto, **incluyendo `app.py`** y excluyendo `data/chroma/` y los PDFs pesados.
3. En **Settings → Variables and secrets** define `LLM_API_KEY` como *secret*.
4. La UI de Streamlit quedará accesible en `https://<usuario>-<space>.hf.space` pero `POST /answer` NO estará disponible públicamente. Usa este Space solo para inspección visual; despliega la API en Render para el examen.

---

## Opción 4 — Local + ngrok (sin despliegue en la nube)

Si no quieres desplegar en ninguna plataforma:

```bash
# Terminal 1: arranca el servicio FastAPI
PYTHONPATH=./src python3 -m uvicorn ir_rag.api:app --host 0.0.0.0 --port 7860

# Terminal 2: expone el puerto a Internet
ngrok http 7860
```

ngrok te dará una URL `https://<id>.ngrok-free.app` que puedes usar con Postman. **Limitación**: la URL cambia cada vez que reinicies ngrok (a menos que uses el plan de pago).

Alternativa gratuita con URL fija: [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

```bash
cloudflared tunnel --url http://localhost:7860
```

---

## Verificar los endpoints (cualquier opción)

```bash
HOST=https://<tu-host>

# Health check (debe devolver 200)
curl $HOST/health

# Pregunta válida (necesita LLM_API_KEY)
curl -X POST $HOST/answer \
     -H 'Content-Type: application/json' \
     -d '{"question": "## ¿Qué es BM25?"}'

# Documentación interactiva (abre en el navegador)
open $HOST/docs
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
