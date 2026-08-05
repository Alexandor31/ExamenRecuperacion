"""Tests for the FastAPI surface (status codes, error mapping)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Boot the API in test mode with an isolated Chroma directory."""
    project = Path(__file__).resolve().parents[1]
    data_dir = tmp_path_factory.mktemp("data")
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["CHROMA_DIR"] = str(data_dir / "chroma")
    os.environ["CHROMA_COLLECTION"] = "ir_corpus_test"
    os.environ["AUTO_BUILD_INDEX"] = "false"
    # Avoid hitting real LLM endpoint during tests.
    os.environ.pop("LLM_API_KEY", None)
    os.environ.pop("GROQ_API_KEY", None)

    # Import after env vars are set.
    from importlib import reload
    from ir_rag import config as cfg
    reload(cfg)
    from ir_rag import api as api_module
    reload(api_module)
    app = api_module.create_app(cfg.Settings.from_env())
    return TestClient(app)


def test_root_metadata(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "ir-rag-service"
    assert any(e["path"] == "/answer" for e in body["endpoints"])


def test_answer_missing_field_returns_400(client):
    response = client.post("/answer", json={})
    assert response.status_code == 400
    detail = response.json().get("detail")
    assert detail is not None
    assert "question" in detail.lower()


def test_answer_empty_string_returns_400(client):
    response = client.post("/answer", json={"question": "   "})
    assert response.status_code == 400


def test_answer_only_markdown_noise_returns_422(client):
    response = client.post(
        "/answer",
        json={"question": "```\nprint('hello')\n```"},
    )
    assert response.status_code == 422


def test_unknown_endpoint_returns_404(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404


def test_health_returns_503_when_empty(client):
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert "empty" in body["detail"].lower() or "unavailable" in body["detail"].lower()
