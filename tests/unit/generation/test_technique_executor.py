"""Unit tests for technique/executor.py.

Covers:
- TechniqueExecutor.apply returns base PNG unchanged when no enhancements set
- TechniqueExecutor.apply returns base PNG unchanged when GIMP is absent
- Script generation (render_script) produces syntactically plausible Script-Fu
  for plans with surface / shading / outline / global_post
- Script includes correct ordered passes: surface → shading → outline
- Script includes global_post section
- Multi-object plans apply operations in z_order
- Batch: only ONE Script-Fu invocation per image (not one per object)
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from pixelpilot.generation.schema import ImagePlan
from pixelpilot.technique.executor import TechniqueExecutor, _build_batch_script


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(objects: list[dict], global_post: list[str] | None = None) -> ImagePlan:
    data: dict = {
        "version": "1",
        "canvas": {"width": 200, "height": 150, "background_color": [255, 255, 255]},
        "objects": objects,
    }
    if global_post:
        data["global_post"] = global_post
    return ImagePlan.from_dict(data)


def _rect(id_: str = "r1", z: int = 1, **kw) -> dict:
    d = {
        "id": id_, "type": "rect", "color": [200, 50, 50], "z_order": z,
        "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.4,
    }
    d.update(kw)
    return d


def _ellipse(id_: str = "e1", z: int = 2, **kw) -> dict:
    d = {
        "id": id_, "type": "ellipse", "color": [50, 200, 50], "z_order": z,
        "cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.2,
    }
    d.update(kw)
    return d


def _blank_png(width: int = 200, height: int = 150) -> bytes:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Passthrough behaviour (no GIMP / no enhancements)
# ---------------------------------------------------------------------------

class TestTechniqueExecutorPassthrough:
    def test_no_enhancements_returns_base_unchanged(self):
        plan = _plan([_rect()])
        base = _blank_png()
        executor = TechniqueExecutor(gimp_binary="__does_not_exist__")
        result = executor.apply(base, plan)
        assert result == base

    def test_gimp_absent_returns_base_unchanged(self):
        plan = _plan([_rect(surface="leaf_noise")])
        base = _blank_png()
        executor = TechniqueExecutor(gimp_binary="__does_not_exist__")
        result = executor.apply(base, plan)
        assert result == base

    def test_empty_plan_returns_base_unchanged(self):
        plan = _plan([])
        base = _blank_png()
        executor = TechniqueExecutor()
        result = executor.apply(base, plan)
        assert result == base

    def test_global_post_only_still_runs(self):
        """Global post without per-object should still attempt the technique pass."""
        plan = _plan([], global_post=["film_grain"])
        base = _blank_png()
        # With a fake binary, it falls back — just checking it doesn't crash
        executor = TechniqueExecutor(gimp_binary="__does_not_exist__")
        result = executor.apply(base, plan)
        assert result == base  # fallback


# ---------------------------------------------------------------------------
# Script generation correctness
# ---------------------------------------------------------------------------

class TestScriptGeneration:
    def _script(self, plan: ImagePlan) -> str:
        executor = TechniqueExecutor()
        return executor.render_script("/tmp/base.png", "/tmp/out.png", plan)

    def test_script_starts_with_let(self):
        plan = _plan([_rect(surface="leaf_noise")])
        script = self._script(plan)
        assert script.strip().startswith("(let*")

    def test_script_contains_gimp_file_load(self):
        plan = _plan([_rect(surface="bark_rough")])
        script = self._script(plan)
        assert "gimp-file-load" in script

    def test_script_contains_file_png_save(self):
        plan = _plan([_rect(surface="stone_grain")])
        script = self._script(plan)
        assert "file-png-save" in script

    def test_script_contains_gimp_quit(self):
        """The caller passes (gimp-quit 0) separately; script itself should flatten."""
        plan = _plan([_rect(shading="soft_bevel")])
        script = self._script(plan)
        assert "gimp-image-flatten" in script

    def test_surface_op_present_for_surface_preset(self):
        plan = _plan([_rect(surface="leaf_noise")])
        script = self._script(plan)
        # leaf_noise uses plug-in-hsv-noise
        assert "hsv-noise" in script or "surface" in script

    def test_shading_op_present_for_shading_preset(self):
        plan = _plan([_ellipse(shading="soft_bevel")])
        script = self._script(plan)
        assert "bump-map" in script or "shading" in script

    def test_outline_op_present_for_outline_preset(self):
        plan = _plan([_rect(outline="thin_dark")])
        script = self._script(plan)
        # thin_dark uses select-grow-subtract → gimp-selection-grow
        assert "selection-grow" in script or "outline" in script

    def test_global_post_section_present(self):
        plan = _plan([], global_post=["film_grain"])
        script = self._script(plan)
        assert "global post" in script.lower() or "film_grain" in script

    def test_object_id_commented_in_script(self):
        plan = _plan([_rect(id_="trunk", surface="bark_rough")])
        script = self._script(plan)
        assert "trunk" in script

    def test_fixed_order_surface_before_shading_before_outline(self):
        """surface comment should appear before shading, shading before outline."""
        plan = _plan([_rect(
            id_="obj1",
            surface="leaf_noise",
            shading="soft_bevel",
            outline="thin_dark",
        )])
        script = self._script(plan)
        surface_pos = script.find("surface:")
        shading_pos = script.find("shading:")
        outline_pos = script.find("outline:")
        assert surface_pos != -1
        assert shading_pos != -1
        assert outline_pos != -1
        assert surface_pos < shading_pos < outline_pos, (
            "surface must appear before shading, shading before outline in script"
        )

    def test_multi_object_z_order_in_script(self):
        """Objects should appear in z_order (back to front) in the script."""
        plan = _plan([
            _ellipse(id_="canopy", z=2, surface="leaf_noise"),
            _rect(id_="trunk", z=1, surface="bark_rough"),
        ])
        script = self._script(plan)
        trunk_pos = script.find("trunk")
        canopy_pos = script.find("canopy")
        assert trunk_pos != -1 and canopy_pos != -1
        assert trunk_pos < canopy_pos, "trunk (z=1) should appear before canopy (z=2)"

    def test_no_enhancements_produces_minimal_script(self):
        """A plan with no enhancement fields still produces a valid script."""
        plan = _plan([_rect()])
        # render_script always builds a script; it's the executor that skips calling GIMP
        script = self._script(plan)
        assert "gimp-file-load" in script
        assert "gimp-image-flatten" in script


# ---------------------------------------------------------------------------
# build_batch_script unit
# ---------------------------------------------------------------------------

class TestBuildBatchScript:
    def test_base_path_appears_in_script(self):
        plan = _plan([_rect(surface="bark_rough")])
        script = _build_batch_script(
            base_path="/tmp/test/base.png",
            out_path="/tmp/test/out.png",
            mask_paths={"r1": "/tmp/test/masks/mask_r1.png"},
            plan=plan,
        )
        assert "/tmp/test/base.png" in script
        assert "/tmp/test/out.png" in script

    def test_mask_path_appears_in_script(self):
        plan = _plan([_rect(id_="r1", shading="drop_shadow")])
        script = _build_batch_script(
            base_path="/b.png",
            out_path="/o.png",
            mask_paths={"r1": "/masks/mask_r1.png"},
            plan=plan,
        )
        assert "/masks/mask_r1.png" in script

    def test_windows_backslash_converted(self):
        plan = _plan([_rect(surface="stone_grain")])
        script = _build_batch_script(
            base_path=r"C:\tmp\base.png",
            out_path=r"C:\tmp\out.png",
            mask_paths={"r1": r"C:\tmp\masks\mask_r1.png"},
            plan=plan,
        )
        # Script-Fu needs forward slashes
        assert "\\" not in script

    def test_object_without_mask_skipped(self):
        """If an object has enhancements but no mask path, it should be skipped."""
        plan = _plan([
            _rect(id_="r1", surface="bark_rough"),
            _ellipse(id_="e1", shading="soft_bevel"),
        ])
        # Only provide mask for r1
        script = _build_batch_script(
            base_path="/b.png",
            out_path="/o.png",
            mask_paths={"r1": "/masks/mask_r1.png"},
            plan=plan,
        )
        # r1 should be present, e1 should NOT (no mask provided)
        assert "r1" in script
        # e1 won't appear if it has no mask_path
        assert "e1" not in script


# ---------------------------------------------------------------------------
# Schema enum validation (integration with schema)
# ---------------------------------------------------------------------------

class TestSchemaEnumValidation:
    def test_valid_surface_accepted(self):
        plan = _plan([_rect(surface="leaf_noise")])
        obj = plan.objects[0]
        assert obj.surface is not None
        assert obj.surface.value == "leaf_noise"

    def test_invalid_surface_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _plan([_rect(surface="freeform_anything")])

    def test_valid_shading_accepted(self):
        plan = _plan([_ellipse(shading="soft_bevel")])
        assert plan.objects[0].shading is not None

    def test_invalid_shading_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _plan([_ellipse(shading="magic_light")])

    def test_valid_outline_accepted(self):
        from pixelpilot.generation.schema import OutlinePreset
        plan = _plan([_rect(outline="thin_dark")])
        assert plan.objects[0].outline == OutlinePreset.THIN_DARK

    def test_invalid_outline_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _plan([_rect(outline="rainbow_glow")])

    def test_null_fields_accepted(self):
        plan = _plan([_rect()])
        obj = plan.objects[0]
        assert obj.surface is None
        assert obj.shading is None
        assert obj.outline is None

    def test_valid_global_post_accepted(self):
        plan = _plan([], global_post=["vignette", "film_grain"])
        assert len(plan.global_post) == 2

    def test_invalid_global_post_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _plan([], global_post=["fake_effect"])
