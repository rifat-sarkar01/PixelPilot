"""Unit tests for the dependency-free vector store."""

import pytest

from pixelpilot.rag.store import SimpleMemoryStore, cosine_similarity


def test_cosine_similarity():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, a) == pytest.approx(1.0)
    assert cosine_similarity(a, b) == pytest.approx(0.0)
    assert cosine_similarity([], []) == 0.0


def test_memory_store_roundtrip():
    store = SimpleMemoryStore()
    store.add_many(
        "test",
        ids=["a", "b"],
        vectors=[[1.0, 0.0], [0.0, 1.0]],
        metadatas=[{"name": "alpha"}, {"name": "beta"}],
    )
    assert store.count("test") == 2
    results = store.query("test", [1.0, 0.0], top_k=1)
    assert results[0][0] == "a"
    assert results[0][1] == pytest.approx(1.0)
    assert results[0][2]["name"] == "alpha"


def test_memory_store_empty_query():
    store = SimpleMemoryStore()
    assert store.query("nothing", [1.0], top_k=5) == []
    assert store.count("nothing") == 0


def test_memory_store_delete_collection():
    store = SimpleMemoryStore()
    store.add_many("c", ["1"], [[1.0, 0.0]])
    store.delete_collection("c")
    assert store.count("c") == 0


def test_memory_store_persistence(tmp_path):
    db_file = tmp_path / "vectors.json"
    store = SimpleMemoryStore(path=str(db_file))
    store.add_many("col", ["id"], [[1.0, 2.0, 3.0]], metadatas=[{"k": "v"}])

    loaded = SimpleMemoryStore(path=str(db_file))
    assert loaded.count("col") == 1
    results = loaded.query("col", [1.0, 2.0, 3.0], top_k=1)
    assert results[0][2]["k"] == "v"


def test_chroma_import_error_when_missing():
    import pytest

    from pixelpilot.rag.store import ChromaStore

    # If chromadb isn't installed, constructing must raise a helpful ImportError.
    try:
        import chromadb  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError):
            ChromaStore(path="whatever")
