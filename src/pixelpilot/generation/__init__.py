"""Generation pipeline — structured image plan → deterministic renderer.

This package handles the "generate" intent path:
  user prompt → LLM emits ImagePlan JSON → PlanExecutor renders PNG
  → CritiqueLoop (optional vision feedback) → final PNG.

The editing path (GIMP/Krita scripting) is completely unaffected.

Imports are intentionally lazy so that importing this package at CLI startup
does not drag in Pillow or other heavy rasterization dependencies until a
generation request is actually made.
"""

from __future__ import annotations

__all__ = [
    "CanvasSpec",
    "ImagePlan",
    "IntentRouter",
    "PlanExecutor",
    "ShapeObject",
    "ShapeType",
]


def __getattr__(name: str):
    """Lazy attribute resolution — only import heavy modules on first access."""
    if name in ("CanvasSpec", "ImagePlan", "ShapeObject", "ShapeType"):
        from pixelpilot.generation.schema import CanvasSpec, ImagePlan, ShapeObject, ShapeType
        globals().update(
            CanvasSpec=CanvasSpec,
            ImagePlan=ImagePlan,
            ShapeObject=ShapeObject,
            ShapeType=ShapeType,
        )
        return globals()[name]
    if name == "PlanExecutor":
        from pixelpilot.generation.executor import PlanExecutor
        globals()["PlanExecutor"] = PlanExecutor
        return PlanExecutor
    if name == "IntentRouter":
        from pixelpilot.generation.router import IntentRouter
        globals()["IntentRouter"] = IntentRouter
        return IntentRouter
    raise AttributeError(f"module 'pixelpilot.generation' has no attribute {name!r}")
