# Entrega del Examen de Recuperación — Servicio RAG

> **ICCD753 Recuperación de Información 2026-A · Prof. Iván Carrera · EPN-FIS**
>
> Estudiante: *(colocar nombre)*
>
> Fecha: 2026-08-05

---

## a. URL base del servicio

```
https://prone-snowiness-reviving.ngrok-free.dev
```

Esta URL se sirve mediante **ngrok** (HTTPS automático) apuntando al servicio FastAPI corriendo localmente. Mientras la máquina que ejecuta `start-local.sh` esté encendida, la URL responde 24/7.

### Verificación rápida

```bash
curl https://prone-snowiness-reviving.ngrok-free.dev/
curl https://prone-snowiness-reviving.ngrok-free.dev/health
```

---

## b. Endpoint principal

| | |
|---|---|
| **Endpoint** | `/answer` |
| **Propósito** | Recibe una pregunta en Markdown y devuelve la respuesta fundamentada en el corpus con referencias bibliográficas y evidencia. |

### Endpoints auxiliares

| Endpoint | Método | Propósito |
|---|---|---|
| `/` | `GET` | Metadatos del servicio (nombre, descripción, lista de endpoints). |
| `/health` | `GET` | Health check: estado, colección, número de chunks, modelos, LLM. |
| `/stats` | `GET` | Estadísticas del índice y de la configuración. |
| `/docs` | `GET` | Swagger UI interactivo. |
| `/openapi.json` | `GET` | Esquema OpenAPI 3.0. |

---

## c. Método HTTP utilizado

| Endpoint | Método |
|---|---|
| `/` | `GET` |
| `/health` | `GET` |
| `/stats` | `GET` |
| `/docs` | `GET` |
| `/openapi.json` | `GET` |
| **`/answer`** | **`POST`** |

---

## d. Formato de la solicitud

### Headers (obligatorios para `/answer`)

```
Content-Type: application/json
```

### Cuerpo de la solicitud (Body)

```json
{
  "question": "## ¿Qué es BM25?\n\nExplica el algoritmo y sus componentes principales."
}
```

#### Esquema Pydantic (`AnswerRequestIn`)

| Campo | Tipo | Obligatorio | Default | Descripción |
|---|---|---|---|---|
| `question` | `string` | Sí | `""` | Pregunta en formato Markdown. |

#### Reglas de validación

- `question` **vacío** (`""`) → HTTP **400** ("The 'question' field is required and cannot be empty.")
- `question` **sin pregunta extraíble** (solo Markdown sin texto) → HTTP **422** ("The request is valid but no question could be extracted from the supplied Markdown content.")
- Pregunta Markdown con texto → HTTP **200** con respuesta.

### Ejemplo de Body

```json
{
  "question": "## ¿Cómo funciona TF-IDF?\n\nExplica el algoritmo y sus componentes principales."
}
```

---

## e. Formato de la respuesta

### Estructura (`AnswerResponseOut`)

```json
{
  "question": "Pregunta limpia extraída del Markdown (sin headings, bold, code fences, etc.).",
  "answer": "Respuesta generada por el LLM, fundamentada en la evidencia recuperada.",
  "references": [
    "- Autor1, Autor2 (Año). *Título del documento*. Capítulo X.Y — pp. N–M.",
    "..."
  ],
  "evidence": [
    {
      "evidence_id": "E1",
      "rank": 1,
      "chunk_id": "doc-id:pNNN:cNNNN-slug-del-chunk",
      "doc_id": "doc-id-2025",
      "title": "Título del documento",
      "authors": ["Autor 1", "Autor 2"],
      "year": 2025,
      "kind": "book | article",
      "chapter": "Capítulo X",
      "section": "Sección X.Y",
      "page_start": 100,
      "page_end": 105,
      "text": "Texto completo del chunk recuperado.",
      "semantic_score": 0.5123,
      "rerank_score": 0.9871
    }
  ],
  "retrieval_ms": 1234.5,
  "generation_ms": 678.9,
  "insufficient": false,
  "warning": null
}
```

