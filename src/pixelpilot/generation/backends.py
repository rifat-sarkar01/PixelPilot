"""Critique backend protocol and concrete implementations.

A CritiqueBackend receives a rendered PNG and the original user request,
and returns a CritiqueResult describing whether the image is acceptable
and what problems were found.

Two backends are provided:
  LocalCritiqueBackend  — uses the local Ollama vision model (default)
  CloudCritiqueBackend  — pluggable HTTP endpoint (opt-in, never required)

Usage::

    backend = LocalCritiqueBackend(client, model="pixelpilot-vision")
    result = backend.analyze(png_bytes, "draw a red car")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pixelpilot.feedback.screenshot import to_base64
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.prompts.generation import CRITIQUE_PROMPT

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CritiqueResult:
    """Outcome of one critique pass."""

    ok: bool
    """True if the image matches the request well enough to stop iterating."""

    issues: list[str] = field(default_factory=list)
    """Human-readable list of problems found."""

    raw: str = ""
    """Raw model output, for debugging."""

    @classmethod
    def acceptable(cls) -> "CritiqueResult":
        return cls(ok=True, issues=[])

    @classmethod
    def failed_parse(cls, raw: str) -> "CritiqueResult":
        """Used when the critique model returns unparseable output."""
        return cls(ok=True, issues=[], raw=raw)  # treat as 'ok' to avoid infinite loop


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class CritiqueBackend(Protocol):
    """Protocol for critique backends."""

    def analyze(self, image_png: bytes, request: str) -> CritiqueResult:
        """Analyse *image_png* and return a :class:`CritiqueResult`."""
        ...


# ---------------------------------------------------------------------------
# Local (Ollama) backend — default
# ---------------------------------------------------------------------------

class LocalCritiqueBackend:
    """Vision critique via the local Ollama vision model."""

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        temperature: float = 0.3,
        timeout: float = 600.0,
    ) -> None:
        if not model:
            raise ValueError("LocalCritiqueBackend requires a non-empty model name")
        self.client = client
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def analyze(self, image_png: bytes, request: str) -> CritiqueResult:
        prompt = CRITIQUE_PROMPT.format(request=request)
        img_b64 = to_base64(image_png)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": prompt, "images": [img_b64]}
        ]
        try:
            response = self.client.chat(
                self.model,
                messages,
                stream=False,
                temperature=self.temperature,
                timeout=self.timeout,
                think=False,
            )
            content: str = (response.get("message") or {}).get("content", "")
        except Exception as exc:  # noqa: BLE001
            # Vision model unreachable — treat as acceptable so we don't block
            return CritiqueResult(ok=True, issues=[], raw=f"critique error: {exc}")

        return self._parse(content)

    @staticmethod
    def _parse(content: str) -> CritiqueResult:
        match = _JSON_RE.search(content)
        if not match:
            return CritiqueResult.failed_parse(content)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return CritiqueResult.failed_parse(content)
        ok = bool(data.get("ok", True))
        issues = [str(i) for i in (data.get("issues") or [])]
        return CritiqueResult(ok=ok, issues=issues, raw=content)


# ---------------------------------------------------------------------------
# Cloud backend — opt-in
# ---------------------------------------------------------------------------

class CloudCritiqueBackend:
    """HTTP-based critique backend for any OpenAI-compatible vision API.

    This is intentionally a thin wrapper.  It is never a hard dependency —
    the user must explicitly configure it via ``generation.critique_backend``.

    Example config::

        generation:
          critique_backend: cloud
          critique_cloud_url: https://generativelanguage.googleapis.com/v1beta/...
          critique_cloud_key: sk-...
    """

    def __init__(self, url: str, api_key: str, model: str = "gemini-flash") -> None:
        self.url = url
        self.api_key = api_key
        self.model = model

    def analyze(self, image_png: bytes, request: str) -> CritiqueResult:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for CloudCritiqueBackend") from exc

        import base64

        img_b64 = base64.b64encode(image_png).decode()
        prompt = CRITIQUE_PROMPT.format(request=request)

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    ],
                }
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = httpx.post(self.url, json=payload, headers=headers, timeout=60.0)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            return CritiqueResult(ok=True, issues=[], raw=f"cloud critique error: {exc}")

        return LocalCritiqueBackend._parse(content)
