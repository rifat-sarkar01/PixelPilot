"""Golden-image tests — fixed plan JSON → render → pixel-diff against reference.

These tests catch executor regressions independent of the LLM. The reference
PNGs are generated on first run and stored in tests/fixtures/.

To regenerate references: delete the fixtures and re-run these tests.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from pixelpilot.generation.executor import PlanExecutor
from pixelpilot.generation.schema import ImagePlan

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Reference plans (deterministic, no LLM involved)
# ---------------------------------------------------------------------------

SIMPLE_RECT_PLAN = {
    "version": "1",
    "canvas": {"width": 200, "height": 200, "background_color": [255, 255, 255]},
    "objects": [
        {
            "id": "red_rect",
            "type": "rect",
            "color": [255, 0, 0],
            "z_order": 1,
            "x": 0.25,
            "y": 0.25,
            "width": 0.5,
            "height": 0.5,
        }
    ],
}

TWO_OBJECTS_PLAN = {
    "version": "1",
    "canvas": {"width": 200, "height": 200, "background_color": [200, 220, 255]},
    "objects": [
        {
            "id": "bg_circle",
            "type": "circle",
            "color": [0, 100, 200],
            "z_order": 1,
            "cx": 0.5,
            "cy": 0.5,
            "radius": 0.35,
        },
        {
            "id": "fg_rect",
            "type": "rect",
            "color": [255, 200, 0],
            "z_order": 2,
            "x": 0.3,
            "y": 0.3,
            "width": 0.4,
            "height": 0.4,
        },
    ],
}

Z_ORDER_PLAN = {
    "version": "1",
    "canvas": {"width": 100, "height": 100, "background_color": [0, 0, 0]},
    "objects": [
        {
            "id": "back",
            "type": "rect",
            "color": [255, 0, 0],
            "z_order": 1,
            "x": 0.1,
            "y": 0.1,
            "width": 0.8,
            "height": 0.8,
        },
        {
            "id": "front",
            "type": "rect",
            "color": [0, 255, 0],
            "z_order": 2,
            "x": 0.3,
            "y": 0.3,
            "width": 0.4,
            "height": 0.4,
        },
    ],
}

ELLIPSE_PLAN = {
    "version": "1",
    "canvas": {"width": 200, "height": 200, "background_color": [240, 240, 240]},
    "objects": [
        {
            "id": "ellipse1",
            "type": "ellipse",
            "color": [100, 50, 200],
            "z_order": 1,
            "cx": 0.5,
            "cy": 0.5,
            "rx": 0.4,
            "ry": 0.25,
        }
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_or_generate_reference(
    name: str, plan_dict: dict, executor: PlanExecutor
) -> Path:
    """Load the reference PNG if it exists, otherwise generate and save it."""
    ref_path = FIXTURES_DIR / f"golden_{name}.png"
    if not ref_path.exists():
        plan = ImagePlan.from_dict(plan_dict)
        png = executor.render(plan)
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        ref_path.write_bytes(png)
    return ref_path


def _pixel_diff(img_a_bytes: bytes, img_b_bytes: bytes) -> tuple[float, int]:
    """Compare two PNGs pixel-by-pixel.

    Returns:
        (match_ratio, total_pixels) — match_ratio is 0.0 (identical) to 1.0 (completely different).
    """
    img_a = Image.open(io.BytesIO(img_a_bytes)).convert("RGB")
    img_b = Image.open(io.BytesIO(img_b_bytes)).convert("RGB")

    if img_a.size != img_b.size:
        return 1.0, img_a.size[0] * img_a.size[1]

    pixels_a = list(img_a.getdata())
    pixels_b = list(img_b.getdata())
    total = len(pixels_a)
    diff_count = sum(1 for a, b in zip(pixels_a, pixels_b) if a != b)

    return diff_count / total if total > 0 else 0.0, total


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGoldenImages:
    """Pixel-diff tests against stored reference PNGs."""

    @pytest.fixture(autouse=True)
    def _executor(self) -> None:
        self.executor = PlanExecutor(prefer_cairosvg=False)  # Pillow for determinism

    def test_simple_rect_matches_reference(self) -> None:
        ref_path = _load_or_generate_reference("simple_rect", SIMPLE_RECT_PLAN, self.executor)
        plan = ImagePlan.from_dict(SIMPLE_RECT_PLAN)
        rendered = self.executor.render(plan)
        ref_bytes = ref_path.read_bytes()

        diff_ratio, total = _pixel_diff(rendered, ref_bytes)
        assert diff_ratio == 0.0, f"Pixel diff: {diff_ratio:.4%} of {total} pixels"

    def test_two_objects_matches_reference(self) -> None:
        ref_path = _load_or_generate_reference("two_objects", TWO_OBJECTS_PLAN, self.executor)
        plan = ImagePlan.from_dict(TWO_OBJECTS_PLAN)
        rendered = self.executor.render(plan)
        ref_bytes = ref_path.read_bytes()

        diff_ratio, total = _pixel_diff(rendered, ref_bytes)
        assert diff_ratio == 0.0, f"Pixel diff: {diff_ratio:.4%} of {total} pixels"

    def test_z_order_matches_reference(self) -> None:
        ref_path = _load_or_generate_reference("z_order", Z_ORDER_PLAN, self.executor)
        plan = ImagePlan.from_dict(Z_ORDER_PLAN)
        rendered = self.executor.render(plan)
        ref_bytes = ref_path.read_bytes()

        diff_ratio, total = _pixel_diff(rendered, ref_bytes)
        assert diff_ratio == 0.0, f"Pixel diff: {diff_ratio:.4%} of {total} pixels"

    def test_ellipse_matches_reference(self) -> None:
        ref_path = _load_or_generate_reference("ellipse", ELLIPSE_PLAN, self.executor)
        plan = ImagePlan.from_dict(ELLIPSE_PLAN)
        rendered = self.executor.render(plan)
        ref_bytes = ref_path.read_bytes()

        diff_ratio, total = _pixel_diff(rendered, ref_bytes)
        assert diff_ratio == 0.0, f"Pixel diff: {diff_ratio:.4%} of {total} pixels"

    def test_render_produces_valid_png(self) -> None:
        """All plans should produce valid PNG output."""
        for name, plan_dict in [
            ("simple_rect", SIMPLE_RECT_PLAN),
            ("two_objects", TWO_OBJECTS_PLAN),
            ("z_order", Z_ORDER_PLAN),
            ("ellipse", ELLIPSE_PLAN),
        ]:
            plan = ImagePlan.from_dict(plan_dict)
            png = self.executor.render(plan)
            assert png[:8] == b"\x89PNG\r\n\x1a\n", f"{name}: not a valid PNG"
            assert len(png) > 100, f"{name}: PNG too small"

    def test_canvas_dimensions_match(self) -> None:
        """Rendered PNG should match canvas dimensions."""
        for name, plan_dict in [
            ("simple_rect", SIMPLE_RECT_PLAN),
            ("two_objects", TWO_OBJECTS_PLAN),
        ]:
            plan = ImagePlan.from_dict(plan_dict)
            png = self.executor.render(plan)
            img = Image.open(io.BytesIO(png))
            assert img.size == (plan.canvas.width, plan.canvas.height), (
                f"{name}: expected {plan.canvas.width}x{plan.canvas.height}, got {img.size}"
            )
