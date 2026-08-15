"""Integration tests requiring a live Ollama server.

Skipped automatically when Ollama is unreachable.
"""

import pytest

from pixelpilot.ollama.client import OllamaClient


@pytest.fixture(scope="module")
def ollama_client():
    client = OllamaClient("http://localhost:11434")
    if not client.ping():
        pytest.skip("Ollama server is not running on localhost:11434")
    return client


@pytest.mark.skip(reason="Requires a live Ollama server with models pulled.")
def test_list_models(ollama_client):
    models = ollama_client.list_models()
    assert isinstance(models, list)


@pytest.mark.skip(reason="Requires a live Ollama server with models pulled.")
def test_embed(ollama_client):
    embeddings = ollama_client.embed("nomic-embed-text", ["hello world"])
    assert len(embeddings) == 1
    assert len(embeddings[0]) > 0
