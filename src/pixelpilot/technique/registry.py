"""Technique registry — loads and exposes the declarative recipe library.

Maps preset names from the plan schema (SurfacePreset / ShadingPreset /
OutlinePreset / GlobalPostPreset) to ordered lists of GIMP PDB operations.

The LLM never authors operations — it picks only from the enum values defined
here.  Adding a new look means adding a recipe entry to ``recipes.yaml``;
the LLM prompt is updated to widen the enum, but no executor code changes.

Usage::

    from pixelpilot.technique.registry import get_recipe, TechniqueCategory

    ops = get_recipe(TechniqueCategory.SURFACE, "leaf_noise")
    # ops -> [RecipeOp(op="plug-in-hsv-noise", params={...}), ...]
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class TechniqueCategory(str, Enum):
    SURFACE = "surface"
    SHADING = "shading"
    OUTLINE = "outline"
    GLOBAL_POST = "global_post"


@dataclass(frozen=True)
class RecipeOp:
    """A single GIMP PDB call (or PixelPilot pseudo-op) in a recipe."""

    op: str
    """PDB procedure name, e.g. 'plug-in-hsv-noise', or pseudo-op like
    'select-grow-subtract' handled internally by the executor."""

    params: dict[str, Any] = field(default_factory=dict)
    """Key/value parameters.  Types must match the PDB prototype."""


@dataclass(frozen=True)
class Recipe:
    """An ordered list of ops for one named preset."""

    name: str
    description: str
    ops: list[RecipeOp]


class TechniqueRegistry:
    """Loaded view of recipes.yaml.

    Singleton — call :func:`load` once, then use :func:`get`.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data: dict[TechniqueCategory, dict[str, Recipe]] = {}
        for cat in TechniqueCategory:
            section = data.get(cat.value, {}) or {}
            recipes: dict[str, Recipe] = {}
            for preset_name, entry in section.items():
                ops = [
                    RecipeOp(op=op_entry["op"], params=op_entry.get("params", {}))
                    for op_entry in (entry.get("ops") or [])
                ]
                recipes[preset_name] = Recipe(
                    name=preset_name,
                    description=entry.get("description", ""),
                    ops=ops,
                )
            self._data[cat] = recipes

    def get(self, category: TechniqueCategory, preset_name: str) -> Recipe:
        """Return the recipe for *preset_name* in *category*.

        Raises:
            KeyError: if the preset is not in the registry.
        """
        recipes = self._data.get(category, {})
        if preset_name not in recipes:
            available = sorted(recipes.keys())
            raise KeyError(
                f"Unknown {category.value!r} preset {preset_name!r}. "
                f"Available: {available}"
            )
        return recipes[preset_name]

    def list_presets(self, category: TechniqueCategory) -> list[str]:
        """Return sorted preset names for *category*."""
        return sorted(self._data.get(category, {}).keys())

    def all_presets(self) -> dict[TechniqueCategory, list[str]]:
        """Return all preset names grouped by category."""
        return {cat: self.list_presets(cat) for cat in TechniqueCategory}


# ---------------------------------------------------------------------------
# Module-level singleton — loaded lazily on first access
# ---------------------------------------------------------------------------

_registry: TechniqueRegistry | None = None


def _recipes_yaml_path() -> Path:
    """Resolve the path to recipes.yaml bundled with this package."""
    # __file__ is technique/registry.py — recipes.yaml is in the same dir
    return Path(__file__).parent / "recipes.yaml"


def load_registry(path: Path | None = None) -> TechniqueRegistry:
    """Load (or reload) the technique registry from a YAML file.

    Args:
        path: Explicit path to a recipes.yaml file.  Defaults to the
              bundled ``technique/recipes.yaml``.

    Returns:
        The loaded :class:`TechniqueRegistry`.
    """
    global _registry
    yaml_path = path or _recipes_yaml_path()
    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    _registry = TechniqueRegistry(data)
    return _registry


def get_registry() -> TechniqueRegistry:
    """Return the singleton registry, loading it on first call."""
    global _registry
    if _registry is None:
        _registry = load_registry()
    return _registry


def get_recipe(category: TechniqueCategory, preset_name: str) -> Recipe:
    """Convenience wrapper: look up a recipe from the singleton registry."""
    return get_registry().get(category, preset_name)