### Significado de cada campo

| Campo | Descripción |
|---|---|
| `question` | Pregunta limpia extraída del Markdown original (headings, bold, code, listas eliminados). |
| `answer` | Respuesta generada por el LLM en base al contexto de los chunks recuperados. |
| `references` | Lista formateada de referencias bibliográficas (estilo Markdown). |
| `evidence` | Lista de los *top-K* chunks usados como contexto (K=5 por defecto). |
| `evidence_id` | Identificador local (`E1`–`E5`) usado para citas en `answer`. |
| `rank` | Posición del chunk en el ranking (1 = más relevante). |
| `chunk_id` | ID único del chunk en la base vectorial (`{doc_id}:p{page}:c{idx}-{slug}`). |
| `doc_id` | Identificador del documento en el registro bibliográfico. |
| `title` / `authors` / `year` | Metadatos del documento. |
| `kind` | `book` o `article`. |
| `chapter` / `section` | Estructura interna detectada por el parser. |
| `page_start` / `page_end` | Rango de páginas del PDF original. |
| `text` | Texto completo del chunk. |
| `semantic_score` | Similitud coseno (densos, *all-MiniLM-L6-v2*). Rango típico `[0, 1]`. |
| `rerank_score` | Sigmoide del *cross-encoder* (*ms-marco-MiniLM-L-6-v2*). Rango típico `[0, 1]`. |
| `retrieval_ms` | Tiempo de retrieval en milisegundos. |
| `generation_ms` | Tiempo de generación del LLM en milisegundos. |
| `insufficient` | `true` si la evidencia recuperada no cubre la pregunta. |
| `warning` | Mensaje de advertencia opcional (ej. "modo degradado"). |

---

## f. Documentación de los endpoints

### `GET /`

Devuelve metadatos del servicio.

**Respuesta 200:**

```json
{
  "name": "ir-rag-service",
  "description": "Web service that answers Information Retrieval questions...",
  "endpoints": [
    {"path": "/", "method": "GET", "purpose": "Service metadata"},
    {"path": "/health", "method": "GET", "purpose": "Health probe"},
    {"path": "/answer", "method": "POST", "purpose": "Main RAG endpoint"},
    {"path": "/docs", "method": "GET", "purpose": "OpenAPI / Swagger UI"},
    {"path": "/openapi.json", "method": "GET", "purpose": "OpenAPI schema"}
  ],
  "status_codes": {
    "200": "Solicitud procesada correctamente.",
    "400": "Solicitud inválida o ausencia del campo 'question'.",
    "404": "Endpoint o recurso no encontrado.",
    "422": "La solicitud es válida pero no fue posible identificar preguntas en el contenido recibido.",
    "500": "Error interno del servidor.",
    "503": "El modelo, la base vectorial o algún componente requerido no se encuentra disponible."
  }
}
```

### `GET /health`

Verifica que el servicio esté operativo.

**Respuesta 200:**

```json
{
  "status": "ok",
  "collection": "ir_corpus",
  "chunks": 3584,
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
  "llm_configured": true
}
```

**Respuesta 503:**

```json
{"detail": "Vector store is empty. Trigger a build with `python scripts/build_index.py --reset`."}
```

### `POST /answer`

Procesa una pregunta y devuelve la respuesta.

**Body (JSON):**

```json
{
  "question": "## ¿Qué es BM25?"
}
```

**Respuesta 200:**

(Véase la sección *e. Formato de la respuesta*.)

**Respuesta 400:**

```json
{"detail": "The 'question' field is required and cannot be empty."}
```

**Respuesta 422:**

```json
{"detail": "The request is valid but no question could be extracted from the supplied Markdown content."}
```

**Respuesta 503:**

```json
{
  "detail": "No LLM key is configured. Set LLM_API_KEY (or GROQ_API_KEY) as an environment variable or Space secret.",
  "component": "llm",
  "hint": "Configure the LLM_API_KEY environment variable."
}
```

### `GET /stats`

Estadísticas del índice y de la configuración.

**Respuesta 200:**

