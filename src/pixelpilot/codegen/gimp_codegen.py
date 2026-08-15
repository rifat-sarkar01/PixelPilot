"""GIMP script generator - translates IR operations into Python-Fu.

Output uses the classic ``gimpfu`` / PDB style that runs inside GIMP's Python-Fu
console and GIMP 3.x's backwards-compatible ``gimpfu`` shim.
"""

from __future__ import annotations

from pixelpilot.codegen.ir import Operation, ScriptPlan

BLEND_MODES: dict[str, str] = {
    "normal": "NORMAL_MODE",
    "multiply": "MULTIPLY_MODE",
    "screen": "SCREEN_MODE",
    "overlay": "OVERLAY_MODE",
    "soft-light": "SOFTLIGHT_MODE",
    "hard-light": "HARDLIGHT_MODE",
    "darken": "DARKEN_MODE",
    "lighten": "LIGHTEN_MODE",
    "add": "ADDITION_MODE",
    "subtract": "SUBTRACT_MODE",
    "difference": "DIFFERENCE_MODE",
    "color": "COLOR_MODE",
    "saturation": "SATURATION_MODE",
    "luminosity": "LUMINOSITY_MODE",
    "dodge": "DODGE_MODE",
    "burn": "BURN_MODE",
}

DRAWABLE_FILL = {
    "foreground": "FOREGROUND_FILL",
    "background": "BACKGROUND_FILL",
    "white": "WHITE_FILL",
    "black": "BLACK_FILL",
    "transparent": "TRANSPARENT_FILL",
}

HEADER = '''from gimpfu import *

def run_pixelpilot():
    images = gimp.image_list()
    if not images:
        raise RuntimeError("No open images - open or create one first.")
    image = images[0]
    drawable = image.active_drawable

    pdb.gimp_image_undo_group_start(image)
    try:
'''

FOOTER = '''        pdb.gimp_displays_flush()
    finally:
        pdb.gimp_image_undo_group_end(image)

run_pixelpilot()
'''


