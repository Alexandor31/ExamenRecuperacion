# Corpus del servicio RAG

Esta carpeta contiene los PDFs que el servicio web usará como fuente de verdad para responder preguntas de Information Retrieval.

## Estructura esperada

```
corpus/
├── baeza-yates-modern-ir.pdf          ← obligatoria (no se descarga automáticamente)
├── manning-introduction-ir.pdf         ← obligatoria (descargada)
├── jurafsky-slp3.pdf                   ← libro adicional (descargado)
└── articles/
    ├── karpukhin-dpr-2020.pdf          ← artículo 1
    ├── nogueira-monobert-2019.pdf      ← artículo 2
    └── robertson-bm25-perspective.pdf  ← artículo 3
```

## Cómo añadir Baeza-Yates

El libro *Modern Information Retrieval* de Ricardo Baeza-Yates y Berthier Ribeiro-Neto está protegido por derechos de autor y **no** se descarga de Internet automáticamente. Para incluirlo:

1. Coloca tu copia (PDF) en este directorio con el nombre `baeza-yates-modern-ir.pdf`.
2. Si tu edición tiene metadatos distintos, ajusta la entrada correspondiente en `src/ir_rag/corpus.py::CORPUS_REGISTRY`.

Tras añadir el archivo ejecuta:

```bash
PYTHONPATH=./src python scripts/build_index.py --reset
```

## Obtener el resto del corpus

```bash
python3 scripts/download_corpus.py
```

El script descarga los PDFs de acceso abierto sin tocar Baeza-Yates. Si los archivos ya están presentes, no se vuelven a descargar.