```json
{
  "collection": "ir_corpus",
  "chunks": 3584,
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
  "retrieval_candidates": 20,
  "top_k": 5
}
```

### `GET /docs`

Swagger UI interactivo. Disponible en cualquier navegador.

### `GET /openapi.json`

Esquema OpenAPI 3.0 (formato JSON). Útil para generar clientes automáticamente.

---

## g. Ejemplo de consumo mediante Postman

### Paso a paso

1. **Abrir Postman** y crear una nueva request (botón `+`).
2. **Método**: seleccionar **`POST`** en el dropdown.
3. **URL**: pegar `https://prone-snowiness-reviving.ngrok-free.dev/answer`
4. **Headers** (pestaña *Headers*):
   - Key: `Content-Type`
   - Value: `application/json`
5. **Body** (pestaña *Body*):
   - Seleccionar **raw** y luego **JSON** en el dropdown.
   - Pegar:
     ```json
     {
       "question": "## ¿Qué es BM25?\n\nExplica el algoritmo y sus componentes principales."
     }
     ```
6. **Send**.

### Captura de pantalla esperada

```
POST https://prone-snowiness-reviving.ngrok-free.dev/answer

Headers:
  Content-Type: application/json

Body:
{
  "question": "## ¿Qué es BM25?\n\nExplica el algoritmo."
}

Response:
  Status: 200 OK
  Time: ~2.5 s
  Size: ~5 KB

  {
    "question": "¿Qué es BM25? Explica el algoritmo.",
    "answer": "BM25 (Best Match 25) es una función de ranking...",
    "references": [...],
    "evidence": [...],
    "retrieval_ms": 1234,
    "generation_ms": 1100,
    "insufficient": false
  }
```

### Ejemplos adicionales para probar en Postman

```json
{"question": "## ¿Qué es TF-IDF?"}
{"question": "## ¿Cómo funciona el modelo de espacio vectorial?\n\nExplica sus componentes."}
{"question": "## ¿Qué es un dense passage retriever (DPR)?"}
{"question": "## ¿Cómo se hace re-ranking con BERT?\n\nCita el paper original."}
```

### Probar códigos de error

| Caso | Body | Status esperado |
|---|---|---|
| Pregunta vacía | `{}` | **400** |
| Markdown sin pregunta | `{"question":"```code```"}` | **422** |
| Endpoint inexistente | (GET `/no-existe`) | **404** |

---

## h. Ejemplo de consumo mediante curl

### 1. Health check

```bash
curl https://prone-snowiness-reviving.ngrok-free.dev/health
```

**Salida:**

```json
{"status":"ok","collection":"ir_corpus","chunks":3584,"embedding_model":"sentence-transformers/all-MiniLM-L6-v2","reranker_model":"cross-encoder/ms-marco-MiniLM-L-6-v2","llm_configured":true}
```

### 2. Hacer una pregunta

```bash
curl -X POST https://prone-snowiness-reviving.ngrok-free.dev/answer \
     -H 'Content-Type: application/json' \
     -d '{"question": "## ¿Qué es BM25?"}'
```

**Salida (resumida):**

```json
{
  "question": "¿Qué es BM25?",
  "answer": "BM25 (Best Match 25) es una función de ranking probabilística...",
  "references": [
    "- Stephen Robertson, Hugo Zaragoza (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*. ..."
  ],
  "evidence": [
    {
      "evidence_id": "E1",
      "rank": 1,
      "chunk_id": "robertson-zaragoza-2009:p31:c0053-3-6-multiple-streams-and-bm25f",
      "title": "The Probabilistic Relevance Framework: BM25 and Beyond",
      "page_start": 31, "page_end": 31,
      "semantic_score": 0.332,
      "rerank_score": 0.071,
      "text": "..."
    }
  ],
  "retrieval_ms": 10483,
  "generation_ms": 1100,
  "insufficient": true
}
```

### 3. Hacer una pregunta con respuesta completa

```bash
curl -X POST https://prone-snowiness-reviving.ngrok-free.dev/answer \
     -H 'Content-Type: application/json' \
     -d '{"question": "## Explica TF-IDF"}'
```

