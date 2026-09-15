"""Vision feedback behaviour around unsupported image input."""

from __future__ import annotations

from pixelpilot.feedback.vision import VisionAnalyzer
from pixelpilot.ollama.client import OllamaAPIError


class _RejectingImageClient:
    def chat(self, *_args, **_kwargs):
        raise OllamaAPIError(400, "model does not support image input")


def test_image_input_rejection_is_marked_for_the_cli():
    result = VisionAnalyzer(_RejectingImageClient(), model="text-only").analyze(b"png")

    assert result["success"] is False
    assert result["image_input_rejected"] is True
