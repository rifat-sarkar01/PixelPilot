"""Deterministic plan executor — renders an ImagePlan to PNG bytes.

No LLM calls, no editor bridge. Given a validated ImagePlan, the executor:

  1. Sorts objects by z_order (back → front).
  2. Builds an SVG document from the normalised-fraction coordinates.
  3. Rasterizes the SVG to PNG bytes.

Rasterization backends (tried in order):
  1. cairosvg  — high quality, supports all SVG features (requires Cairo libs)
  2. Pillow     — pure-Python fallback, supports the v1 primitive set only

Either backend is sufficient for v1 (rect, circle, ellipse, polygon, line).
cairosvg is listed as an optional dependency in pyproject.toml.
"""

from __future__ import annotations

import io

from pixelpilot.generation.schema import ImagePlan, ShapeObject, ShapeType


# ---------------------------------------------------------------------------
# SVG builder
# ---------------------------------------------------------------------------

class _SVGBuilder:
    """Translates an ImagePlan into an SVG XML string."""

    def __init__(self, plan: ImagePlan) -> None:
        self.plan = plan
        self.w = plan.canvas.width
        self.h = plan.canvas.height

    def build(self) -> str:
        lines: list[str] = []
        w, h = self.w, self.h
        bg = self.plan.canvas.background_color
        bg_hex = _rgb_hex(bg)

        lines.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">'
        )
        # Background rect
        lines.append(
            f'  <rect x="0" y="0" width="{w}" height="{h}" fill="{bg_hex}"/>'
        )

        for obj in self.plan.sorted_objects():
            elem = self._shape(obj)
            if elem is not None:
                lines.append(f"  {elem}")

        lines.append("</svg>")
        return "\n".join(lines)

    # ------------------------------------------------------------------ shapes

    def _shape(self, obj: ShapeObject) -> str | None:
        w, h = self.w, self.h
        fill = _rgb_hex(obj.color)
        opacity = obj.opacity
        common = f'fill="{fill}" fill-opacity="{opacity:.3f}"'

        if obj.type == ShapeType.RECT:
            px = round(obj.x * w)          # type: ignore[operator]
            py = round(obj.y * h)          # type: ignore[operator]
            pw = max(1, round(obj.width * w))   # type: ignore[operator]
            ph = max(1, round(obj.height * h))  # type: ignore[operator]
            return f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" {common}/>'

        if obj.type == ShapeType.CIRCLE:
            cx = round(obj.cx * w)   # type: ignore[operator]
            cy = round(obj.cy * h)   # type: ignore[operator]
            r = max(1, round(obj.radius * w))  # type: ignore[operator]
            return f'<circle cx="{cx}" cy="{cy}" r="{r}" {common}/>'

        if obj.type == ShapeType.ELLIPSE:
            cx = round(obj.cx * w)   # type: ignore[operator]
            cy = round(obj.cy * h)   # type: ignore[operator]
            rx = max(1, round(obj.rx * w))  # type: ignore[operator]
            ry = max(1, round(obj.ry * h))  # type: ignore[operator]
            return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" {common}/>'

        if obj.type == ShapeType.POLYGON:
            pts = " ".join(
                f"{round(p[0] * w)},{round(p[1] * h)}"
                for p in (obj.points or [])
            )
            return f'<polygon points="{pts}" {common}/>'

        if obj.type == ShapeType.LINE:
            x1 = round(obj.x1 * w)  # type: ignore[operator]
            y1 = round(obj.y1 * h)  # type: ignore[operator]
            x2 = round(obj.x2 * w)  # type: ignore[operator]
            y2 = round(obj.y2 * h)  # type: ignore[operator]
            sw = max(1, round(obj.stroke_width * w))
            stroke = _rgb_hex(obj.color)
            return (
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{stroke}" stroke-opacity="{opacity:.3f}" '
                f'stroke-width="{sw}" fill="none"/>'
            )

        return None  # unknown type — silently skip


# ---------------------------------------------------------------------------
# Rasterization backends
# ---------------------------------------------------------------------------

def _rasterize_cairosvg(svg_bytes: bytes, width: int, height: int) -> bytes:
    import cairosvg  # type: ignore[import-untyped]

    return cairosvg.svg2png(
        bytestring=svg_bytes,
        output_width=width,
        output_height=height,
    )


