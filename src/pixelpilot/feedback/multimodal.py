"""Detection for vision models that reject image input.

Ollama accepts ordinary chat requests for text-only models, but rejects a chat
containing ``images`` with HTTP 400. That is a capability mismatch, not a
critique of the rendered image, so it must not trigger a code-generation
recovery round.
"""

from __future__ import annotations

from pixelpilot.ollama.client import OllamaAPIError


# These model families are language-only in Ollama.  Keep this list deliberately
# small: an unfamiliar model should still be tried, because Ollama can host
# custom multimodal models under arbitrary names.
_KNOWN_TEXT_ONLY_PREFIXES = ("gpt-oss",)


def known_image_input_rejection(model: str) -> str | None:
    """Return a user-facing reason when *model* is known to be text-only.

    This avoids submitting screenshots to a model such as ``gpt-oss:20b`` and
    producing a confusing HTTP 400 on every generation or edit.
    """
    normalized = model.strip().lower()
    if normalized.startswith(_KNOWN_TEXT_ONLY_PREFIXES):
        return (
            f"{model} is a text-only model and cannot inspect images. "
            "Choose a separate vision model such as qwen3-vl, llava, gemma3, "
            "or pixelpilot-vision."
        )
    return None


def rejected_image_input(exc: Exception) -> bool:
    """Return whether Ollama rejected the image-bearing vision request.

    This helper is called only from image-bearing vision requests. Ollama
    reports unsupported image input as a 400 response; keeping the check on
    the typed API error avoids treating malformed model output or connection
    failures as a reason to disable vision.
    """
    return isinstance(exc, OllamaAPIError) and exc.status_code == 400
