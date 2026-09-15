"""Unit tests for technique/mask_export.py.

Covers:
- needs_technique_pass returns True/False correctly
- export_masks returns masks only for objects with enhancement fields
- Mask dimensions match canvas exactly (pixel-perfect alignment check)
- Masks are binary (0 or 255) grayscale PNGs
- Object silhouettes are within expected bounding boxes
- Objects outside the mask boundary are untouched (bleed check)
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from pixelpilot.generation.schema import ImagePlan, ShapeObject, SurfacePreset
from pixelpilot.technique.mask_export import export_masks, needs_technique_pass


# ---------------------------------------------------------------------------
# Plan builder helpers
# ---------------------------------------------------------------------------

def _plan(objects: list[dict], width: int = 200, height: int = 150) -> ImagePlan:
    return ImagePlan.from_dict({
        "version": "1",
        "canvas": {"width": width, "height": height, "background_color": [255, 255, 255]},
        "objects": objects,
    })


def _rect_obj(id_: str = "r1", z: int = 1, surface: str | None = None, **kw) -> dict:
    d = {
        "id": id_, "type": "rect", "color": [200, 50, 50], "z_order": z,
        "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.4,
    }
    if surface is not None:
        d["surface"] = surface
    d.update(kw)
    return d


def _ellipse_obj(id_: str = "e1", z: int = 2, shading: str | None = None) -> dict:
    d = {
        "id": id_, "type": "ellipse", "color": [50, 200, 50], "z_order": z,
        "cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.2,
    }
    if shading is not None:
        d["shading"] = shading
    return d


def _circle_obj(id_: str = "c1", z: int = 1, outline: str | None = None) -> dict:
    d = {
        "id": id_, "type": "circle", "color": [100, 100, 200], "z_order": z,
        "cx": 0.5, "cy": 0.5, "radius": 0.2,
    }
    if outline is not None:
        d["outline"] = outline
    return d


def _open_mask(png_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes)).convert("L")


# ---------------------------------------------------------------------------
# needs_technique_pass
# ---------------------------------------------------------------------------

class TestNeedsTechniquePass:
    def test_no_enhancements_returns_false(self):
        plan = _plan([_rect_obj()])
        assert not needs_technique_pass(plan)

    def test_surface_set_returns_true(self):
        plan = _plan([_rect_obj(surface="leaf_noise")])
        assert needs_technique_pass(plan)

    def test_shading_set_returns_true(self):
        plan = _plan([_ellipse_obj(shading="soft_bevel")])
        assert needs_technique_pass(plan)

    def test_outline_set_returns_true(self):
        plan = _plan([_circle_obj(outline="thin_dark")])
        assert needs_technique_pass(plan)

    def test_mixed_plan_returns_true(self):
        # One enhanced, one plain
        plan = _plan([_rect_obj(), _ellipse_obj(shading="drop_shadow")])
        assert needs_technique_pass(plan)

    def test_empty_plan_returns_false(self):
        plan = _plan([])
        assert not needs_technique_pass(plan)


# ---------------------------------------------------------------------------
# export_masks — inclusion logic
# ---------------------------------------------------------------------------

class TestExportMasksInclusion:
    def test_no_enhanced_objects_returns_empty(self):
        plan = _plan([_rect_obj(), _ellipse_obj()])
        masks = export_masks(plan, 200, 150)
        assert masks == {}

    def test_only_enhanced_objects_included(self):
        plan = _plan([
            _rect_obj(id_="r1"),                       # no enhancements
            _ellipse_obj(id_="e1", shading="soft_bevel"),  # has shading
        ])
        masks = export_masks(plan, 200, 150)
        assert "r1" not in masks
        assert "e1" in masks

    def test_all_enhanced_objects_included(self):
        plan = _plan([
            _rect_obj(id_="r1", surface="bark_rough"),
            _circle_obj(id_="c1", outline="thin_dark"),
        ])
        masks = export_masks(plan, 200, 150)
        assert "r1" in masks
        assert "c1" in masks


# ---------------------------------------------------------------------------
# Mask properties
# ---------------------------------------------------------------------------

class TestMaskProperties:
    def test_mask_is_png(self):
        plan = _plan([_rect_obj(id_="r1", surface="leaf_noise")])
        masks = export_masks(plan, 200, 150)
        assert masks["r1"][:4] == b"\x89PNG"

    def test_mask_dimensions_match_canvas(self):
        W, H = 320, 240
        plan = _plan([_rect_obj(id_="r1", surface="leaf_noise")], width=W, height=H)
        masks = export_masks(plan, W, H)
        img = _open_mask(masks["r1"])
        assert img.size == (W, H)

    def test_mask_is_binary(self):
        """All pixels must be exactly 0 or 255."""
        plan = _plan([_ellipse_obj(id_="e1", shading="soft_bevel")], width=100, height=100)
        masks = export_masks(plan, 100, 100)
        img = _open_mask(masks["e1"])
        # pyrefly: ignore [bad-argument-type]
        pixels = set(img.getdata())
        assert pixels.issubset({0, 255}), f"Non-binary pixel values: {pixels - {0, 255}}"

    def test_rect_mask_has_white_interior(self):
        """For a rect at (0.1,0.1,0.5,0.4) on 200x150: center should be white."""
        plan = _plan([_rect_obj(id_="r1", surface="bark_rough")], width=200, height=150)
        masks = export_masks(plan, 200, 150)
        img = _open_mask(masks["r1"])
        # Center of the rect: x=0.35*200=70, y=0.30*150=45
        cx, cy = 70, 45
        assert img.getpixel((cx, cy)) == 255, "Center of rect should be white in mask"

    def test_outside_mask_boundary_is_black(self):
        """Pixels just outside the mask object must be 0 — no bleed."""
        plan = _plan([_rect_obj(id_="r1", surface="leaf_noise")], width=200, height=150)
        masks = export_masks(plan, 200, 150)
        img = _open_mask(masks["r1"])
        # Pixel at (1, 1) is outside the rect (which starts at x=0.1*200=20, y=0.1*150=15)
        assert img.getpixel((1, 1)) == 0, "Corner pixel should be black (outside object)"

    def test_ellipse_center_is_white(self):
        plan = _plan([_ellipse_obj(id_="e1", shading="inner_glow")], width=200, height=150)
        masks = export_masks(plan, 200, 150)
        img = _open_mask(masks["e1"])
        # Center: cx=0.5*200=100, cy=0.5*150=75
        assert img.getpixel((100, 75)) == 255

    def test_circle_center_is_white(self):
        plan = _plan([_circle_obj(id_="c1", outline="white_glow")], width=200, height=150)
        masks = export_masks(plan, 200, 150)
        img = _open_mask(masks["c1"])
        assert img.getpixel((100, 75)) == 255


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

class TestExportMasksFileOutput:
    def test_writes_to_output_dir(self, tmp_path):
        plan = _plan([_rect_obj(id_="r1", surface="stone_grain")], width=100, height=100)
        export_masks(plan, 100, 100, output_dir=tmp_path)
        expected = tmp_path / "mask_r1.png"
        assert expected.exists()
        assert expected.stat().st_size > 0

    def test_file_matches_returned_bytes(self, tmp_path):
        plan = _plan([_ellipse_obj(id_="e1", shading="drop_shadow")], width=100, height=100)
        masks = export_masks(plan, 100, 100, output_dir=tmp_path)
        written = (tmp_path / "mask_e1.png").read_bytes()
        assert written == masks["e1"]

    def test_multiple_objects_multiple_files(self, tmp_path):
        plan = _plan([
            _rect_obj(id_="r1", surface="wood_grain"),
            _circle_obj(id_="c1", outline="thin_dark"),
        ], width=100, height=100)
        export_masks(plan, 100, 100, output_dir=tmp_path)
        assert (tmp_path / "mask_r1.png").exists()
        assert (tmp_path / "mask_c1.png").exists()
