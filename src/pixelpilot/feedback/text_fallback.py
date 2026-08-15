"""Text-only canvas analysis fallback (implementation_plan.md §4.5.2).

For systems without VRAM for a vision model: build a compact text description of the
result from canvas state and pixel statistics, then hand it to the code model.
"""

from __future__ import annotations

from pixelpilot.bridge.state import CanvasState
from pixelpilot.feedback.screenshot import analyze_pixels


class TextFallbackAnalyzer:
    """Describe the post-edit canvas as text for the code model."""

    def describe(
        self,
        canvas_state: CanvasState,
        screenshot_bytes: bytes | None = None,
        changes: str = "",
    ) -> str:
        parts: list[str] = []
        if screenshot_bytes:
            stats = analyze_pixels(screenshot_bytes)
            if stats:
                parts.append(
                    f"Canvas {stats['size'][0]}x{stats['size'][1]}: "
                    f"mean brightness {stats['mean_brightness']} "
                    f"(dark {stats['dark_pct']}%, light {stats['light_pct']}%)."
                )
        if canvas_state and not canvas_state.is_empty():
            parts.append(
                f"{len(canvas_state.layers)} layer(s); active layer "
                f"'{canvas_state.active_layer or '?'}'; "
                f"dimensions {canvas_state.dimensions}; mode {canvas_state.color_mode}; "
                f"{'selection active' if canvas_state.has_selection else 'no selection'}."
            )
        if changes:
            parts.append(f"Change summary: {changes}")
        return " ".join(parts) if parts else "No canvas information available."
