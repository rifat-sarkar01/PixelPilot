"""Feedback & observation layer: screenshots, vision analysis, error recovery."""

from pixelpilot.feedback.error_recovery import ErrorRecovery
from pixelpilot.feedback.screenshot import capture_png, downscale_and_encode, downscale_png
from pixelpilot.feedback.text_fallback import TextFallbackAnalyzer
from pixelpilot.feedback.vision import VisionAnalyzer

__all__ = [
    "ErrorRecovery",
    "TextFallbackAnalyzer",
    "VisionAnalyzer",
    "capture_png",
    "downscale_and_encode",
    "downscale_png",
]
