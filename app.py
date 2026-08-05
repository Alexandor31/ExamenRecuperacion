"""Punto de entrada para Hugging Face Spaces con SDK Streamlit (UI de inspección).

IMPORTANTE: el SDK Streamlit de HF Spaces NO expone endpoints HTTP personalizados.
Por eso este archivo solo levanta la UI de Streamlit.

Para tener `POST /answer` accesible públicamente al examen, despliega el mismo
proyecto con Docker en Render.com / Railway / HF Spaces. Ver docs/deployment_cheatsheet.md.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st  # noqa: E402

from ir_rag.config import Settings  # noqa: E402
from ir_rag.models import AnswerRequest  # noqa: E402
from ir_rag.rag import RAGPipeline, extract_question  # noqa: E402
from ir_rag.vector_store import VectorStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
LOGGER = logging.getLogger(__name__)

st.set_page_config(
    page_title="IR RAG · Examen de Recuperación",
    page_icon="🔎",
    layout="wide",
)

SETTINGS = Settings.from_env()


# ---------- Recursos cacheados ----------

@st.cache_resource(show_spinner="Cargando pipeline RAG…")
def get_pipeline() -> RAGPipeline:
    return RAGPipeline(SETTINGS)


@st.cache_resource(show_spinner=False)
def get_index_count() -> int:
    store = VectorStore(
        SETTINGS.chroma_dir, SETTINGS.collection_name, SETTINGS.embedding_model
    )
    return store.count


# ---------- Sidebar ----------

with st.sidebar:
    st.header("Estado del sistema")
    try:
        chunks = get_index_count()
    except Exception as exc:
        chunks = 0
        st.error(f"Vector store no disponible: {exc}")
    if chunks:
        st.success(f"Índice listo: {chunks:,} fragmentos")
    else:
        st.warning("El índice vectorial está vacío.")
        st.caption(
            "Ejecuta `python3 scripts/build_index.py --reset` antes de desplegar."
        )
    st.caption(f"Embeddings: `{SETTINGS.embedding_model.split('/')[-1]}`")
    reranker = (
        SETTINGS.reranker_model.split("/")[-1]
        if SETTINGS.enable_reranker
        else "desactivado"
    )
    st.caption(f"Re-ranking: `{reranker}`")
    st.caption(f"LLM: `{SETTINGS.llm_model}`")
    if SETTINGS.llm_api_key:
        st.success("LLM_API_KEY configurada")
    else:
        st.error("Falta LLM_API_KEY (defínela como secreto en el Space)")
    st.caption(f"Colección Chroma: `{SETTINGS.collection_name}`")

    with st.expander("⚠️ Sobre el SDK Streamlit", expanded=False):
        st.markdown(
            """
            El SDK Streamlit de HF Spaces **no expone endpoints HTTP
            personalizados**, por lo que `POST /answer` no es accesible
            públicamente desde aquí.

            **Para evaluar con Postman**, despliega el mismo proyecto
            con Docker en Render.com (gratis):

            1. Sube este repo a GitHub.
            2. Crea un Web Service en Render conectado al repo.
            3. Render detecta el `Dockerfile` y lo construye.
            4. Define `LLM_API_KEY` en **Environment → Environment Variables**.
            5. La URL pública `https://<servicio>.onrender.com/answer`
               es la que debes usar en Postman.

            Esta UI de Streamlit sirve solo para inspección visual.
            """
        )


# ---------- Cabecera principal ----------

st.title("🔎 IR RAG Service · Examen de Recuperación")
st.markdown(
    """
    Servicio **RAG** (Retrieval-Augmented Generation) que responde preguntas
    sobre *Information Retrieval* usando la bibliografía del curso.

    Pipeline: PDF → *chunks* → embeddings → **Chroma** → cross-encoder
    → LLM (Groq por defecto).

    ---
    """
)


# ---------- Tabs ----------

tab_query, tab_status, tab_docs = st.tabs(
    ["💬 Consulta", "📊 Estado del sistema", "📖 Endpoints REST"]
)


# ===== Tab 1: consulta =====

with tab_query:
    st.subheader("Probar el pipeline localmente")
    question_md = st.text_area(
        "Pregunta en Markdown",
        height=200,
        placeholder=(
            "## ¿Qué es BM25?\n\n"
            "Explica el algoritmo y sus **componentes** principales."
        ),
    )

    col_btn, col_clear = st.columns([1, 5])
    with col_btn:
        run = st.button("Enviar", type="primary", use_container_width=True)
    with col_clear:
        if st.button("Limpiar", use_container_width=False):
            st.rerun()

    if run:
        if not question_md.strip():
            st.error("La pregunta está vacía.")
        elif get_index_count() == 0:
            st.error("El índice vectorial está vacío. Reconstruye con `build_index.py`.")
        else:
            with st.spinner("Recuperando evidencia y generando respuesta…"):
                try:
                    response = get_pipeline().answer(
                        AnswerRequest(question=question_md)
                    )
                except Exception as exc:
                    LOGGER.exception("Pipeline failure")
                    st.error(f"Error en el pipeline: {exc}")
                    st.stop()

            st.success(f"Procesado en {response.retrieval_ms:.0f} ms (retrieval) + "
                       f"{response.generation_ms:.0f} ms (generación)")

            st.markdown("### Pregunta detectada")
            st.write(response.question)

            if response.insufficient:
                st.warning(response.answer)
            else:
                st.markdown("### Respuesta")
                st.write(response.answer)

            st.markdown("### Referencias bibliográficas")
            if response.references:
                for ref in response.references:
                    st.markdown(ref)
            else:
                st.caption("(sin referencias)")

            st.markdown("### Evidencia recuperada")
            st.caption(
                f"Cada chunk muestra `semantic_score` (recuperación inicial) "
                f"y `rerank_score` (cross-encoder)."
            )
            for ev in response.evidence:
                with st.expander(
                    f"[{ev['evidence_id']}] {ev['title']}  ·  "
                    f"p.{ev['page_start']}–{ev['page_end']}  ·  "
                    f"sem={ev['semantic_score']:.3f} · "
                    f"rerank={ev.get('rerank_score', 0) or 0:.3f}"
                ):
                    st.markdown(
                        f"**doc_id:** `{ev['doc_id']}`  \n"
                        f"**chunk_id:** `{ev['chunk_id']}`  \n"
                        f"**autores:** {', '.join(ev.get('authors', []))}  \n"
                        f"**año:** {ev.get('year') or '-'}  \n"
                        f"**capítulo:** {ev.get('chapter') or '-'}  \n"
                        f"**sección:** {ev.get('section') or '-'}"
                    )
                    st.text_area(
                        "Texto del chunk",
                        ev["text"],
                        height=180,
                        key=f"txt-{ev['evidence_id']}",
                    )


# ===== Tab 2: estado =====

with tab_status:
    st.subheader("Estado del sistema")
    st.json(
        {
            "collection": SETTINGS.collection_name,
            "chroma_dir": str(SETTINGS.chroma_dir),
            "embedding_model": SETTINGS.embedding_model,
            "reranker_model": SETTINGS.reranker_model if SETTINGS.enable_reranker else "disabled",
            "chunk_size": SETTINGS.chunk_size,
            "chunk_overlap": SETTINGS.chunk_overlap,
            "retrieval_candidates": SETTINGS.retrieval_candidates,
            "top_k": SETTINGS.top_k,
            "min_semantic_score": SETTINGS.min_semantic_score,
            "min_rerank_score": SETTINGS.min_rerank_score,
            "llm_model": SETTINGS.llm_model,
            "llm_api_base": SETTINGS.llm_api_base,
            "llm_configured": bool(SETTINGS.llm_api_key),
            "chunks_in_collection": get_index_count(),
        }
    )


# ===== Tab 3: documentación REST =====

with tab_docs:
    st.subheader("Endpoints REST del servicio FastAPI")
    st.info(
        "Esta UI es **Streamlit**, no expone los endpoints REST. "
        "Despliega el `Dockerfile` en Render.com para tener `POST /answer` "
        "accesible públicamente."
    )

    st.markdown("### POST /answer")
    st.markdown(
        "Recibe una pregunta en **Markdown** y devuelve la respuesta "
        "fundamentada en el corpus con referencias y *scores*."
    )
    st.code(
        """curl -X POST https://<HOST>/answer \\
     -H 'Content-Type: application/json' \\
     -d '{
       "question": "## ¿Qué es BM25?\\n\\nExplica el algoritmo."
     }'""",
        language="bash",
    )

    st.markdown("**Respuesta (ejemplo abreviado)**")
    st.code(
        """{
  "question": "¿Qué es BM25? Explica el algoritmo.",
  "answer": "BM25 (Best Match 25) es ...",
  "references": [
    "- Robertson, Zaragoza (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*. 3.9 Open Source Implementations — pp. 39–39."
  ],
  "evidence": [
    {
      "evidence_id": "E1",
      "rank": 1,
      "chunk_id": "robertson-zaragoza-2009:p39:c0072-3-9-open-source-implementation",
      "title": "The Probabilistic Relevance Framework: BM25 and Beyond",
      "page_start": 39, "page_end": 39,
      "semantic_score": 0.526,
      "rerank_score": 0.984,
      "text": "..."
    }
  ],
  "retrieval_ms": 412.7,
  "generation_ms": 1180.4,
  "insufficient": false
}""",
        language="json",
    )

    st.markdown("### Códigos de estado HTTP")
    st.table(
        {
            "Código": ["200", "400", "404", "422", "500", "503"],
            "Significado": [
                "Solicitud procesada correctamente.",
                "Solicitud inválida o ausencia del campo `question`.",
                "Endpoint o recurso no encontrado.",
                "La solicitud es válida pero no se pudo extraer una pregunta.",
                "Error interno del servidor.",
                "Componente requerido no disponible (LLM, vector store, etc.).",
            ],
        }
    )

    st.markdown("### Otros endpoints")
    st.markdown(
        """
        - `GET /` — metadatos del servicio.
        - `GET /health` — health-check (200 si todo OK).
        - `GET /stats` — estadísticas del índice.
        - `GET /docs` — Swagger UI.
        - `GET /openapi.json` — esquema OpenAPI.
        """
    )
