"""Reliable, file-based GIMP execution for PixelPilot prompt edits.

GIMP 2.10's Python-Fu plug-ins run in a separate process.  Keeping one of
those plug-ins alive as a socket server starts GIMP in batch/no-interface
mode, so it cannot be the visible GIMP window.  This module instead runs a
short-lived headless edit against a known image file, then lets the regular
GIMP application open the exported result for the user.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from pixelpilot.bridge.launcher import find_gimp_binary


class GimpBatchError(RuntimeError):
    """GIMP could not apply or export a file-based edit."""


def _diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout).strip().replace("\n", " ")
    return text[:500] or f"GIMP exited with code {result.returncode}"


def apply_python_edit(
    input_path: Path,
    output_path: Path,
    code: str,
    *,
    gimp_binary: str | None = None,
    timeout: float = 120.0,
) -> Path:
    """Run *code* against *input_path* and export the result to *output_path*.

    The generated code is stored in a temporary Python file instead of being
    passed on the command line, avoiding Windows command-length limits.
    """
    if not input_path.is_file():
        raise GimpBatchError(f"Working image does not exist: {input_path}")

    binary = find_gimp_binary(gimp_binary)
    if binary is None:
        raise GimpBatchError("Could not find GIMP 2.10. Set editor.gimp.binary_path.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = output_path.as_posix()
    export_code = (
        "\n\n# PixelPilot export wrapper\n"
        "from gimpfu import *\n"
        "_pixelpilot_image = gimp.image_list()[0]\n"
        "_pixelpilot_drawable = _pixelpilot_image.active_drawable\n"
        f"pdb.gimp_file_save(_pixelpilot_image, _pixelpilot_drawable, {source_path!r}, {source_path!r})\n"
    )

    with tempfile.TemporaryDirectory(prefix="pixelpilot_gimp_edit_") as tmpdir:
        script_path = Path(tmpdir) / "operation.py"
        script_path.write_text(code + export_code, encoding="utf-8")
        script_ref = script_path.as_posix()
        # python-fu-eval evaluates this short expression in GIMP's Python 2
        # runtime; the actual generated script is compiled from the temp file.
        expression = f"exec(compile(open(r'{script_ref}').read(), r'{script_ref}', 'exec'))"
        cmd = [
            binary,
            "-i",
            str(input_path),
            "--batch-interpreter=python-fu-eval",
            "-b",
            expression,
            "-b",
            "(gimp-quit 0)",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise GimpBatchError(f"GIMP timed out after {timeout:.0f}s") from exc
        except OSError as exc:
            raise GimpBatchError(f"Could not start GIMP: {exc}") from exc

    if result.returncode != 0:
        raise GimpBatchError(_diagnostic(result))
    if not output_path.is_file():
        raise GimpBatchError("GIMP finished without exporting an image.")
    return output_path


def open_in_gimp(image_path: Path, *, gimp_binary: str | None = None) -> None:
    """Open an image in GIMP's normal, visible application window."""
    binary = find_gimp_binary(gimp_binary)
    if binary is None:
        raise GimpBatchError("Could not find GIMP 2.10. Set editor.gimp.binary_path.")

    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    subprocess.Popen([binary, str(image_path)], **kwargs)
