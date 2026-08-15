"""Krita script generator - translates IR operations into PyKrita."""

from __future__ import annotations

from pixelpilot.codegen.ir import Operation, ScriptPlan

# Krita blending modes use lowercase names.
BLEND_MODES: dict[str, str] = {
    "normal": "normal",
    "multiply": "multiply",
    "screen": "screen",
    "overlay": "overlay",
    "soft-light": "soft_light",
    "hard-light": "hard_light",
    "darken": "darken",
    "lighten": "lighten",
    "add": "add",
    "subtract": "subtract",
    "difference": "difference",
    "color": "color",
    "saturation": "saturation",
    "luminosity": "luminosity",
    "dodge": "dodge",
    "burn": "burn",
}

HEADER = '''from krita import Krita

def run_pixelpilot():
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        raise RuntimeError("No active document open - open or create one first.")
    node = doc.activeNode()
'''

FOOTER = '''
    doc.refreshProjection()

run_pixelpilot()
'''


class KritaCodeGen:
    """Translate a :class:`ScriptPlan` into an executable PyKrita script."""

    def __init__(self) -> None:
        self._filter_cache: list[str] = []

    def render(self, plan: ScriptPlan) -> str:
        body_lines: list[str] = []
        for op in plan.operations:
            rendered = self.render_operation(op)
            if rendered:
                body_lines.extend(rendered)
        if not body_lines:
            body_lines.append("    # (no supported operations in this plan)")
        return HEADER + "\n".join(body_lines) + FOOTER

    def render_operation(self, op: Operation) -> list[str]:
        handler = getattr(self, f"_op_{op.type.replace('.', '_')}", None)
        if handler is None:
            return [
                f"    # [unhandled] {op.type} - not yet implemented in KritaCodeGen",
                f"    # params: {op.params}",
            ]
        return handler(op)

    # ------------------------------------------------------------------ layers

    def _op_layer_new(self, op: Operation) -> list[str]:
        name = op.params.get("name", "New Layer")
        blend = BLEND_MODES.get(str(op.params.get("blend_mode", "normal")).lower(), "normal")
        opacity = float(op.params.get("opacity", 100)) / 100.0
        return [
            f"    new_layer = doc.createNode('{name}', 'paintlayer')",
            f"    new_layer.setBlendingMode('{blend}')",
            f"    new_layer.setOpacity({opacity:.2f})",
            "    doc.rootNode().addChildNode(new_layer, None)",
            "    doc.setActiveNode(new_layer)",
        ]

    def _op_layer_duplicate(self, op: Operation) -> list[str]:
        name = op.params.get("name", "Copy")
        return [
            "    source = doc.activeNode()",
            "    copy = source.duplicate()",
            f"    copy.setName('{name}')",
            "    source.parentNode().addChildNode(copy, source)",
            "    doc.setActiveNode(copy)",
        ]

    def _op_layer_set_opacity(self, op: Operation) -> list[str]:
        opacity = float(op.params.get("opacity", 100)) / 100.0
        return [f"    node.setOpacity({opacity:.2f})"]

    def _op_layer_set_blend_mode(self, op: Operation) -> list[str]:
        blend = BLEND_MODES.get(str(op.params.get("mode", "normal")).lower(), "normal")
        return [f"    node.setBlendingMode('{blend}')"]

    def _op_layer_set_visible(self, op: Operation) -> list[str]:
        visible = "True" if op.params.get("visible", True) else "False"
        return [f"    node.setVisible({visible})"]

    # ---------------------------------------------------------------- selections

    def _op_selection_all(self, op: Operation) -> list[str]:
        return ["    doc.selection().selectAll()"]

    def _op_selection_none(self, op: Operation) -> list[str]:
        return ["    doc.selection().clear()"]

    def _op_selection_invert(self, op: Operation) -> list[str]:
        return ["    doc.selection().invert()"]

    # ------------------------------------------------------------- color & tone

    def _apply_filter(self, filter_name: str, props: dict[str, float], bounds: str) -> list[str]:
        lines = [
            f"    filter = app.filters()['{filter_name}']",
            "    info = filter.configuration()",
        ]
        for key, value in props.items():
            lines.append(f"    info.setProperty('{key}', {value})")
        lines.append(f"    filter.apply(node, info, 0, 0, {bounds})")
        return lines

    def _node_bounds(self) -> str:
        return "node.bounds().width(), node.bounds().height()"

    def _op_colors_brightness_contrast(self, op: Operation) -> list[str]:
        return self._apply_filter(
            "brightness/contrast adjustment",
            {
                "brightness": float(op.params.get("brightness", 0)),
                "contrast": float(op.params.get("contrast", 0)),
            },
            self._node_bounds(),
        )

    def _op_colors_desaturate(self, op: Operation) -> list[str]:
        mode = {"luminosity": 0, "average": 1, "lightness": 2}.get(
            str(op.params.get("mode", "luminosity")).lower(), 0
        )
        return self._apply_filter("desaturate", {"type": mode}, self._node_bounds())

    def _op_colors_hue_saturation(self, op: Operation) -> list[str]:
        return self._apply_filter(
            "hsv adjustment",
            {
                "hue": float(op.params.get("hue", 0)) / 180.0,
                "saturation": float(op.params.get("saturation", 0)) / 100.0,
                "value": float(op.params.get("lightness", 0)) / 100.0,
            },
            self._node_bounds(),
        )

    # ------------------------------------------------------------------ filters

    def _op_filter_gaussian_blur(self, op: Operation) -> list[str]:
        radius = float(op.params.get("radius", 5))
        return self._apply_filter(
            "gaussian blur",
            {"horizRadius": radius, "vertRadius": radius},
            self._node_bounds(),
        )

    def _op_filter_unsharp_mask(self, op: Operation) -> list[str]:
        return self._apply_filter(
            "unsharp mask",
            {
                "amount": float(op.params.get("amount", 0.5)),
                "radius": float(op.params.get("radius", 2.0)),
                "threshold": float(op.params.get("threshold", 0)),
            },
            self._node_bounds(),
        )

    # ---------------------------------------------------------------- transform

    def _op_transform_scale(self, op: Operation) -> list[str]:
        width = int(op.params.get("width", 800))
        height = int(op.params.get("height", 600))
        return [f"    doc.scaleImage({width}, {height}, 1)"]

    def _op_transform_flip(self, op: Operation) -> list[str]:
        # Krita has no direct scripted flip; rotate 180 is a poor substitute, so
        # note the limitation instead of silently doing the wrong thing.
        return [
            (
                "    # Krita's Python API has no direct flip call - flip via "
                "Transform mask or perform in the UI."
            ),
        ]

    def _op_transform_rotate(self, op: Operation) -> list[str]:
        degrees = float(op.params.get("degrees", 90))
        return [f"    doc.rotateImage({degrees})"]

    # ------------------------------------------------------------------ editing

    def _op_edit_fill(self, op: Operation) -> list[str]:
        color = op.params.get("color", [255, 255, 255])
        r, g, b = [int(c) for c in color[:3]]
        return [
            "    # Krita's scripting API has no direct 'fill drawable' call. Create a",
            "    # paint layer and fill it by setting pixels (BGRA byte order):",
            "    fill_layer = doc.createNode('Fill', 'paintlayer')",
            "    doc.rootNode().addChildNode(fill_layer, None)",
            "    doc.setActiveNode(fill_layer)",
            "    bounds = fill_layer.bounds()",
            f"    rgba = bytes([{b}, {g}, {r}, 255])  # BGRA byte order",
            (
                "    fill_layer.setPixelData(rgba * (bounds.width() * bounds.height()), "
                "bounds.x(), bounds.y(), bounds.width(), bounds.height())"
            ),
        ]

    # -------------------------------------------------------------------- image

    def _op_image_flatten(self, op: Operation) -> list[str]:
        return ["    doc.rootNode().mergeAllVisibleLayers()"]

    def _op_image_duplicate(self, op: Operation) -> list[str]:
        return ["    duplicate = doc.duplicate()"]

    def _op_export(self, op: Operation) -> list[str]:
        path = op.params.get("path", "output.png")
        return [f"    doc.exportImage('{path}', Krita.instance().createInfoObject())"]
