"""Mask exporter — per-object silhouette masks for the technique executor.

For every object that has ANY enhancement field set (surface, shading, or
outline), this module renders an isolated binary mask PNG at the same
canvas dimensions as base.png.

Each mask is:
  - Grayscale ('L' mode), same width × height as the canvas
  - 255 (white) inside the object's silhouette
  - 0 (black) everywhere else

The masks and base.png share the exact same coordinate system — they are
rendered from the same normalised fractions, so they align pixel-for-pixel
without any separate scaling step.

Usage::

    from pixelpilot.technique.mask_export import export_masks, needs_technique_pass

    masks = export_masks(plan, canvas_w=800, canvas_h=600)
    # masks: dict[str, bytes]   object_id -> PNG bytes
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from pixelpilot.generation.schema import ImagePlan, ShapeObject, ShapeType


def needs_technique_pass(plan: ImagePlan) -> bool:
    """Return True if any object in *plan* requires a technique (surface/shading/outline)."""
    return any(
        obj.surface is not None or obj.shading is not None or obj.outline is not None
        for obj in plan.objects
    )


def export_masks(
    plan: ImagePlan,
    canvas_w: int,
    canvas_h: int,
    output_dir: Path | None = None,
) -> dict[str, bytes]:
    """Render per-object silhouette masks for objects that need the technique pass.

    Args:
        plan: The resolved ImagePlan.
        canvas_w: Canvas pixel width (must match the base.png).
        canvas_h: Canvas pixel height (must match the base.png).
        output_dir: If given, also write ``mask_{object_id}.png`` files here.

    Returns:
        Dict mapping object IDs to grayscale mask PNG bytes.
        Only includes objects that have at least one enhancement field set.
    """
    masks: dict[str, bytes] = {}

    for obj in plan.sorted_objects():
        if obj.surface is None and obj.shading is None and obj.outline is None:
            # Also support legacy fill=textured so old plans still work
            if not (hasattr(obj, "fill") and str(obj.fill) == "textured"):
                continue

        mask_img = _render_object_mask(obj, canvas_w, canvas_h)
        buf = io.BytesIO()
        mask_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        masks[obj.id] = png_bytes

        if output_dir is not None:
            (output_dir / f"mask_{obj.id}.png").write_bytes(png_bytes)

    return masks


def _render_object_mask(obj: ShapeObject, w: int, h: int) -> Image.Image:
    """Return a grayscale silhouette mask for a single shape."""
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    _draw_shape(draw, obj, w, h, fill=255)
    return mask


def _draw_shape(
    draw: ImageDraw.ImageDraw,
    obj: ShapeObject,
    w: int,
    h: int,
    fill: int,
) -> None:
    if obj.type == ShapeType.RECT:
        x0 = round(obj.x * w)           # type: ignore[operator]
        y0 = round(obj.y * h)           # type: ignore[operator]
        x1 = x0 + max(1, round(obj.width * w))   # type: ignore[operator]
        y1 = y0 + max(1, round(obj.height * h))  # type: ignore[operator]
        draw.rectangle([x0, y0, x1, y1], fill=fill)

    elif obj.type == ShapeType.CIRCLE:
        cx = round(obj.cx * w)   # type: ignore[operator]
        cy = round(obj.cy * h)   # type: ignore[operator]
        r = max(1, round(obj.radius * w))  # type: ignore[operator]
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)

    elif obj.type == ShapeType.ELLIPSE:
        cx = round(obj.cx * w)   # type: ignore[operator]
        cy = round(obj.cy * h)   # type: ignore[operator]
        rx = max(1, round(obj.rx * w))  # type: ignore[operator]
        ry = max(1, round(obj.ry * h))  # type: ignore[operator]
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill)

    elif obj.type == ShapeType.POLYGON:
        pts = [
            (round(p[0] * w), round(p[1] * h))
            for p in (obj.points or [])
        ]
        if len(pts) >= 3:
            draw.polygon(pts, fill=fill)

    elif obj.type == ShapeType.LINE:
        x1 = round(obj.x1 * w)  # type: ignore[operator]
        y1 = round(obj.y1 * h)  # type: ignore[operator]
        x2 = round(obj.x2 * w)  # type: ignore[operator]
        y2 = round(obj.y2 * h)  # type: ignore[operator]
        sw = max(1, round(obj.stroke_width * w))
        draw.line([(x1, y1), (x2, y2)], fill=fill, width=sw)
