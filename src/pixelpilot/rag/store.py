"""Vector store abstraction.

PixelPilot uses a fully local vector store for RAG. ``ChromaStore`` is the plan's
default (``chromadb``, embedded, SQLite-backed) but requires the optional
``chromadb`` dependency. ``SimpleMemoryStore`` is a dependency-free pure-Python
fallback with the same interface - fine for the bundled starter knowledge base.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

Collection = str


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors (pure Python)."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore(ABC):
    """Minimal vector-store interface used by the RAG pipeline."""

    @abstractmethod
    def add_many(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None: ...

    @abstractmethod
    def query(
        self,
        collection: str,
        vector: list[float],
        top_k: int = 5,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Return ``(id, score, metadata)`` tuples, best score first."""

    @abstractmethod
    def count(self, collection: str) -> int: ...

    @abstractmethod
    def delete_collection(self, collection: str) -> None: ...


class SimpleMemoryStore(VectorStore):
    """In-memory vector store with optional JSON persistence.

    Vectors are stored per collection; cosine similarity is computed lazily on query.
    Good enough for a starter knowledge base (~100-200 documents) and zero deps.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path).expanduser() if path else None
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._load()

    # --------------------------------------------------------------- persistence

    def _load(self) -> None:
        if self._path and self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data), encoding="utf-8")

    # --------------------------------------------------------------- interface

    def add_many(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        bucket = self._data.setdefault(collection, [])
        for idx, doc_id in enumerate(ids):
            bucket.append(
                {
                    "id": doc_id,
                    "vector": vectors[idx],
                    "metadata": (metadatas[idx] if metadatas else {}),
                }
            )
        self._save()

    def query(
        self,
        collection: str,
        vector: list[float],
        top_k: int = 5,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        bucket = self._data.get(collection, [])
        scored = [(d["id"], cosine_similarity(vector, d["vector"]), d["metadata"]) for d in bucket]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]

    def count(self, collection: str) -> int:
        return len(self._data.get(collection, []))

    def delete_collection(self, collection: str) -> None:
        self._data.pop(collection, None)
        self._save()


class ChromaStore(VectorStore):
    """chromadb-backed store (optional dependency). Uses persistent local storage."""

    def __init__(self, path: str | None = None, *, instance_path: str | None = None) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "chromadb is not installed. Install it with: pip install 'pixelpilot[rag]' "
                "or use SimpleMemoryStore."
            ) from exc

        if path:
            base = Path(path).expanduser()
            base.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(base))
        else:
            self._client = chromadb.Client()
        self._collections: dict[str, Any] = {}

    def _collection(self, name: str):
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(name=name)
        return self._collections[name]

    def add_many(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        self._collection(collection).add(ids=ids, embeddings=vectors, metadatas=metadatas)

    def query(
        self,
        collection: str,
        vector: list[float],
        top_k: int = 5,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        result = self._collection(collection).query(query_embeddings=[vector], n_results=top_k)
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        scores = []
        for doc_id, dist, meta in zip(ids, distances, metadatas):
            # chromadb returns a distance; convert to a 0..1 similarity score.
            similarity = 1.0 - float(dist)
            scores.append((str(doc_id), similarity, meta or {}))
        return scores

    def count(self, collection: str) -> int:
        return self._collection(collection).count()

    def delete_collection(self, collection: str) -> None:
        self._client.delete_collection(name=collection)
        self._collections.pop(collection, None)