### 4. Pregunta vacía → 400

```bash
curl -X POST https://prone-snowiness-reviving.ngrok-free.dev/answer \
     -H 'Content-Type: application/json' \
     -d '{}' -w "\nHTTP %{http_code}\n"
```

**Salida:**

```json
{"detail": "The 'question' field is required and cannot be empty."}
HTTP 400
```

### 5. Markdown sin pregunta → 422

```bash
curl -X POST https://prone-snowiness-reviving.ngrok-free.dev/answer \
     -H 'Content-Type: application/json' \
     -d '{"question":"```\nprint(1)\n```"}' -w "\nHTTP %{http_code}\n"
```

**Salida:**

```json
{"detail": "The request is valid but no question could be extracted from the supplied Markdown content."}
HTTP 422
```

### 6. Ruta inexistente → 404

```bash
curl https://prone-snowiness-reviving.ngrok-free.dev/no-existe -w "\nHTTP %{http_code}\n"
```

**Salida:**

```json
{"detail": "Endpoint 'GET /no-existe' was not found."}
HTTP 404
```

---

## i. Códigos de estado utilizados

| Código | Nombre | Cuándo se devuelve |
|---|---|---|
| **200** | OK | Solicitud procesada correctamente. Devuelve la respuesta, referencias y evidencia. |
| **400** | Bad Request | El campo `question` está ausente, es `null`, o es una cadena vacía. |
| **404** | Not Found | La ruta solicitada no existe (endpoint no registrado). |
| **422** | Unprocessable Entity | El campo `question` llegó pero no se pudo extraer una pregunta del Markdown (ej. solo code fences, headings vacíos). |
| **500** | Internal Server Error | Error inesperado en el servidor (no controlado). Se devuelve un JSON con `"detail"`. |
| **503** | Service Unavailable | Alguno de los componentes requeridos no está disponible: vector store vacío o `LLM_API_KEY` no configurada. Se devuelve un JSON con `"detail"`, `"component"` y opcionalmente `"hint"`. |

### Mapeo de excepciones

| Excepción interna | Código HTTP | Origen |
|---|---|---|
| `HTTPException(400, ...)` | 400 | Pregunta vacía o mal formada. |
| `HTTPException(422, ...)` | 422 | Sin pregunta extraíble del Markdown. |
| `HTTPException(503, ...)` (interno) | 503 | Vector store no disponible o vacío. |
| `LLMConfigurationError` | 503 | `LLM_API_KEY` no configurada. |
| `LLMRequestError` | 503 | Error de red con el LLM. |
| `HTTPException(404)` (default FastAPI) | 404 | Ruta no encontrada (manejado por nuestro handler). |
| Excepción no controlada | 500 | Error genérico (logger + 500). |

---

## 📋 Resumen rápido para el examen

```bash
HOST="https://prone-snowiness-reviving.ngrok-free.dev"

# Health check
curl -s $HOST/health

# Pregunta
curl -s -X POST $HOST/answer \
  -H 'Content-Type: application/json' \
  -d '{"question":"## ¿Qué es BM25?"}'

# Documentación interactiva
# Abrir en navegador: $HOST/docs
```

| Entregable | Valor |
|---|---|
| **a. URL base** | `https://prone-snowiness-reviving.ngrok-free.dev` |
| **b. Endpoint principal** | `/answer` |
| **c. Método HTTP** | `POST` |
| **d. Formato solicitud** | JSON con campo `question` (Markdown) |
| **e. Formato respuesta** | JSON con `question`, `answer`, `references`, `evidence[]`, scores, tiempos |
| **f. Documentación** | `GET /docs` (Swagger UI) y `GET /openapi.json` |
| **g. Postman** | Body raw JSON, header `Content-Type: application/json` |
| **h. curl** | `curl -X POST HOST/answer -H 'Content-Type: application/json' -d '{"question":"..."}'` |
| **i. Códigos HTTP** | 200, 400, 404, 422, 500, 503 |
