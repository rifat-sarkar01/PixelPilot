"""Mask export — extract per-object alpha masks from a rendered PNG.

Given a base-rendered PNG and an ImagePlan, this module exports a separate
grayscale mask PNG for each object whose ``fill`` is ``textured``.  The mask
is a binary silhouette (white = object pixels, black = background) used by
the GIMP texture pass to constrain filter application to the object's area.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from pixelpilot.generation.schema import FillType, ImagePlan, ShapeObject, ShapeType


def export_masks(
    base_png: bytes,
    plan: ImagePlan,
    output_dir: Path | None = None,
) -> dict[str, bytes]:
    """Export per-object alpha masks for textured objects.

    Returns:
        A dict mapping object IDs to mask PNG bytes.  Only objects with
        ``fill=TEXTURED`` are included.
    """
    base_img = Image.open(io.BytesIO(base_png)).convert("RGBA")
    w, h = base_img.size
    masks: dict[str, bytes] = {}

    for obj in plan.sorted_objects():
        if obj.fill != FillType.TEXTURED:
            continue
        mask_img = _render_mask(obj, w, h)
        buf = io.BytesIO()
        mask_img.save(buf, format="PNG")
        masks[obj.id] = buf.getvalue()

        if output_dir is not None:
            out_path = output_dir / f"mask_{obj.id}.png"
            out_path.write_bytes(masks[obj.id])

    return masks


def _render_mask(obj: ShapeObject, w: int, h: int) -> Image.Image:
    """Render a binary mask for a single shape object."""
    mask = Image.new("L", (w, h), 0)
    _draw_mask(mask, obj, w, h)
    return mask


def _draw_mask(mask: Image.Image, obj: ShapeObject, w: int, h: int) -> None:
    """Draw a shape's silhouette onto a grayscale mask image."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(mask)
    white = 255

    if obj.type == ShapeType.RECT:
        x0 = round(obj.x * w)  # type: ignore[operator]
        y0 = round(obj.y * h)  # type: ignore[operator]
        x1 = x0 + max(1, round(obj.width * w))  # type: ignore[operator]
        y1 = y0 + max(1, round(obj.height * h))  # type: ignore[operator]
        draw.rectangle([x0, y0, x1, y1], fill=white)

    elif obj.type == ShapeType.CIRCLE:
        cx = round(obj.cx * w)  # type: ignore[operator]
        cy = round(obj.cy * h)  # type: ignore[operator]
        r = max(1, round(obj.radius * w))  # type: ignore[operator]
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=white)

    elif obj.type == ShapeType.ELLIPSE:
        cx = round(obj.cx * w)  # type: ignore[operator]
        cy = round(obj.cy * h)  # type: ignore[operator]
        rx = max(1, round(obj.rx * w))  # type: ignore[operator]
        ry = max(1, round(obj.ry * h))  # type: ignore[operator]
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=white)

    elif obj.type == ShapeType.POLYGON:
        pts = [
            (round(p[0] * w), round(p[1] * h))
            for p in (obj.points or [])
        ]
        if len(pts) >= 3:
            draw.polygon(pts, fill=white)

    elif obj.type == ShapeType.LINE:
        x1 = round(obj.x1 * w)  # type: ignore[operator]
        y1 = round(obj.y1 * h)  # type: ignore[operator]
        x2 = round(obj.x2 * w)  # type: ignore[operator]
        y2 = round(obj.y2 * h)  # type: ignore[operator]
        sw = max(1, round(obj.stroke_width * w))
        draw.line([(x1, y1), (x2, y2)], fill=white, width=sw)


def has_textured_objects(plan: ImagePlan) -> bool:
    """Return True if any object in the plan uses textured fill."""
    return any(obj.fill == FillType.TEXTURED for obj in plan.objects)