class GimpCodeGen:
    """Translate a :class:`ScriptPlan` into an executable Python-Fu script."""

    def __init__(self, version: str = "3.0") -> None:
        self.version = version

    def render(self, plan: ScriptPlan) -> str:
        body_lines: list[str] = []
        for op in plan.operations:
            rendered = self.render_operation(op)
            if rendered:
                body_lines.extend(rendered)
        if not body_lines:
            body_lines.append("        # (no supported operations in this plan)")
        return HEADER + "\n".join(body_lines) + "\n" + FOOTER

    def render_operation(self, op: Operation) -> list[str]:
        handler = getattr(self, f"_op_{op.type.replace('.', '_')}", None)
        if handler is None:
            return [
                f"        # [unhandled] {op.type} - not yet implemented in GimpCodeGen",
                f"        # params: {op.params}",
            ]
        return handler(op)

    # ------------------------------------------------------------------ layers

    def _op_layer_new(self, op: Operation) -> list[str]:
        name = op.params.get("name", "New Layer")
        width = op.params.get("width", "image.width")
        height = op.params.get("height", "image.height")
        blend = BLEND_MODES.get(str(op.params.get("blend_mode", "normal")).lower(), "NORMAL_MODE")
        opacity = float(op.params.get("opacity", 100))
        lines = [
            (
                f"        layer = pdb.gimp_layer_new(image, {width}, {height}, RGBA_IMAGE, "
                f"'{name}', {opacity}, {blend})"
            ),
            "        pdb.gimp_image_insert_layer(image, layer, None, -1)",
        ]
        if op.description:
            lines.insert(0, f"        # {op.description}")
        return lines

    def _op_layer_duplicate(self, op: Operation) -> list[str]:
        name = op.params.get("name", "Layer Copy")
        return [
            "        source = image.active_drawable",
            "        copy = pdb.gimp_layer_copy(source, 1)",
            f"        pdb.gimp_item_set_name(copy, '{name}')",
            "        pdb.gimp_image_insert_layer(image, copy, None, -1)",
        ]

    def _op_layer_set_opacity(self, op: Operation) -> list[str]:
        return [f"        pdb.gimp_layer_set_opacity(image.active_drawable, {float(op.params.get('opacity', 100))})"]

    def _op_layer_set_blend_mode(self, op: Operation) -> list[str]:
        mode = BLEND_MODES.get(str(op.params.get("mode", "normal")).lower(), "NORMAL_MODE")
        return [f"        pdb.gimp_layer_set_mode(image.active_drawable, {mode})"]

    def _op_layer_set_visible(self, op: Operation) -> list[str]:
        visible = "1" if op.params.get("visible", True) else "0"
        return [f"        pdb.gimp_item_set_visible(image.active_drawable, {visible})"]

    def _op_layer_merge_down(self, op: Operation) -> list[str]:
        return ["        merged = pdb.gimp_image_merge_down(image, image.active_drawable, 0)"]

    # ---------------------------------------------------------------- selections

    def _op_selection_by_color(self, op: Operation) -> list[str]:
        color = op.params.get("color", [0, 0, 0])
        threshold = float(op.params.get("threshold", 15))
        color_str = ", ".join(str(int(c)) for c in color)
        return [
            f"        pdb.gimp_context_set_foreground(({color_str}, 255))",
            (
                f"        pdb.gimp_image_select_color(image, CHANNEL_OP_REPLACE, "
                f"image.active_drawable, ({color_str}, 255), {threshold})"
            ),
        ]

    def _op_selection_invert(self, op: Operation) -> list[str]:
        return ["        pdb.gimp_selection_invert(image)"]

    def _op_selection_all(self, op: Operation) -> list[str]:
        return ["        pdb.gimp_selection_all(image)"]

    def _op_selection_none(self, op: Operation) -> list[str]:
        return ["        pdb.gimp_selection_none(image)"]

    def _op_selection_grow(self, op: Operation) -> list[str]:
        return [f"        pdb.gimp_selection_grow(image, {int(op.params.get('amount', 1))})"]

    def _op_selection_feather(self, op: Operation) -> list[str]:
        return [f"        pdb.gimp_selection_feather(image, {float(op.params.get('radius', 5.0))})"]

    # ------------------------------------------------------------- color & tone

    def _op_colors_brightness_contrast(self, op: Operation) -> list[str]:
        brightness = float(op.params.get("brightness", 0))
        contrast = float(op.params.get("contrast", 0))
        return [
            f"        pdb.gimp_brightness_contrast(image.active_drawable, {brightness}, {contrast})"
        ]

    def _op_colors_desaturate(self, op: Operation) -> list[str]:
        # DESATURATE_LUMINOSITY = 0, AVERAGE = 1, LIGHTNESS = 2
        mode = {"luminosity": 0, "average": 1, "lightness": 2}.get(
            str(op.params.get("mode", "luminosity")).lower(), 0
        )
        return [f"        pdb.gimp_desaturate_full(image.active_drawable, {mode})"]

    def _op_colors_levels(self, op: Operation) -> list[str]:
        low = float(op.params.get("low_input", 0))
        high = float(op.params.get("high_input", 255))
        gamma = float(op.params.get("gamma", 1.0))
        low_out = float(op.params.get("low_output", 0))
        high_out = float(op.params.get("high_output", 255))
        return [
            (
                f"        pdb.gimp_levels(image.active_drawable, HISTOGRAM_VALUE, "
                f"{low}, {high}, {gamma}, {low_out}, {high_out})"
            )
        ]

    def _op_colors_hue_saturation(self, op: Operation) -> list[str]:
        hue = float(op.params.get("hue", 0))
        saturation = float(op.params.get("saturation", 0))
        lightness = float(op.params.get("lightness", 0))
        return [
            (
                f"        pdb.gimp_hue_saturation(image.active_drawable, HUE_RANGE_ALL, "
                f"{hue}, {saturation}, {lightness})"
            )
        ]

    def _op_colors_colorize(self, op: Operation) -> list[str]:
        hue = float(op.params.get("hue", 0))
        saturation = float(op.params.get("saturation", 50))
        lightness = float(op.params.get("lightness", 0))
        return [
            f"        pdb.gimp_colorize(image.active_drawable, {hue}, {saturation}, {lightness})"
        ]

    # ------------------------------------------------------------------ filters

    def _op_filter_gaussian_blur(self, op: Operation) -> list[str]:
        rx = float(op.params.get("radius_x", op.params.get("radius", 5)))
        ry = float(op.params.get("radius_y", op.params.get("radius", 5)))
        return [
            f"        pdb.plug_in_gauss(image, image.active_drawable, {rx}, {ry}, 0)"
        ]

    def _op_filter_unsharp_mask(self, op: Operation) -> list[str]:
        amount = float(op.params.get("amount", 0.5))
        radius = float(op.params.get("radius", 2.0))
        threshold = float(op.params.get("threshold", 0))
        return [
            f"        pdb.plug_in_unsharp_mask(image, image.active_drawable, {radius}, {amount}, {threshold})"
        ]

    def _op_filter_noise(self, op: Operation) -> list[str]:
        amount = float(op.params.get("amount", 0.2))
        return [f"        pdb.plug_in_noise(image, image.active_drawable, {amount}, 0, 0)"]

    # ---------------------------------------------------------------- transform

    def _op_transform_scale(self, op: Operation) -> list[str]:
        width = int(op.params.get("width", 800))
        height = int(op.params.get("height", 600))
        return [
            f"        pdb.gimp_image_scale_full(image, {width}, {height}, INTERPOLATION_CUBIC)"
        ]

    def _op_transform_flip(self, op: Operation) -> list[str]:
        direction = op.params.get("direction", "horizontal")
        flip = 1 if direction == "horizontal" else 0
        return [
            (
                f"        flipped = pdb.gimp_item_transform_flip_simple(image.active_drawable, "
                f"{flip}, 1, 0)"
            )
        ]

    def _op_transform_rotate(self, op: Operation) -> list[str]:
        degrees = float(op.params.get("degrees", 90))
        return [
            (
                f"        rotated = pdb.gimp_item_transform_rotate_simple(image.active_drawable, "
                f"{degrees}, 1, 0)"
            )
        ]

    # ------------------------------------------------------------------ editing

    def _op_edit_fill(self, op: Operation) -> list[str]:
        fill = DRAWABLE_FILL.get(str(op.params.get("fill", "foreground")).lower(), "FOREGROUND_FILL")
        return [
            f"        pdb.gimp_context_set_foreground(({_color_tuple(op.params.get('color', [255, 255, 255]))}))",
            f"        pdb.gimp_edit_fill(image.active_drawable, {fill})",
        ]

    # -------------------------------------------------------------------- image

    def _op_image_flatten(self, op: Operation) -> list[str]:
        return ["        pdb.gimp_image_flatten(image)"]

    def _op_image_duplicate(self, op: Operation) -> list[str]:
        return ["        duplicate = pdb.gimp_image_duplicate(image)"]

    def _op_image_convert_rgb(self, op: Operation) -> list[str]:
        return ["        pdb.gimp_image_convert_rgb(image)"]


def _color_tuple(color) -> str:
    if isinstance(color, (list, tuple)):
        return ", ".join(str(int(c)) for c in color) + ", 255"
    return f"{color}, 255"