def _rasterize_pillow(svg_string: str, plan: ImagePlan) -> bytes:
    """Pure-Pillow fallback: re-parse the plan and draw directly.

    This intentionally avoids parsing the SVG string (Pillow can't do that)
    and instead re-walks the plan. Limited to v1 primitives.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError(
            "Neither cairosvg nor Pillow is installed. "
            "Install at least one: pip install pillow"
        ) from exc

    w, h = plan.canvas.width, plan.canvas.height
    bg = (*plan.canvas.background_color, 255)  # RGBA background
    img = Image.new("RGBA", (w, h), bg)
    draw = ImageDraw.Draw(img)

    for obj in plan.sorted_objects():
        color_a = (*obj.color, round(obj.opacity * 255))  # type: ignore[arg-type]
        _pillow_shape(draw, obj, w, h, color_a)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pillow_shape(
    draw: "ImageDraw.ImageDraw",
    obj: ShapeObject,
    w: int,
    h: int,
    color: tuple[int, int, int, int],
) -> None:

    if obj.type == ShapeType.RECT:
        x0 = round(obj.x * w)           # type: ignore[operator]
        y0 = round(obj.y * h)           # type: ignore[operator]
        x1 = x0 + max(1, round(obj.width * w))   # type: ignore[operator]
        y1 = y0 + max(1, round(obj.height * h))  # type: ignore[operator]
        draw.rectangle([x0, y0, x1, y1], fill=color)

    elif obj.type == ShapeType.CIRCLE:
        cx = round(obj.cx * w)   # type: ignore[operator]
        cy = round(obj.cy * h)   # type: ignore[operator]
        r = max(1, round(obj.radius * w))  # type: ignore[operator]
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    elif obj.type == ShapeType.ELLIPSE:
        cx = round(obj.cx * w)   # type: ignore[operator]
        cy = round(obj.cy * h)   # type: ignore[operator]
        rx = max(1, round(obj.rx * w))  # type: ignore[operator]
        ry = max(1, round(obj.ry * h))  # type: ignore[operator]
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=color)

    elif obj.type == ShapeType.POLYGON:
        pts = [
            (round(p[0] * w), round(p[1] * h))
            for p in (obj.points or [])
        ]
        if len(pts) >= 3:
            draw.polygon(pts, fill=color)

    elif obj.type == ShapeType.LINE:
        x1 = round(obj.x1 * w)  # type: ignore[operator]
        y1 = round(obj.y1 * h)  # type: ignore[operator]
        x2 = round(obj.x2 * w)  # type: ignore[operator]
        y2 = round(obj.y2 * h)  # type: ignore[operator]
        sw = max(1, round(obj.stroke_width * w))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=sw)


# ---------------------------------------------------------------------------
# Public executor
# ---------------------------------------------------------------------------

class PlanExecutor:
    """Render an :class:`ImagePlan` to PNG bytes deterministically.

    Usage::

        executor = PlanExecutor()
        png_bytes = executor.render(plan)

    No editor bridge, no LLM calls, no side effects — pure in-memory rendering.
    """

    def __init__(self, prefer_cairosvg: bool = True) -> None:
        self._prefer_cairosvg = prefer_cairosvg
        self._cairosvg_available: bool | None = None  # cached after first probe

    def _has_cairosvg(self) -> bool:
        if self._cairosvg_available is None:
            try:
                import cairosvg  # type: ignore[import-untyped]  # noqa: F401
                self._cairosvg_available = True
            except ImportError:
                self._cairosvg_available = False
        return self._cairosvg_available

    def render(self, plan: ImagePlan) -> bytes:
        """Render *plan* and return PNG bytes.

        Tries cairosvg first (if available), falls back to Pillow.

        Raises:
            RuntimeError: if neither backend is available.
        """
        builder = _SVGBuilder(plan)
        svg_string = builder.build()
        svg_bytes = svg_string.encode("utf-8")

        if self._prefer_cairosvg and self._has_cairosvg():
            try:
                return _rasterize_cairosvg(svg_bytes, plan.canvas.width, plan.canvas.height)
            except Exception:
                # cairosvg present but failed (e.g. missing native libs on Windows)
                pass

        return _rasterize_pillow(svg_string, plan)

    def render_svg(self, plan: ImagePlan) -> str:
        """Return the SVG string without rasterizing (useful for tests / debugging)."""
        return _SVGBuilder(plan).build()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _rgb_hex(color: list[int]) -> str:
    """Convert [R, G, B] → '#rrggbb' hex string."""
    r, g, b = color[0], color[1], color[2]
    return f"#{r:02x}{g:02x}{b:02x}"
