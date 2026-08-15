"""Direct REST API client for Ollama.

Speaks to ``http://localhost:11434`` (or a configured URL) using only ``httpx``.
No wrapper libraries, no SDKs - just the handful of endpoints Ollama exposes.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import httpx

from pixelpilot.ollama.streaming import iter_ndjson


class OllamaConnectionError(RuntimeError):
    """Ollama server is unreachable or did not respond."""


class OllamaAPIError(RuntimeError):
    """Ollama returned a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Ollama API error {status_code}: {detail}")


class OllamaClient:
    """Synchronous HTTP client for the Ollama REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    # ------------------------------------------------------------------ health

    def ping(self) -> bool:
        """Return True if Ollama responds at the configured URL."""
        try:
            resp = self._client.get("/api/tags", timeout=5.0)
            return resp.status_code < 500
        except (httpx.HTTPError, ValueError):
            return False

    def health_check(self) -> None:
        """Raise ``OllamaConnectionError`` if the server is unreachable."""
        if not self.ping():
            raise OllamaConnectionError(
                f"Ollama is not responding at {self.base_url}. "
                "Start it with: ollama serve"
            )

    # ------------------------------------------------------------------ models

    def list_models(self) -> list[dict[str, Any]]:
        resp = self._request("GET", "/api/tags")
        return resp.get("models", [])

    def show_model(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/api/show", json={"name": name})

    def ps(self) -> dict[str, Any]:
        return self._request("GET", "/api/ps")

    def pull_model(
        self, name: str, stream: bool = False
    ) -> list[dict[str, Any]] | Generator[dict[str, Any], None, None]:
        payload = {"name": name, "stream": stream}
        if stream:
            return self._stream("POST", "/api/pull", json=payload)
        return self._request("POST", "/api/pull", json=payload)

    def create_model(
        self, name: str, modelfile: str, stream: bool = False
    ) -> list[dict[str, Any]] | Generator[dict[str, Any], None, None]:
        payload = {"name": name, "modelfile": modelfile, "stream": stream}
        if stream:
            return self._stream("POST", "/api/create", json=payload)
        return self._request("POST", "/api/create", json=payload)

    def delete_model(self, name: str) -> dict[str, Any]:
        return self._request("DELETE", "/api/delete", json={"name": name})

    # ------------------------------------------------------------- inference

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        images: list[str] | None = None,
        timeout: float | None = None,
        **params: Any,
    ) -> dict[str, Any] | Generator[dict[str, Any], None, None]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
        if images:
            payload["images"] = images
        payload.update(params)
        if stream:
            return self._stream("POST", "/api/chat", json=payload, timeout=timeout)
        return self._request("POST", "/api/chat", json=payload, timeout=timeout)

    def generate(
        self,
        model: str,
        prompt: str,
        stream: bool = False,
        images: list[str] | None = None,
        **params: Any,
    ) -> dict[str, Any] | Generator[dict[str, Any], None, None]:
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": stream}
        if images:
            payload["images"] = images
        payload.update(params)
        if stream:
            return self._stream("POST", "/api/generate", json=payload)
        return self._request("POST", "/api/generate", json=payload)

    # --------------------------------------------------------------- embeddings

    def embed(self, model: str, input: list[str]) -> list[list[float]]:
        """Return a list of embeddings, one per input string."""
        resp = self._request("POST", "/api/embed", json={"model": model, "input": input})
        return resp.get("embeddings", [])

    def embed_single(self, model: str, text: str) -> list[float]:
        embeddings = self.embed(model, [text])
        if not embeddings:
            raise OllamaAPIError(0, f"embedding model {model} returned no vectors")
        return embeddings[0]

    # --------------------------------------------------------------- internals

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        timeout = kwargs.pop("timeout", None)
        try:
            if timeout is not None:
                resp = self._client.request(method, path, timeout=timeout, **kwargs)
            else:
                resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise OllamaConnectionError(f"Request to {self.base_url}{path} failed: {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.text[:500]
            try:
                body = resp.json()
                detail = json.dumps(body)[:500]
            except ValueError:
                pass
            raise OllamaAPIError(resp.status_code, detail)
        try:
            return resp.json()
        except Exception as exc:
            raise OllamaAPIError(resp.status_code, f"invalid JSON response: {resp.text[:200]}") from exc

    def _stream(
        self, method: str, path: str, **kwargs: Any
    ) -> Generator[dict[str, Any], None, None]:
        timeout = kwargs.pop("timeout", None)
        if timeout is not None:
            kwargs["timeout"] = timeout

        def _gen() -> Generator[dict[str, Any], None, None]:
            try:
                with self._client.stream(method, path, **kwargs) as resp:
                    if resp.status_code >= 400:
                        detail = resp.read().decode("utf-8", errors="replace")[:500]
                        raise OllamaAPIError(resp.status_code, detail)
                    yield from iter_ndjson(resp.iter_lines())
            except httpx.HTTPError as exc:
                raise OllamaConnectionError(f"Stream to {self.base_url}{path} failed: {exc}") from exc

        return _gen()
