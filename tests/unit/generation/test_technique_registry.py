"""Unit tests for technique/registry.py.

Covers:
- Registry loads bundled recipes.yaml without errors
- get_recipe returns a valid Recipe object for each known preset
- get_recipe raises KeyError for unknown presets
- Enum validation: schema rejects surface/shading/outline values not in registry
"""

from __future__ import annotations

import pytest

from pixelpilot.technique.registry import (
    Recipe,
    RecipeOp,
    TechniqueCategory,
    TechniqueRegistry,
    get_recipe,
    get_registry,
    load_registry,
)


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

class TestRegistryLoad:
    def test_loads_without_error(self):
        registry = load_registry()
        assert isinstance(registry, TechniqueRegistry)

    def test_singleton_get_registry(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2   # same object — singleton

    def test_surface_presets_present(self):
        registry = load_registry()
        presets = registry.list_presets(TechniqueCategory.SURFACE)
        assert "leaf_noise" in presets
        assert "bark_rough" in presets
        assert "stone_grain" in presets

    def test_shading_presets_present(self):
        registry = load_registry()
        presets = registry.list_presets(TechniqueCategory.SHADING)
        assert "soft_bevel" in presets
        assert "drop_shadow" in presets

    def test_outline_presets_present(self):
        registry = load_registry()
        presets = registry.list_presets(TechniqueCategory.OUTLINE)
        assert "thin_dark" in presets

    def test_global_post_presets_present(self):
        registry = load_registry()
        presets = registry.list_presets(TechniqueCategory.GLOBAL_POST)
        assert "vignette" in presets
        assert "film_grain" in presets

    def test_all_presets_returns_all_categories(self):
        registry = load_registry()
        all_p = registry.all_presets()
        assert set(all_p.keys()) == set(TechniqueCategory)


# ---------------------------------------------------------------------------
# Recipe structure
# ---------------------------------------------------------------------------

class TestRecipeStructure:
    def test_leaf_noise_has_ops(self):
        recipe = get_recipe(TechniqueCategory.SURFACE, "leaf_noise")
        assert isinstance(recipe, Recipe)
        assert len(recipe.ops) >= 1
        assert all(isinstance(op, RecipeOp) for op in recipe.ops)

    def test_bark_rough_multi_op(self):
        recipe = get_recipe(TechniqueCategory.SURFACE, "bark_rough")
        assert len(recipe.ops) >= 2

    def test_soft_bevel_params(self):
        recipe = get_recipe(TechniqueCategory.SHADING, "soft_bevel")
        assert len(recipe.ops) >= 1
        op = recipe.ops[0]
        assert "azimuth" in op.params or "elevation" in op.params

    def test_thin_dark_is_pseudo_op(self):
        recipe = get_recipe(TechniqueCategory.OUTLINE, "thin_dark")
        assert len(recipe.ops) >= 1
        assert recipe.ops[0].op == "select-grow-subtract"

    def test_recipe_description_nonempty(self):
        for cat in TechniqueCategory:
            registry = get_registry()
            for name in registry.list_presets(cat):
                recipe = get_recipe(cat, name)
                assert recipe.description, f"{cat.value}/{name} has no description"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestRegistryErrors:
    def test_unknown_surface_raises_key_error(self):
        with pytest.raises(KeyError, match="freeform_texture"):
            get_recipe(TechniqueCategory.SURFACE, "freeform_texture")

    def test_unknown_shading_raises_key_error(self):
        with pytest.raises(KeyError):
            get_recipe(TechniqueCategory.SHADING, "magic_light")

    def test_unknown_outline_raises_key_error(self):
        with pytest.raises(KeyError):
            get_recipe(TechniqueCategory.OUTLINE, "glitter_border")

    def test_wrong_category_raises_key_error(self):
        # "vignette" is a global_post preset, not a surface preset
        with pytest.raises(KeyError):
            get_recipe(TechniqueCategory.SURFACE, "vignette")


# ---------------------------------------------------------------------------
# Custom registry from dict
# ---------------------------------------------------------------------------

class TestCustomRegistry:
    def _make_registry(self) -> TechniqueRegistry:
        data = {
            "surface": {
                "test_noise": {
                    "description": "Test noise",
                    "ops": [
                        {"op": "plug-in-hsv-noise", "params": {"holdness": 1, "hue": 5, "saturation": 10, "value": 10}}
                    ],
                }
            },
            "shading": {},
            "outline": {},
            "global_post": {},
        }
        return TechniqueRegistry(data)

    def test_custom_registry_get(self):
        reg = self._make_registry()
        recipe = reg.get(TechniqueCategory.SURFACE, "test_noise")
        assert recipe.name == "test_noise"
        assert len(recipe.ops) == 1
        assert recipe.ops[0].op == "plug-in-hsv-noise"

    def test_custom_registry_missing_raises(self):
        reg = self._make_registry()
        with pytest.raises(KeyError):
            reg.get(TechniqueCategory.SURFACE, "nonexistent")
