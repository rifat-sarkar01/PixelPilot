"""Ollama interface - direct REST API integration (no wrapper libraries)."""

from pixelpilot.ollama.client import OllamaAPIError, OllamaClient, OllamaConnectionError
from pixelpilot.ollama.models import (
    ModelInfo,
    ModelRecommendation,
    list_installed_models,
    recommend_models,
)

__all__ = [
    "ModelInfo",
    "ModelRecommendation",
    "OllamaAPIError",
    "OllamaClient",
    "OllamaConnectionError",
    "list_installed_models",
    "recommend_models",
]
