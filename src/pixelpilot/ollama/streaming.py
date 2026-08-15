"""Thin streaming helpers for Ollama's newline-delimited JSON responses."""

from __future__ import annotations

from collections.abc import Iterator


class OllamaStreamError(RuntimeError):
    pass


def iter_ndjson(lines: Iterator[str]) -> Iterator[dict]:
    """Yield parsed JSON objects from newline-delimited JSON lines.

    Ollama returns one JSON object per line for streaming chat/generate/pull.
    Empty or whitespace-only lines are skipped.
    """
    import json

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            raise OllamaStreamError(f"Failed to parse stream chunk: {line!r}") from exc


def collect_generate_stream(chunks: Iterator[dict]) -> str:
    """Concatenate the ``response`` field of /api/generate stream chunks."""
    parts = []
    for chunk in chunks:
        if chunk.get("error"):
            raise OllamaStreamError(str(chunk["error"]))
        parts.append(chunk.get("response", ""))
    return "".join(parts)


def collect_chat_stream(chunks: Iterator[dict]) -> str:
    """Concatenate the assistant message content from /api/chat stream chunks."""
    parts = []
    for chunk in chunks:
        if chunk.get("error"):
            raise OllamaStreamError(str(chunk["error"]))
        msg = chunk.get("message") or {}
        parts.append(msg.get("content", ""))
    return "".join(parts)


def finalize_generate_chunks(chunks: Iterator[dict]) -> str:
    """Alias kept for symmetry with /api/generate callers."""
    return collect_generate_stream(chunks)
