"""Index the bundled knowledge base into a local vector store.

Embeds procedures and examples with the configured Ollama embedding model
(default ``nomic-embed-text``) and stores the vectors locally.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pixelpilot.config import Settings
from pixelpilot.knowledge import load_examples, load_gimp_pdb, load_krita_api
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.rag.store import VectorStore


@dataclass
class IndexReport:
    collections: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.collections.values())

    def __str__(self) -> str:
        lines = ["RAG index summary:"]
        for name, count in self.collections.items():
            lines.append(f"  - {name:<24} {count}")
        lines.append(f"  - {'TOTAL':<24} {self.total}")
        return "\n".join(lines)


COLLECTION_GIMP_PROCEDURES = "gimp_procedures"
COLLECTION_KRITA_API = "krita_api"
COLLECTION_GIMP_EXAMPLES = "gimp_examples"
COLLECTION_KRITA_EXAMPLES = "krita_examples"


def _procedure_text(proc: dict) -> str:
    """A searchable text representation of a procedure for embedding."""
    parts = [proc.get("name", "")]
    if proc.get("signature"):
        parts.append(proc["signature"])
    if proc.get("gimp3_signature"):
        parts.append(proc["gimp3_signature"])
    if proc.get("category"):
        parts.append(f"category: {proc['category']}")
    if proc.get("description"):
        parts.append(proc["description"])
    return "\n".join(parts)


def _example_text(example: dict) -> str:
    return "\n".join(
        [
            example.get("prompt", ""),
            f"category: {example.get('category', '')}",
            example.get("code", ""),
        ]
    )


class KnowledgeBaseIndexer:
    def __init__(self, client: OllamaClient, store: VectorStore, settings: Settings) -> None:
        self.client = client
        self.store = store
        self.settings = settings
        self.embed_model = settings.ollama.embed_model

    def _embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # /api/embed accepts a batch of inputs.
        return self.client.embed(self.embed_model, texts)

    def index_procedures(self) -> None:
        gimp = load_gimp_pdb()
        self._index(COLLECTION_GIMP_PROCEDURES, gimp, _procedure_text)

        krita = load_krita_api()
        self._index(COLLECTION_KRITA_API, krita, _procedure_text)

    def index_examples(self) -> None:
        self._index(COLLECTION_GIMP_EXAMPLES, load_examples("gimp"), _example_text)
        self._index(COLLECTION_KRITA_EXAMPLES, load_examples("krita"), _example_text)

    def _index(self, collection: str, docs: list[dict], text_fn) -> None:
        self.store.delete_collection(collection)
        if not docs:
            return
        texts = [text_fn(d) for d in docs]
        vectors = self._embed_many(texts)
        ids = [f"{collection}:{idx}" for idx in range(len(docs))]
        self.store.add_many(collection, ids, vectors, metadatas=docs)

    def build(self) -> IndexReport:
        self.index_procedures()
        self.index_examples()
        return IndexReport(
            collections={
                COLLECTION_GIMP_PROCEDURES: self.store.count(COLLECTION_GIMP_PROCEDURES),
                COLLECTION_KRITA_API: self.store.count(COLLECTION_KRITA_API),
                COLLECTION_GIMP_EXAMPLES: self.store.count(COLLECTION_GIMP_EXAMPLES),
                COLLECTION_KRITA_EXAMPLES: self.store.count(COLLECTION_KRITA_EXAMPLES),
            }
        )


def _make_store(settings: Settings) -> VectorStore:
    from pathlib import Path

    db_path = Path(settings.rag.db_path).expanduser()
    try:
        from pixelpilot.rag.store import ChromaStore

        return ChromaStore(db_path)
    except ImportError:
        # chromadb not installed -> dependency-free JSON-persisted memory store.
        from pixelpilot.rag.store import SimpleMemoryStore

        return SimpleMemoryStore(path=str(db_path / "vectors.json"))


def build_index(settings: Settings) -> IndexReport:
    """Build (or rebuild) the RAG index. Returns an :class:`IndexReport`."""
    client = OllamaClient(settings.ollama.base_url)
    client.health_check()
    store = _make_store(settings)
    indexer = KnowledgeBaseIndexer(client, store, settings)
    return indexer.build()
