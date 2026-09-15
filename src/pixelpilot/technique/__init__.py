"""Technique pipeline package.

Adds surface quality to the generation pipeline via a declarative recipe
system and a single batched GIMP Script-Fu invocation per image.

Pipeline position::

    base.png (flat shapes)
        |
    [Mask Exporter]   → per-object silhouette masks (same canvas size)
        |
    [Technique Executor]  → one GIMP batch script covering all objects
        |  surface → shading → outline (per object, masked)
        |  global_post passes (whole canvas)
        |
    final.png

Key modules:
    registry  — loads technique/recipes.yaml into typed Recipe objects
    mask_export — renders per-object binary masks from the ImagePlan
    executor  — builds + runs the single batched GIMP Script-Fu script
"""

from __future__ import annotations

from pixelpilot.technique.executor import TechniqueExecutor, find_gimp_binary
from pixelpilot.technique.mask_export import export_masks, needs_technique_pass
from pixelpilot.technique.registry import (
    Recipe,
    RecipeOp,
    TechniqueCategory,
    TechniqueRegistry,
    get_recipe,
    get_registry,
    load_registry,
)

__all__ = [
    "TechniqueExecutor",
    "find_gimp_binary",
    "export_masks",
    "needs_technique_pass",
    "Recipe",
    "RecipeOp",
    "TechniqueCategory",
    "TechniqueRegistry",
    "get_recipe",
    "get_registry",
    "load_registry",
]
