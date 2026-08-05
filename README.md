# IR RAG Service — Examen de Recuperación (Supletorio)

Servicio web (HTTPS) que responde preguntas sobre **Recuperación de Información** usando un pipeline RAG (*Retrieval-Augmented Generation*) construido a partir de los PDFs de la bibliografía del curso.

## Tabla de contenidos

1. [Visión general](#visión-general)
2. [Arquitectura](#arquitectura)
3. [Corpus](#corpus)
4. [Procesamiento del corpus](#procesamiento-del-corpus)
5. [Recuperación y re-ranking](#recuperación-y-re-ranking)
6. [Servicio web](#servicio-web)
7. [Códigos de estado HTTP](#códigos-de-estado-http)
8. [Ejemplos de uso](#ejemplos-de-uso)
9. [Despliegue](#despliegue)
10. [Configuración](#configuración)
11. [Pruebas](#pruebas)
12. [Limitaciones](#limitaciones)

---

## Visión general

- **No** requiere interfaz gráfica ni chatbot.
- Recibe preguntas en **Markdown** por HTTP.
- Devuelve respuestas **fundamentadas exclusivamente** en el corpus, con citas y referencias bibliográficas.
- Diferencia el *score* inicial de recuperación densa y el *score* de re-ranking.
- Indica explícitamente cuando la evidencia del corpus es insuficiente.
- Se expone en Internet con **HTTPS** para que pueda ser evaluado con Postman.

### Dos puntos de entrada

El proyecto incluye dos formas de arrancarlo, según dónde lo despliegues:

| Entrada | Qué hace | Dónde usarlo |
|---------|----------|--------------|
| `uvicorn ir_rag.api:app` | Servicio FastAPI puro: `POST /answer`, `GET /health`, `GET /docs`. | Render.com / Fly.io / Railway / HF Docker (API real para el examen). |
| `streamlit run app.py` | UI Streamlit con pestañas de consulta, estado y documentación. | HF Spaces SDK Streamlit (solo para inspección visual). |

⚠️ **Importante:** el SDK Streamlit de Hugging Face Spaces **no** expone endpoints HTTP personalizados. Si despliegas el proyecto en HF con SDK Streamlit, `POST /answer` **no será accesible públicamente** y el profesor no podrá evaluarlo con Postman. Para el examen, despliega la API FastAPI en Render.com (gratis).

---

## Arquitectura

```
   cliente (Postman, curl)
            │  HTTPS · POST /answer
            ▼
 ┌──────────────────────────────────────────────────────────┐
 │                FastAPI (uvicorn workers)                 │
 │                                                          │
 │  1. extract_question()   ← limpia Markdown               │
 │  2. EmbeddingService     ← vector denso de la pregunta   │
 │  3. VectorStore (Chroma) ← top-K candidatos              │
 │  4. CrossEncoder         ← re-ranking                    │
 │  5. OpenAI-compatible LLM ← generación con evidencia     │
 └──────────────────────────────────────────────────────────┘
            │  JSON
            ▼
   { question, answer, references, evidence[...], scores }
```

Cada `evidence` incluye `semantic_score` (recuperación inicial) **y** `rerank_score` (cross-encoder), de modo que la respuesta permite diferenciar ambas etapas como pide el examen (sección 4).

---

## Corpus

| Tipo | Documento | doc_id | Origen |
|------|-----------|--------|--------|
| Libro obligatorio | Baeza-Yates & Ribeiro-Neto — *Modern Information Retrieval* | `baeza-yates-1999` | **No descargable** (copyright). El usuario debe colocar el PDF. |
| Libro obligatorio | Manning, Raghavan & Schütze — *Introduction to Information Retrieval* | `manning-2009` | <https://nlp.stanford.edu/IR-book/pdf/irbookonlinereading.pdf> |
| Libro adicional | Jurafsky & Martin — *Speech and Language Processing* (cap. sobre IR y búsqueda) | `jurafsky-martin-2026` | <https://web.stanford.edu/~jurafsky/slp3/ed3book.pdf> |
| Artículo | Robertson & Zaragoza — *The Probabilistic Relevance Framework: BM25 and Beyond* | `robertson-zaragoza-2009` | <https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf> |
| Artículo | Karpukhin et al. — *Dense Passage Retrieval for Open-Domain Question Answering* | `karpukhin-etal-2020` | <https://arxiv.org/pdf/2004.04906> |
| Artículo | Nogueira & Cho — *Passage Re-ranking with BERT* | `nogueira-cho-2019` | <https://arxiv.org/pdf/1901.04085> |

> **Importante**: el examen prohíbe incorporar contenido generado por modelos de lenguaje al corpus. Los campos bibliográficos (`authors`, `year`) solo se usan como **etiquetas**; el texto indexado siempre proviene del PDF original.

### Colocar Baeza-Yates

1. Descarga tu copia personal.
2. Cópiala a `corpus/baeza-yates-modern-ir.pdf`.
3. Si tu edición difiere en título/autores/año, ajusta la entrada en `src/ir_rag/corpus.py::CORPUS_REGISTRY`.

---

## Procesamiento del corpus

`src/ir_rag/corpus.py` implementa todas las operaciones exigidas por el examen (sección 3):

| Operación | Implementación |
|-----------|----------------|
| a. Lectura y extracción desde PDFs | PyMuPDF (`fitz`) por página |
| b. Limpieza de encabezados, pies y contenido repetitivo | Detección de líneas repetidas (umbral 5–10 % de páginas) + filtro de números de página |
| c. Identificador de documento de origen | `doc_id` del registro bibliográfico (`CORPUS_REGISTRY`) |
| d. Conservar números de página | Cada chunk guarda `page_start` y `page_end` |
| e. División en chunks | Ventanas de caracteres con solapamiento, ajustadas a límites de palabra |
| f. IDs únicos de chunks | `{doc_id}:p{page}:c{idx:04d}-{slug}` |
| g. Embeddings | `sentence-transformers/all-MiniLM-L6-v2`, normalizados |
| h. Indexación en base vectorial | Chroma persistente con cosine similarity |

La detección de capítulos y secciones combina patrones numéricos (`^\d+\s+`, `^\d+\.\d+\s+`) con análisis de tamaño de fuente y negrita (PyMuPDF `flags & 16`). Las páginas de contenido repetitivo (TOC) se filtran exigiendo un tamaño mínimo de fuente para los encabezados.

---

## Recuperación y re-ranking

1. **Representación de la pregunta**: `EmbeddingService.encode_query()` produce un vector denso normalizado.
2. **Búsqueda inicial**: `VectorStore.query()` devuelve los `RETRIEVAL_CANDIDATES` (20 por defecto) vecinos más cercanos con cosine.
3. **Re-ranking**: `CrossEncoder (ms-marco-MiniLM-L-6-v2)` reordena los candidatos y devuelve una puntuación tras `sigmoid`.
4. **Selección top-K**: se toman los `TOP_K` mejores chunks respetando un tope por documento (`MAX_CHUNKS_PER_DOCUMENT`) para fomentar diversidad.
5. **Generación**: el LLM recibe **únicamente** los chunks seleccionados (más metadatos mínimos) y debe responder citando identificadores como `[E1]`.

Si la mejor puntuación semántica o de re-ranking cae por debajo de los umbrales configurados (`MIN_SEMANTIC_SCORE`, `MIN_RERANK_SCORE`), el sistema devuelve la respuesta *“El corpus no contiene evidencia suficiente…”* sin invocar al LLM.

---

## Servicio web

| Atributo | Valor |
|----------|-------|
| URL base | `https://<host>/` (definida en el despliegue) |
| Endpoint principal | `POST /answer` |
| Método HTTP | `POST` (cuerpo JSON) |
| Formato de solicitud | `application/json` con campo `question` (Markdown) |
| Formato de respuesta | `application/json` con `question`, `answer`, `references[]`, `evidence[]`, `retrieval_ms`, `generation_ms`, `insufficient` |
| HTTPS | sí, gestionado por la plataforma (HF Spaces, Render, etc.) |

Otros endpoints:

- `GET /` — metadatos del servicio (incluye descripción y lista de códigos).
- `GET /health` — comprobación de salud (vector store, modelos, LLM configurado).
- `GET /stats` — estadísticas básicas del índice.
- `GET /docs` — Swagger UI generado automáticamente.
- `GET /openapi.json` — esquema OpenAPI.

---

## Códigos de estado HTTP

| Código | Significado en este servicio |
|--------|------------------------------|
| **200** | Solicitud procesada correctamente. |
| **400** | Solicitud inválida — falta el campo `question` o viene vacío. |
| **404** | Endpoint o recurso no encontrado. |
| **422** | La solicitud es válida pero no fue posible identificar una pregunta en el contenido recibido (p. ej. solo hay un bloque de código Markdown). |
| **500** | Error interno del servidor. |
| **503** | El modelo, la base vectorial o algún componente requerido no se encuentra disponible (clave LLM ausente, Chroma no accesible, etc.). |

---

## Ejemplos de uso

### curl

```bash
# Pregunta en Markdown
curl -X POST https://TU-HOST/answer \
     -H 'Content-Type: application/json' \
     -d '{
       "question": "## ¿Qué es BM25?\n\nExplica el algoritmo y sus variantes."
     }'
```

### Postman

1. Crea una nueva request `POST` apuntando a `{{base_url}}/answer`.
2. En *Body → raw → JSON* pega `{"question": "## ..."}`.
3. Pulsa *Send*.

### Respuesta (ejemplo abreviado)

```json
{
  "question": "¿Qué es BM25? Explica el algoritmo y sus variantes.",
  "answer": "BM25 (Best Match 25) es una función de ranking probabilística...",
  "references": [
    "- Robertson, Zaragoza (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*. 3.9 Open Source Implementations of BM25 and BM25F — pp. 39–39."
  ],
  "evidence": [
    {
      "evidence_id": "E1",
      "rank": 1,
      "chunk_id": "robertson-zaragoza-2009:p39:c0072-3-9-open-source-implementation",
      "doc_id": "robertson-zaragoza-2009",
      "title": "The Probabilistic Relevance Framework: BM25 and Beyond",
      "authors": ["Stephen Robertson", "Hugo Zaragoza"],
      "year": 2009,
      "kind": "article",
      "chapter": "3 Derived Models",
      "section": "3.9 Open Source Implementations of BM25 and BM25F",
      "page_start": 39,
      "page_end": 39,
      "text": "...",
      "semantic_score": 0.526,
      "rerank_score": 0.984
    }
  ],
  "retrieval_ms": 412.7,
  "generation_ms": 1180.4,
  "insufficient": false,
  "warning": null
}
```

Los campos `semantic_score` (búsqueda densa inicial) y `rerank_score` (cross-encoder) son los dos puntajes independientes que exige el examen en la sección 4.

---

## Despliegue

### Hugging Face Spaces (opcional, solo para inspección visual)

Si quieres inspeccionar el pipeline visualmente en HF Spaces:

1. Crea un Space con SDK **Streamlit** y hardware **CPU basic** (gratis).
2. Sube todos los archivos (incluido `app.py`), excluyendo `data/chroma/` y los PDFs.
3. Define `LLM_API_KEY` como *secret* en **Settings → Variables and secrets**.
4. La UI de Streamlit quedará visible en `https://<usuario>-<space>.hf.space`.

⚠️ Esta UI **no expone `POST /answer`** públicamente. Para la evaluación con Postman, despliega la API FastAPI en Render.com (ver abajo).

### Render.com (RECOMENDADO para el examen, gratis con Docker)

1. Sube el proyecto a GitHub.
2. En <https://render.com> → **New + → Web Service** → conecta el repo.
3. **Environment**: Docker. **Plan**: Free. **Health Check Path**: `/health`.
4. Define `LLM_API_KEY` en **Environment → Environment Variables**.
5. Render detecta el `Dockerfile` y construye. La URL pública `https://<servicio>.onrender.com` expone `POST /answer` con HTTPS automático.

Más detalles en [`docs/deployment_cheatsheet.md`](docs/deployment_cheatsheet.md).

### Render / Railway / Fly.io

1. Conecta el repositorio.
2. Comando de inicio: `uvicorn ir_rag.api:app --host 0.0.0.0 --port $PORT`.
3. Define `LLM_API_KEY` como variable de entorno.
4. Activa HTTPS automático de la plataforma.

### Local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # rellena LLM_API_KEY

python scripts/download_corpus.py   # descarga lo público
# Coloca tu PDF de Baeza-Yates en corpus/baeza-yates-modern-ir.pdf

PYTHONPATH=./src python scripts/build_index.py --reset

# Opción A — FastAPI puro (Render / Docker / local)
PYTHONPATH=./src uvicorn ir_rag.api:app --host 0.0.0.0 --port 7860

# Opción B — UI Streamlit (HF Spaces SDK Streamlit / local)
PYTHONPATH=./src streamlit run app.py --server.port 7860
```

### Túnel público temporal (sin desplegar)

```bash
# ngrok
ngrok http 7860

# Cloudflare Tunnel
cloudflared tunnel --url http://localhost:7860
```

---

## Configuración

Todas las variables se leen del entorno o de `.env`:

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `LLM_API_KEY` | — | Clave del LLM (Groq, OpenAI u otro). |
| `LLM_API_BASE` | `https://api.groq.com/openai/v1` | Endpoint compatible con OpenAI. |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Modelo del LLM. |
| `LLM_TEMPERATURE` | `0.1` | Temperatura. |
| `LLM_MAX_TOKENS` | `900` | Tokens máximos de la respuesta. |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Modelo de embeddings. |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder. |
| `ENABLE_RERANKER` | `true` | Desactiva el re-ranking si lo necesitas. |
| `RETRIEVAL_CANDIDATES` | `20` | Candidatos densos por consulta. |
| `TOP_K` | `5` | Evidencias finales. |
| `MIN_SEMANTIC_SCORE` | `0.20` | Umbral de cosine. |
| `MIN_RERANK_SCORE` | `0.05` | Umbral del cross-encoder (post-sigmoid). |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1200` / `200` | Tamaño y solapamiento de chunks. |
| `MIN_CHUNK_CHARS` | `120` | Descarta chunks más cortos. |
| `MAX_CONTEXT_CHARS` | `14000` | Límite del contexto enviado al LLM. |
| `MAX_CHUNKS_PER_DOCUMENT` | `2` | Diversidad documental en el top-K. |
| `AUTO_BUILD_INDEX` | `false` | Construye el índice al iniciar si está vacío. |
| `MAX_DOCUMENTS` | (vacío) | Limita cuántos documentos indexar (útil para demos). |

---

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q
```

Los tests cubren:

- Limpieza y *chunking* del corpus.
- Detección y eliminación de encabezados repetidos.
- *Stripping* de Markdown en `extract_question`.
- Manejo de evidencia insuficiente.
- Códigos HTTP: 200, 400, 404, 422, 503 (LLM ausente).
- Formato de referencias bibliográficas.

---

## Limitaciones

- El servicio **no** indexa contenido generado por LLMs. Si el corpus del usuario contiene tal contenido, la calidad de las respuestas será arbitraria.
- El PDF de Baeza-Yates es propietario y debe ser provisto por el estudiante.
- El primer arranque descarga modelos (~250 MB de sentence-transformers + 90 MB de cross-encoder) y puede tardar varios minutos en plataformas con poca RAM.
