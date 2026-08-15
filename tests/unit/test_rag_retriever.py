"""Unit tests for the RAG indexer/retriever with a mocked embed client."""

from pixelpilot.config import Settings
from pixelpilot.rag.indexer import KnowledgeBaseIndexer
from pixelpilot.rag.retriever import Retriever
from pixelpilot.rag.store import SimpleMemoryStore


class FakeEmbedClient:
    """Stub OllamaClient that returns deterministic, keyword-aware embeddings."""

    def embed(self, model, texts):
        return [self._vector(t) for t in texts]

    def embed_single(self, model, text):
        return self._vector(text)

    @staticmethod
    def _vector(text):
        # Tiny bag-of-words style vector; same words => similar vectors.
        words = ["blur", "layer", "color", "selection", "scale", "export", "desaturate"]
        vec = [0.0] * len(words)
        lowered = text.lower()
        for i, word in enumerate(words):
            if word in lowered:
                vec[i] = 1.0
        return vec


def _settings() -> Settings:
    settings = Settings()
    settings.rag.top_k_procedures = 3
    settings.rag.top_k_examples = 1
    return settings


def _build_indexed_store():
    store = SimpleMemoryStore()
    indexer = KnowledgeBaseIndexer(FakeEmbedClient(), store, _settings())
    indexer.index_procedures()
    indexer.index_examples()
    return store


def test_index_and_retrieve_blur():
    store = _build_indexed_store()
    retriever = Retriever(FakeEmbedClient(), store, _settings())
    results = retriever.retrieve_procedures("gimp", "I want to blur the background")
    assert results
    assert any("gaussian blur" in r.get("description", "").lower() for r in results)


def test_retrieve_layers():
    store = _build_indexed_store()
    retriever = Retriever(FakeEmbedClient(), store, _settings())
    results = retriever.retrieve_procedures("gimp", "make a new layer")
    assert results
    names = " ".join(r.get("name", "") for r in results)
    assert "layer" in names.lower()


def test_krita_retrieval():
    store = _build_indexed_store()
    retriever = Retriever(FakeEmbedClient(), store, _settings())
    results = retriever.retrieve_procedures("krita", "set the opacity of a layer")
    assert results


def test_retrieve_examples():
    store = _build_indexed_store()
    retriever = Retriever(FakeEmbedClient(), store, _settings())
    examples = retriever.retrieve_examples("gimp", "desaturate the background")
    assert examples
    assert examples[0]["code"]
