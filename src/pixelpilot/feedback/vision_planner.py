"""Vision-first scene planning.

Until now, the vision model only ever saw a script's result *after* the code
model had already guessed at shapes, sizes, positions and colors - the vision
model's job was purely to critique and trigger a rewrite. That means every
mistake the code model could have avoided (wrong proportions, overlapping
elements, paired parts stacked on top of each other) had to be discovered by
trial, burning a round of the bounded rewrite budget.

This module moves vision earlier: before any code is generated, the vision
model is shown the user's request and a screenshot of the CURRENT canvas, and
asked to produce a concrete visual plan - what to draw, roughly how big, and
where, using the same composition-grid vocabulary the code model's system
prompt already teaches it (see prompts/gimp.py rule 15). The code model then
implements that plan instead of inventing one, and the post-execution vision
check becomes a final sanity pass rather than the primary way mistakes get
caught.
"""

from __future__ import annotations

import json
import re

from pixelpilot.feedback.screenshot import to_base64
from pixelpilot.ollama.client import OllamaClient

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

PLAN_PROMPT = """You are the visual-planning stage of an AI image editor. A user asked \
for the edit below, and the image attached is the CURRENT canvas, before any change is made.

User request: {request}

Canvas size: {width}x{height} pixels.

Write a concrete visual plan that a Python/GIMP coder can implement directly. Do NOT \
write GIMP API calls or code - describe the visual result only. For each distinct shape \
or element the request needs:
- what it is, and its approximate color as an RGB triple
- its size as a FRACTION of canvas width/height (e.g. "about 60% of width, 20% of height")
- its position using this grid (fractions of width x height, origin top-left, x right, y down):
    top-left, top-mid, top-right, mid-left, center, mid-right, bot-left, bot-mid, bot-right
- how it relates to what is already visible on the canvas (describe the existing canvas \
content briefly, and say where the new element should sit relative to it - if the canvas \
is blank, say so)

If the request implies two or more of the same part (wheels, eyes, windows, legs...), \
give each one an explicitly different grid position - never describe them with identical \
placement, since that draws them stacked on top of each other instead of side by side.

Respond with JSON only, no other text, no markdown fence:
{{"scene_description": "...", "elements": [{{"name": "...", "color_rgb": [0, 0, 0], \
"size_fraction": "...", "grid_position": "...", "notes": "..."}}]}}"""


class VisionPlanner:
    """Ask the vision model for a concrete visual plan before code generation.

    Degrades gracefully: any failure (vision disabled, no screenshot available,
    model unreachable, bad JSON) returns ``success=False`` with an empty plan
    rather than raising, so a request should never be blocked on this step -
    callers should just generate without a plan in that case, i.e. the old
    behavior is always the fallback.
    """

    def __init__(self, client: OllamaClient, model: str = "", enabled: bool = True) -> None:
        self.client = client
        self.model = model
        self.enabled = enabled and bool(model)

    def plan(
        self,
        request: str,
        screenshot_bytes: bytes | None,
        width: int | None = None,
        height: int | None = None,
        max_retries: int = 1,
    ) -> dict:
        """Return ``{"success": bool, "plan_text": str, "raw": str}``.

        ``plan_text`` is a plain-text rendering meant to be injected directly
        into the code model's prompt.
        """
        if not self.enabled or not screenshot_bytes:
            return {"success": False, "plan_text": "", "raw": ""}

        prompt = PLAN_PROMPT.format(
            request=request, width=width or "unknown", height=height or "unknown"
        )
        messages = [
            {"role": "user", "content": prompt, "images": [to_base64(screenshot_bytes)]}
        ]

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat(
                    self.model, messages, stream=False, temperature=0.3, timeout=600.0
                )
                content = (response.get("message") or {}).get("content", "")
                parsed = self._parse_json(content)
                if parsed is not None:
                    return {"success": True, "plan_text": self._render(parsed), "raw": content}
                if attempt < max_retries:
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user", "content": "That was not valid JSON. Respond with JSON only."}
                    )
            except Exception as exc:  # noqa: BLE001 - never block generation on this step
                return {"success": False, "plan_text": "", "raw": f"Vision planner error: {exc}"}
        return {"success": False, "plan_text": "", "raw": "Could not parse vision plan response."}

    @staticmethod
    def _render(parsed: dict) -> str:
        lines = []
        scene = parsed.get("scene_description")
        if scene:
            lines.append(f"Scene: {scene}")
        for el in parsed.get("elements", []) or []:
            if not isinstance(el, dict):
                continue
            name = el.get("name", "?")
            color = el.get("color_rgb", "")
            size = el.get("size_fraction", "")
            pos = el.get("grid_position", "")
            notes = el.get("notes", "")
            line = f"- {name}: color {color}, size {size}, position {pos}"
            if notes:
                line += f" ({notes})"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        match = _JSON_BLOCK_RE.search(content)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
