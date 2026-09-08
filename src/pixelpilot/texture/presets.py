"""Texture presets — maps TextureName enums to GIMP Script-Fu recipes.

Each preset defines a GIMP Script-Fu command string that can be evaluated
headlessly. The script operates on the current image with the selection
already set to the object's alpha mask.

The LLM never invents arbitrary texture descriptions — it only picks from
the TextureName enum, keeping this step reliable.
"""

from __future__ import annotations

from dataclasses import dataclass

from pixelpilot.generation.schema import TextureName


@dataclass(frozen=True)
class TextureRecipe:
    """A concrete GIMP filter recipe for a texture preset."""

    name: str
    """Human-readable name for logging."""

    script_template: str
    """Script-Fu template.  {image_id} and {layer_id} are substituted at runtime."""

    description: str
    """Short description for UI display."""


# ---------------------------------------------------------------------------
# Preset registry
# ---------------------------------------------------------------------------

_PRESETS: dict[TextureName, TextureRecipe] = {
    TextureName.LEAF_NOISE: TextureRecipe(
        name="Leaf Noise",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (gimp-drawable-edit-fill layer FILL-NONE)"
            "  (plug-in-hsv-grain RUN-NONINTERACTIVE image layer 0.3 0.4 0.8)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Organic noise pattern for foliage",
    ),
    TextureName.BARK_ROUGH: TextureRecipe(
        name="Bark Rough",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (plug-in-noise-hsv RUN-NONINTERACTIVE image layer 0 2 0.15 0.05 0.3)"
            "  (plug-in-mblur RUN-NONINTERACTIVE image layer 0 3 0 0)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Rough vertical grain for tree bark",
    ),
    TextureName.STONE_GRAIN: TextureRecipe(
        name="Stone Grain",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (plug-in-noise-hsv RUN-NONINTERACTIVE image layer 0 1 0.1 0.02 0.15)"
            "  (plug-in-gauss-run2 RUN-NONINTERACTIVE image layer 1.5 1.5 0)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Subtle grain for stone or concrete",
    ),
    TextureName.WATER_RIPPLE: TextureRecipe(
        name="Water Ripple",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (plug-in-maze-run RUN-NONINTERACTIVE image layer 3 5 0 0 0)"
            "  (plug-in-gauss-run2 RUN-NONINTERACTIVE image layer 2 0.5 0)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Ripple pattern for water surfaces",
    ),
    TextureName.WOOD_GRAIN: TextureRecipe(
        name="Wood Grain",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (plug-in-noise-hsv RUN-NONINTERACTIVE image layer 0 2 0.12 0.08 0.25)"
            "  (plug-in-mblur RUN-NONINTERACTIVE image layer 0 8 90 0)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Horizontal grain for wooden surfaces",
    ),
    TextureName.SAND_FINE: TextureRecipe(
        name="Sand Fine",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (plug-in-noise-hsv RUN-NONINTERACTIVE image layer 0 1 0.08 0.03 0.1)"
            "  (plug-in-gauss-run2 RUN-NONINTERACTIVE image layer 0.5 0.5 0)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Fine granular texture for sand",
    ),
    TextureName.BRICK_PATTERN: TextureRecipe(
        name="Brick Pattern",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (gimp-patterns-set-pattern \"Brick\")"
            "  (gimp-drawable-edit-fill layer PATTERN-_FILL)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Repeating brick pattern",
    ),
    TextureName.METAL_BRUSH: TextureRecipe(
        name="Metal Brush",
        script_template=(
            "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{path}\" \"{path}\")))"
            "  (layer (car (gimp-image-get-active-drawable image))))"
            "  (plug-in-noise-hsv RUN-NONINTERACTIVE image layer 0 1 0.05 0.01 0.08)"
            "  (plug-in-mblur RUN-NONINTERACTIVE image layer 0 12 0 0)"
            "  (gimp-image-flatten image)"
            "  (file-png-save RUN-NONINTERACTIVE image layer \"{out}\" \"{out}\" 0 9 1 1 1 1 1))"
        ),
        description="Brushed metal finish with horizontal strokes",
    ),
}


def get_recipe(texture: TextureName) -> TextureRecipe:
    """Look up the GIMP Script-Fu recipe for *texture*."""
    recipe = _PRESETS.get(texture)
    if recipe is None:
        raise KeyError(f"Unknown texture preset: {texture!r}")
    return recipe


def available_textures() -> list[TextureName]:
    """Return all registered texture preset names."""
    return list(_PRESETS.keys())
