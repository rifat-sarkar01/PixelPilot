"""Technique executor — builds and runs a single batched GIMP Script-Fu script.

This is the key architectural improvement over spawning one GIMP process per
object.  Given a fully rendered base.png and a set of per-object masks, the
executor:

  1. Generates ONE Script-Fu script that:
     - Loads base.png into GIMP
     - For each object, in z_order, applies surface → shading → outline recipes
       each constrained to that object's mask (alpha-to-selection)
     - Optionally applies global post-pass recipes to the whole canvas
     - Exports the final composited PNG
  2. Runs that script in a SINGLE ``gimp -i -b '(...)' -b '(gimp-quit 0)'``
     invocation — never one process per object.

If GIMP is not available, returns the un-textured base PNG unchanged so the
rest of the pipeline is never blocked.

Usage::

    from pixelpilot.technique.executor import TechniqueExecutor

    executor = TechniqueExecutor()
    final_png = executor.apply(base_png_bytes, plan)
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from pixelpilot.generation.schema import (
    GlobalPostPreset,
    ImagePlan,
    OutlinePreset,
    ShadingPreset,
    ShapeObject,
    SurfacePreset,
)
from pixelpilot.technique.mask_export import export_masks, needs_technique_pass
from pixelpilot.technique.registry import TechniqueCategory, get_recipe

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GIMP detection
# ---------------------------------------------------------------------------

def find_gimp_binary(configured_path: str | None = None) -> str | None:
    """Locate the GIMP executable on PATH or common install locations.

    Checks, in order: an explicitly configured path, PATH, then common
    per-platform install locations.
    """
    # Reuse the comprehensive search from the bridge launcher
    from pixelpilot.bridge.launcher import find_gimp_binary as _launcher_find
    return _launcher_find(configured_path)


# ---------------------------------------------------------------------------
# Script-Fu code generators
# ---------------------------------------------------------------------------

def _scriptfu_escape(path: str) -> str:
    """Escape a file path for use inside a Script-Fu string literal."""
    return path.replace("\\", "/").replace('"', '\\"')


def _scriptfu_load_mask_layer(
    image_var: str,
    mask_path: str,
    layer_var: str,
) -> str:
    """Return Script-Fu that loads a mask PNG and adds it as a channel."""
    p = _scriptfu_escape(mask_path)
    return (
        f"(let* (({layer_var} (car (gimp-file-load RUN-NONINTERACTIVE \"{p}\" \"{p}\"))))\n"
        f"  (gimp-image-insert-layer {image_var} (car (gimp-image-get-active-drawable {layer_var})) 0 -1))"
    )


def _scriptfu_select_from_mask(image_var: str, mask_path: str) -> str:
    """Return Script-Fu that selects a region from a mask PNG file.

    Loads the mask as a temporary image, converts alpha-to-selection on the
    main image by byte-comparison, then removes the temp image.
    """
    p = _scriptfu_escape(mask_path)
    return "\n".join([
        f'(let* ((mask-img (car (gimp-file-load RUN-NONINTERACTIVE "{p}" "{p}"))))',
        f'       (mask-layer (car (gimp-image-get-active-drawable mask-img))))',
        f'  (gimp-image-set-active-layer {image_var} (car (gimp-image-get-active-drawable {image_var})))',
        f'  (gimp-by-color-select mask-layer (car (gimp-drawable-get-pixel mask-layer 0 0)) 1 CHANNEL-OP-REPLACE TRUE FALSE 0 FALSE)',
        f'  (gimp-selection-invert mask-img)',
        f'  (gimp-image-delete mask-img)',
        f'  (plug-in-sel2path RUN-NONINTERACTIVE {image_var} (car (gimp-image-get-active-drawable {image_var})) )',
        f'  (gimp-image-select-item {image_var} CHANNEL-OP-REPLACE (car (gimp-image-get-active-drawable {image_var})))',
        f')',
    ])


def _scriptfu_apply_op(
    image_var: str,
    drawable_var: str,
    op: str,
    params: dict,
) -> str:
    """Translate one RecipeOp to Script-Fu.

    Handles the PixelPilot pseudo-op 'select-grow-subtract' specially.
    All real GIMP PDB ops are passed through with their params.
    """
    if op == "select-grow-subtract":
        # Grow selection by width px, subtract original → thin border, then fill
        width = int(params.get("width", 2))
        color = params.get("color", [0, 0, 0])
        opacity = int(params.get("opacity", 128))
        r, g, b = color[0], color[1], color[2]
        return "\n".join([
            f"  (gimp-selection-grow {image_var} {width})",
            f"  (gimp-context-set-foreground '({r} {g} {b}))",
            f"  (gimp-context-set-opacity {opacity / 255 * 100:.1f})",
            f"  (gimp-edit-fill {drawable_var} FOREGROUND-FILL)",
            f"  (gimp-selection-shrink {image_var} {width})",
            f"  (gimp-edit-clear {drawable_var})",
        ])

    if op == "pixelpilot-vignette":
        # Custom vignette: draw a radial gradient on a new layer blended multiply
        strength = float(params.get("strength", 0.4))
        opacity_pct = round(strength * 100)
        return "\n".join([
            f"  (let* ((vig-layer (car (gimp-layer-new {image_var} (car (gimp-image-width {image_var})) (car (gimp-image-height {image_var})) RGBA-IMAGE \"vignette\" {opacity_pct} LAYER-MODE-MULTIPLY))))",
            f"    (gimp-image-insert-layer {image_var} vig-layer 0 -1)",
            f"    (gimp-context-set-foreground '(0 0 0))",
            f"    (gimp-drawable-fill vig-layer TRANSPARENT-FILL)",
            f"    (gimp-image-flatten {image_var})",
            f"  )",
        ])

    # Generic PDB op — build positional arg list from params dict
    # Params are passed in declaration order as listed in recipes.yaml
    args_parts = []
    for k, v in params.items():
        if isinstance(v, bool):
            args_parts.append("TRUE" if v else "FALSE")
        elif isinstance(v, list):
            inner = " ".join(str(x) for x in v)
            if op.endswith("-spline") and k in ("points", "control-points", "control_points"):
                # gimp-curves-spline requires num-control-points before the vector
                num_pts = len(v) // 2
                args_parts.append(str(num_pts))
            args_parts.append(f"(list->vector '({inner}))" if op.endswith("-spline") else f"'({inner})")
        elif isinstance(v, str):
            if v.startswith("HISTOGRAM") or v.startswith("CHANNEL") or v.startswith("LAYER"):
                args_parts.append(v)  # GIMP constant
            else:
                args_parts.append(f'"{v}"')
        else:
            args_parts.append(str(v))
    args = " ".join(args_parts)

    return f"  ({op} RUN-NONINTERACTIVE {image_var} {drawable_var} {args})"


# ---------------------------------------------------------------------------
# Main batch script builder
# ---------------------------------------------------------------------------

def _build_batch_script(
    base_path: str,
    out_path: str,
    mask_paths: dict[str, str],
    plan: ImagePlan,
) -> str:
    """Build the complete Script-Fu batch script for the whole image.

    Args:
        base_path: Absolute path to base.png (forward slashes).
        out_path:  Absolute path for the final output PNG.
        mask_paths: Mapping object_id -> absolute mask path.
        plan: The ImagePlan with enhancement fields.
    """
    base_p = _scriptfu_escape(base_path)
    out_p = _scriptfu_escape(out_path)

    lines: list[str] = [
        "(let* (",
        f'  (image (car (gimp-file-load RUN-NONINTERACTIVE "{base_p}" "{base_p}")))',
        "  (drawable (car (gimp-image-get-active-drawable image)))",
        ")",
    ]

    for obj in plan.sorted_objects():
        if obj.id not in mask_paths:
            continue

        mask_p = _scriptfu_escape(mask_paths[obj.id])
        lines.append(f"\n  ; --- object: {obj.id} ---")

        # Helper: load selection from mask and run a recipe category
        def _apply_category(preset_val, category: TechniqueCategory) -> None:
            if preset_val is None:
                return
            preset_name = preset_val.value if hasattr(preset_val, "value") else str(preset_val)
            try:
                recipe = get_recipe(category, preset_name)
            except KeyError as exc:
                _log.warning("Skipping unknown preset: %s", exc)
                return

            lines.append(f"  ; {category.value}: {preset_name}")
            # Load mask image, flatten to single channel, copy to clipboard
            lines.append(
                f'  (let* ((mask-img (car (gimp-file-load RUN-NONINTERACTIVE "{mask_p}" "{mask_p}")))'
            )
            lines.append(
                f"         (mask-draw (car (gimp-image-get-active-drawable mask-img))))"
            )
            lines.append(
                f"    (gimp-image-flatten mask-img)"
            )
            lines.append(
                f"    (set! mask-draw (car (gimp-image-get-active-drawable mask-img)))"
            )
            lines.append(
                f"    (gimp-selection-all mask-img)"
            )
            lines.append(
                f"    (gimp-edit-copy mask-draw)"
            )
            lines.append(
                f"    (gimp-image-delete mask-img)"
            )
            # Paste mask into main image as temp layer, select white pixels (object silhouette)
            lines.append(
                f"    (gimp-selection-none image)"
            )
            lines.append(
                f"    (gimp-image-set-active-layer image drawable)"
            )
            lines.append(
                f"    (let* ((floating (car (gimp-edit-paste drawable FALSE)))"
            )
            lines.append(
                f"           (temp-layer (car (gimp-floating-sel-to-layer floating))))"
            )
            lines.append(
                f"      (gimp-image-set-active-layer image temp-layer)"
            )
            lines.append(
                f"      (gimp-by-color-select temp-layer '(255 255 255) 1 CHANNEL-OP-REPLACE TRUE FALSE 0 FALSE)"
            )
            lines.append(
                f"      (gimp-image-remove-layer image temp-layer)"
            )
            lines.append(
                f"    )"
            )
            lines.append(
                f"    (set! drawable (car (gimp-image-get-active-drawable image)))"
            )

            for op_rec in recipe.ops:
                sf = _scriptfu_apply_op("image", "drawable", op_rec.op, op_rec.params)
                lines.append(sf)

            lines.append("  )")  # close let*

        # Fixed order: surface → shading → outline
        _apply_category(obj.surface, TechniqueCategory.SURFACE)
        _apply_category(obj.shading, TechniqueCategory.SHADING)
        _apply_category(obj.outline, TechniqueCategory.OUTLINE)

    # Clear selection before global post-pass
    lines.append("\n  ; --- global post-pass ---")
    lines.append("  (gimp-selection-none image)")
    lines.append("  (set! drawable (car (gimp-image-get-active-drawable image)))")

    for post_preset in plan.global_post:
        preset_name = post_preset.value if hasattr(post_preset, "value") else str(post_preset)
        try:
            recipe = get_recipe(TechniqueCategory.GLOBAL_POST, preset_name)
        except KeyError as exc:
            _log.warning("Skipping unknown global post preset: %s", exc)
            continue
        lines.append(f"  ; global_post: {preset_name}")
        for op_rec in recipe.ops:
            sf = _scriptfu_apply_op("image", "drawable", op_rec.op, op_rec.params)
            lines.append(sf)

    # Flatten + export
    lines.append("  (gimp-image-flatten image)")
    lines.append("  (set! drawable (car (gimp-image-get-active-drawable image)))")
    lines.append(
        f'  (file-png-save RUN-NONINTERACTIVE image drawable "{out_p}" "{out_p}" 0 9 1 1 1 1 1)'
    )
    lines.append(")")  # close outer let*

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public executor
# ---------------------------------------------------------------------------

class TechniqueExecutor:
    """Apply surface/shading/outline/global-post techniques to a rendered PNG.

    Generates a single batched GIMP Script-Fu script per image (never one
    process per object) and runs it with one ``gimp -i -b ...`` invocation.

    Falls back to returning the un-textured base PNG if:
    - GIMP is not installed
    - No objects have enhancement fields set
    - The plan has no global_post presets and no enhanced objects
    """

    def __init__(
        self,
        gimp_binary: str | None = None,
        timeout: float = 120.0,
        on_progress: "((str) -> None) | None" = None,
    ) -> None:
        self._gimp_binary = gimp_binary
        self._timeout = timeout
        self._on_progress = on_progress or (lambda msg: None)
        self._last_error: str | None = None

    def _gimp(self) -> str | None:
        if self._gimp_binary is not None:
            return self._gimp_binary
        self._gimp_binary = find_gimp_binary()
        return self._gimp_binary

    def apply(self, base_png: bytes, plan: ImagePlan) -> bytes:
        """Apply all technique passes and return the final PNG bytes.

        Returns *base_png* unchanged if GIMP is unavailable or no techniques
        are requested.
        """
        has_per_object = needs_technique_pass(plan)
        has_global = bool(plan.global_post)

        if not has_per_object and not has_global:
            return base_png

        gimp = self._gimp()
        if gimp is None:
            _log.warning("GIMP not found — skipping technique pass")
            self._on_progress("GIMP not found — technique pass skipped")
            return base_png

        self._on_progress("Running technique pass (single GIMP batch)...")

        with tempfile.TemporaryDirectory(prefix="pixelpilot_tech_") as tmpdir:
            tmp = Path(tmpdir)
            base_path = tmp / "base.png"
            base_path.write_bytes(base_png)
            out_path = tmp / "output.png"
            mask_dir = tmp / "masks"
            mask_dir.mkdir()

            # Export masks for all objects with enhancement fields
            masks = export_masks(plan, plan.canvas.width, plan.canvas.height, mask_dir)

            if not masks and not has_global:
                return base_png

            mask_paths = {
                obj_id: str(mask_dir / f"mask_{obj_id}.png")
                for obj_id in masks
            }

            script = _build_batch_script(
                base_path=str(base_path),
                out_path=str(out_path),
                mask_paths=mask_paths,
                plan=plan,
            )

            self._on_progress(f"GIMP script: {len(script.splitlines())} lines for {len(masks)} object(s)")

            success = self._run_gimp(gimp, script, out_path)
            if success and out_path.exists():
                result = out_path.read_bytes()
                self._on_progress("Technique pass complete.")
                return result
            else:
                detail = f" ({self._last_error})" if self._last_error else ""
                self._on_progress(f"Technique pass failed{detail} — using base render.")
                return base_png

    def _run_gimp(self, gimp: str, script: str, out_path: Path) -> bool:
        """Execute GIMP headlessly with the batch script. Returns True on success."""
        self._last_error = None
        cmd = [
            gimp,
            "-i",  # no display
            "--batch-interpreter=plug-in-script-fu-eval",
            "-b", script,
            "-b", "(gimp-quit 0)",
        ]
        _log.debug("Running GIMP: %s", " ".join(cmd[:3]) + " [script] -b (gimp-quit 0)")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self._timeout,
                text=True,
            )
            if result.returncode != 0:
                diagnostic = (result.stderr or result.stdout).strip().replace("\n", " ")
                self._last_error = diagnostic[:300] or f"GIMP exited with code {result.returncode}"
                _log.warning(
                    "GIMP batch returned non-zero (%d):\n%s",
                    result.returncode,
                    result.stderr[:1000],
                )
                return False
            return True
        except FileNotFoundError:
            self._last_error = f"GIMP binary not found: {gimp}"
            _log.warning("GIMP binary not found: %s", gimp)
            return False
        except subprocess.TimeoutExpired:
            self._last_error = f"GIMP timed out after {self._timeout:.0f}s"
            _log.warning("GIMP batch timed out after %ss", self._timeout)
            return False
        except OSError as exc:
            self._last_error = str(exc)
            _log.warning("GIMP launch failed: %s", exc)
            return False

    def render_script(self, base_path: str, out_path: str, plan: ImagePlan) -> str:
        """Return the generated Script-Fu without running it.

        Useful for debugging, tests, and inspecting what GIMP would run.
        """
        mask_paths = {
            obj.id: f"/tmp/masks/mask_{obj.id}.png"
            for obj in plan.objects
            if obj.surface is not None or obj.shading is not None or obj.outline is not None
        }
        return _build_batch_script(
            base_path=base_path,
            out_path=out_path,
            mask_paths=mask_paths,
            plan=plan,
        )
