"""GIMP batch texture application (headless).

Invokes GIMP in batch mode to apply texture presets to masked regions of
a rendered PNG.  Each textured object gets its own mask and filter pass.

Falls back gracefully if GIMP is not available — returns the un-textured
base PNG so the pipeline is never blocked by a missing GIMP install.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from pixelpilot.generation.schema import ImagePlan, TextureName
from pixelpilot.texture.mask_export import export_masks, has_textured_objects
from pixelpilot.texture.presets import get_recipe

_log = logging.getLogger(__name__)


class GIMPNotAvailable(RuntimeError):
    """Raised when GIMP cannot be found on the system."""


def find_gimp_binary() -> str | None:
    """Locate the GIMP executable. Returns None if not found."""
    # Common GIMP binary names
    candidates = ["gimp", "gimp-2.10", "gimp-3.0", "gimp.exe"]

    # Check PATH
    for name in candidates:
        path = shutil.which(name)
        if path is not None:
            return path

    # Windows: common install locations
    if __import__("sys").platform == "win32":
        for prog in [
            r"C:\Program Files\GIMP 3\bin\gimp-3.0.exe",
            r"C:\Program Files\GIMP 2\bin\gimp-2.10.exe",
            r"C:\Program Files (x86)\GIMP 2\bin\gimp-2.10.exe",
        ]:
            if Path(prog).exists():
                return prog

    return None


def apply_textures(
    base_png: bytes,
    plan: ImagePlan,
    gimp_binary: str | None = None,
) -> bytes:
    """Apply texture presets to textured objects in the plan.

    Args:
        base_png: The base-rendered PNG bytes (flat shapes, no textures).
        plan: The ImagePlan with texture metadata.
        gimp_binary: Path to GIMP binary. Auto-detected if None.

    Returns:
        Textured PNG bytes.  If GIMP is unavailable or no textured objects
        exist, returns the original base_png unchanged.
    """
    if not has_textured_objects(plan):
        return base_png

    if gimp_binary is None:
        gimp_binary = find_gimp_binary()
    if gimp_binary is None:
        _log.warning("GIMP not found — skipping texture pass")
        return base_png

    with tempfile.TemporaryDirectory(prefix="pixelpilot_tex_") as tmpdir:
        tmp = Path(tmpdir)
        base_path = tmp / "base.png"
        base_path.write_bytes(base_png)

        # Export masks
        mask_dir = tmp / "masks"
        mask_dir.mkdir()
        masks = export_masks(base_png, plan, output_dir=mask_dir)

        # Apply textures via GIMP batch
        textured_ids = [
            obj.id for obj in plan.objects
            if obj.fill == "textured" and obj.id in masks
        ]
        for obj_id in textured_ids:
            obj = next(o for o in plan.objects if o.id == obj_id)
            texture_name: TextureName = obj.texture  # type: ignore[assignment]
            recipe = get_recipe(texture_name)
            mask_path = mask_dir / f"mask_{obj_id}.png"
            out_path = tmp / f"tex_{obj_id}.png"

            _apply_single_texture(
                gimp_binary=gimp_binary,
                image_path=base_path,
                mask_path=mask_path,
                out_path=out_path,
                recipe_script=recipe.script_template,
                obj_id=obj_id,
            )

            # Composite textured result back onto base
            if out_path.exists():
                _composite_texture(base_path, out_path, mask_path)
                # Update base for next pass
                base_path.write_bytes(base_path.read_bytes())

        return base_path.read_bytes()


def _apply_single_texture(
    gimp_binary: str,
    image_path: Path,
    mask_path: Path,
    out_path: Path,
    recipe_script: str,
    obj_id: str,
) -> None:
    """Run a single GIMP texture filter via batch Script-Fu."""
    # Build the Script-Fu command
    script = recipe_script.format(
        path=str(image_path).replace("\\", "/"),
        out=str(out_path).replace("\\", "/"),
        mask=str(mask_path).replace("\\", "/"),
    )

    # Wrap in a batch eval
    batch_cmd = f'(gimp-message "pixelpilot texture: {obj_id}")'

    cmd = [
        gimp_binary,
        "-i",  # No display
        "--batch-interpreter=procedure-eval",
        "-b", script,
        "-b", "(gimp-quit 0)",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            text=True,
        )
        if result.returncode != 0:
            _log.warning(
                "GIMP batch failed for object '%s': %s",
                obj_id,
                result.stderr[:500],
            )
    except FileNotFoundError:
        _log.warning("GIMP binary not found at %s", gimp_binary)
    except subprocess.TimeoutExpired:
        _log.warning("GIMP batch timed out for object '%s'", obj_id)


def _composite_texture(
    base_path: Path,
    textured_path: Path,
    mask_path: Path,
) -> None:
    """Composite the textured layer onto the base image using the mask."""
    try:
        from PIL import Image

        base = Image.open(base_path).convert("RGBA")
        textured = Image.open(textured_path).convert("RGBA")
        mask = Image.open(mask_path).convert("L")

        # Paste textured region onto base using mask
        base.paste(textured, (0, 0), mask)
        base.save(base_path, format="PNG")
    except Exception as exc:  # noqa: BLE001
        _log.warning("Texture compositing failed: %s", exc)
