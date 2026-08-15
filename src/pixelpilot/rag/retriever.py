"""Semantic retrieval over the local vector store (implementation_plan.md §4.2)."""

from __future__ import annotations

from pixelpilot.config import Settings
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.rag.indexer import (
    COLLECTION_GIMP_EXAMPLES,
    COLLECTION_GIMP_PROCEDURES,
    COLLECTION_KRITA_API,
    COLLECTION_KRITA_EXAMPLES,
)
from pixelpilot.rag.store import VectorStore


class Retriever:
    """Retrieve relevant API procedures and few-shot examples for a query."""

    def __init__(
        self,
        client: OllamaClient,
        store: VectorStore,
        settings: Settings,
    ) -> None:
        self.client = client
        self.store = store
        self.settings = settings

    def _embed_query(self, query: str) -> list[float]:
        return self.client.embed_single(self.settings.ollama.embed_model, query)

    def retrieve_procedures(self, editor: str, query: str) -> list[dict]:
        collection = COLLECTION_GIMP_PROCEDURES if editor == "gimp" else COLLECTION_KRITA_API
        top_k = self.settings.rag.top_k_procedures
        return self._query(collection, query, top_k)

    def retrieve_examples(self, editor: str, query: str) -> list[dict]:
        collection = COLLECTION_GIMP_EXAMPLES if editor == "gimp" else COLLECTION_KRITA_EXAMPLES
        top_k = self.settings.rag.top_k_examples
        return self._query(collection, query, top_k)

    def retrieve_all(self, editor: str, query: str) -> dict[str, list[dict]]:
        return {
            "procedures": self.retrieve_procedures(editor, query),
            "examples": self.retrieve_examples(editor, query),
        }

    def _query(self, collection: str, query: str, top_k: int) -> list[dict]:
        if self.store.count(collection) == 0:
            return []
        vector = self._embed_query(query)
        results = self.store.query(collection, vector, top_k=top_k)
        docs = []
        for doc_id, score, metadata in results:
            doc = dict(metadata)
            doc["_id"] = doc_id
            doc["_score"] = round(score, 4)
            docs.append(doc)
        return docs


def make_retriever(settings: Settings, client: OllamaClient | None = None) -> Retriever:
    """Build a Retriever with a dependency-free store unless chromadb is available."""

    from pixelpilot.rag.indexer import _make_store

    client = client or OllamaClient(settings.ollama.base_url)
    store = _make_store(settings)
    return Retriever(client, store, settings)
