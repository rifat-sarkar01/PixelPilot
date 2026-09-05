"""Unit tests for generation/executor.py — PlanExecutor and SVG builder.

These tests verify:
- SVG output contains the correct elements and attributes.
- z_order is honoured (back-to-front rendering order in SVG).
- All 5 shape types produce valid output.
- PNG bytes are produced by at least one backend (Pillow).
- The executor degrades gracefully when cairosvg is absent.
"""

from __future__ import annotations

import io
import re

import pytest

from pixelpilot.generation.executor import PlanExecutor, _rgb_hex
from pixelpilot.generation.schema import ImagePlan


# ---------------------------------------------------------------------------
# Minimal plan builders
# ---------------------------------------------------------------------------

def _plan(objects: list[dict], width: int = 200, height: int = 150) -> ImagePlan:
    return ImagePlan.from_dict({
        "version": "1",
        "canvas": {"width": width, "height": height, "background_color": [255, 255, 255]},
        "objects": objects,
    })


def _rect(id_: str = "r1", z: int = 1, **kw) -> dict:
    d = {"id": id_, "type": "rect", "color": [200, 50, 50], "z_order": z,
         "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.4}
    d.update(kw)
    return d


def _circle(id_: str = "c1", z: int = 2) -> dict:
    return {"id": id_, "type": "circle", "color": [50, 200, 50], "z_order": z,
            "cx": 0.5, "cy": 0.5, "radius": 0.2}


def _ellipse(id_: str = "e1", z: int = 3) -> dict:
    return {"id": id_, "type": "ellipse", "color": [50, 50, 200], "z_order": z,
            "cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.15}


def _polygon(id_: str = "p1", z: int = 4) -> dict:
    return {"id": id_, "type": "polygon", "color": [200, 200, 0], "z_order": z,
            "points": [[0.1, 0.9], [0.5, 0.1], [0.9, 0.9]]}


def _line(id_: str = "l1", z: int = 5) -> dict:
    return {"id": id_, "type": "line", "color": [0, 0, 0], "z_order": z,
            "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0, "stroke_width": 0.01}


# ---------------------------------------------------------------------------
# Helper: Pillow-only executor (never tries cairosvg)
# ---------------------------------------------------------------------------

def _pillow_executor() -> PlanExecutor:
    ex = PlanExecutor(prefer_cairosvg=False)
    ex._cairosvg_available = False
    return ex


# ---------------------------------------------------------------------------
# SVG builder tests
# ---------------------------------------------------------------------------

class TestSVGBuilder:
    def _svg(self, plan: ImagePlan) -> str:
        return PlanExecutor().render_svg(plan)

    def test_svg_header(self):
        svg = self._svg(_plan([_rect()]))
        assert '<svg xmlns="http://www.w3.org/2000/svg"' in svg
        assert 'width="200"' in svg
        assert 'height="150"' in svg

    def test_background_rect_present(self):
        svg = self._svg(_plan([_rect()]))
        # Background is the first rect with x=0 y=0
        assert '<rect x="0" y="0" width="200" height="150"' in svg

    def test_rect_element(self):
        svg = self._svg(_plan([_rect()]))
        # x=0.1*200=20, y=0.1*150=15, w=0.5*200=100, h=0.4*150=60
        assert '<rect x="20" y="15" width="100" height="60"' in svg

    def test_circle_element(self):
        svg = self._svg(_plan([_circle()]))
        # cx=0.5*200=100, cy=0.5*150=75, r=0.2*200=40
        assert '<circle cx="100" cy="75" r="40"' in svg

    def test_ellipse_element(self):
        svg = self._svg(_plan([_ellipse()]))
        # cx=100, cy=75, rx=0.3*200=60, ry=0.15*150=22 (rounded)
        assert "<ellipse" in svg
        assert 'cx="100"' in svg
        assert 'cy="75"' in svg

    def test_polygon_element(self):
        svg = self._svg(_plan([_polygon()]))
        assert "<polygon" in svg
        assert "points=" in svg

    def test_line_element(self):
        svg = self._svg(_plan([_line()]))
        assert "<line" in svg
        assert 'stroke="' in svg

    def test_z_order_in_svg(self):
        """Lower z_order objects must appear earlier in the SVG (back-to-front)."""
        plan = _plan([_circle(z=10), _rect(z=1)])
        svg = self._svg(plan)
        rect_pos = svg.find("<rect x=")   # skip background rect
        # Find second <rect (the actual shape, not the background)
        rect_shape_pos = svg.find("<rect x=", svg.find("<rect x=") + 1)
        circle_pos = svg.find("<circle")
        assert rect_shape_pos < circle_pos, "rect (z=1) should appear before circle (z=10)"

    def test_color_hex(self):
        svg = self._svg(_plan([_rect(color=[200, 50, 50])]))
        assert "#c83232" in svg

    def test_opacity_in_svg(self):
        plan = _plan([_rect(opacity=0.5)])
        svg = self._svg(plan)
        assert 'fill-opacity="0.500"' in svg

    def test_all_shapes_in_one_plan(self):
        plan = _plan([_rect(), _circle(), _ellipse(), _polygon(), _line()])
        svg = self._svg(plan)
        for tag in ["<rect", "<circle", "<ellipse", "<polygon", "<line"]:
            assert tag in svg


# ---------------------------------------------------------------------------
# PNG rendering tests (Pillow fallback)
# ---------------------------------------------------------------------------

class TestPillow:
    """Tests that use the Pillow fallback renderer — no cairosvg required."""

    @pytest.fixture
    def executor(self):
        return _pillow_executor()

    def test_rect_produces_png(self, executor):
        plan = _plan([_rect()])
        png = executor.render(plan)
        assert png[:4] == b"\x89PNG"   # PNG magic bytes

    def test_circle_produces_png(self, executor):
        png = _pillow_executor().render(_plan([_circle()]))
        assert png[:4] == b"\x89PNG"

    def test_ellipse_produces_png(self, executor):
        png = _pillow_executor().render(_plan([_ellipse()]))
        assert png[:4] == b"\x89PNG"

    def test_polygon_produces_png(self, executor):
        png = _pillow_executor().render(_plan([_polygon()]))
        assert png[:4] == b"\x89PNG"

    def test_line_produces_png(self, executor):
        png = _pillow_executor().render(_plan([_line()]))
        assert png[:4] == b"\x89PNG"

    def test_canvas_size_respected(self, executor):
        """The rendered PNG should have the correct dimensions."""
        from PIL import Image
        plan = _plan([_rect()], width=320, height=240)
        png = executor.render(plan)
        img = Image.open(io.BytesIO(png))
        assert img.size == (320, 240)

    def test_background_color_applied(self, executor):
        """Top-left pixel should match the background colour."""
        from PIL import Image
        plan = _plan([], width=50, height=50)
        plan.canvas.background_color = [10, 20, 30]
        png = executor.render(plan)
        img = Image.open(io.BytesIO(png)).convert("RGB")
        assert img.getpixel((0, 0)) == (10, 20, 30)

    def test_empty_objects_renders_blank(self, executor):
        plan = _plan([])
        png = executor.render(plan)
        assert len(png) > 0
        assert png[:4] == b"\x89PNG"

    def test_multiple_objects(self, executor):
        plan = _plan([_rect(id_="r1", z=1), _circle(id_="c1", z=2)])
        png = executor.render(plan)
        assert png[:4] == b"\x89PNG"

    def test_out_of_range_coords_clamped(self, executor):
        """Clamped coordinates should not crash the renderer."""
        plan = _plan([_rect(x=0.9, y=0.9, width=0.5, height=0.5)])
        png = executor.render(plan)
        assert png[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# _rgb_hex utility
# ---------------------------------------------------------------------------

class TestRgbHex:
    def test_white(self):
        assert _rgb_hex([255, 255, 255]) == "#ffffff"

    def test_black(self):
        assert _rgb_hex([0, 0, 0]) == "#000000"

    def test_red(self):
        assert _rgb_hex([255, 0, 0]) == "#ff0000"

    def test_mixed(self):
        assert _rgb_hex([16, 32, 48]) == "#102030"
