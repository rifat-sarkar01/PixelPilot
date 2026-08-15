"""Canvas capture and downscaling (implementation_plan.md §4.5.1)."""

from __future__ import annotations

import base64
import io

from pixelpilot.bridge.base import EditorBridge


def capture_png(bridge: EditorBridge) -> bytes:
    """Capture the current canvas as PNG bytes from the editor bridge."""
    return bridge.capture_screenshot()


def downscale_png(image_bytes: bytes, max_size: tuple[int, int] = (512, 384)) -> bytes:
    """Downscale an image to fit within ``max_size``, returning PNG bytes.

    Uses Pillow when available; otherwise returns the input unchanged.
    """
    try:
        from PIL import Image
    except ImportError:
        return image_bytes

    with Image.open(io.BytesIO(image_bytes)) as img:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()


def to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


def downscale_and_encode(
    image_bytes: bytes, max_size: tuple[int, int] = (512, 384)
) -> tuple[str, bytes]:
    """Return ``(base64_str, downscaled_bytes)`` for the vision model."""
    downscaled = downscale_png(image_bytes, max_size)
    return to_base64(downscaled), downscaled


def analyze_pixels(image_bytes: bytes) -> dict | None:
    """Compute lightweight histogram stats for text-only feedback.

    Returns ``None`` if Pillow is unavailable or the image can't be decoded.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            gray = img.convert("L")
            hist = gray.histogram()
            total = max(1, sum(hist))
            mean = sum(i * count for i, count in enumerate(hist)) / total
            dark = sum(hist[:85]) / total * 100
            light = sum(hist[170:]) / total * 100
            return {
                "mean_brightness": round(mean, 1),
                "dark_pct": round(dark, 1),
                "light_pct": round(light, 1),
                "size": list(img.size),
            }
    except Exception:  # noqa: BLE001 - analysis must never crash the pipeline
        return None
