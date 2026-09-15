"""Vision-model analysis of editor screenshots (implementation_plan.md §4.5.1)."""

from __future__ import annotations

import json
import re

from pixelpilot.feedback.multimodal import known_image_input_rejection, rejected_image_input
from pixelpilot.feedback.screenshot import to_base64
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.prompts.system import SystemPromptBuilder

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class VisionAnalyzer:
    """Ask the Ollama vision model to evaluate a screenshot."""

    def __init__(self, client: OllamaClient, model: str = "", enabled: bool = True) -> None:
        self.client = client
        self.model = model
        self.enabled = enabled and bool(model)

    def analyze(
        self, screenshot_bytes: bytes, context: str | None = None, max_retries: int = 1
    ) -> dict:
        """Return a vision assessment without retrying capability failures."""
        if not self.enabled:
            return {
                "success": False,
                "assessment": "Vision feedback is disabled.",
                "fixes": [],
                "raw": "",
                "image_input_rejected": False,
            }
        unsupported_reason = known_image_input_rejection(self.model)
        if unsupported_reason:
            return {
                "success": False,
                "assessment": unsupported_reason,
                "fixes": [],
                "raw": "",
                "image_input_rejected": True,
            }
        builder = SystemPromptBuilder(editor="gimp", vision=True)
        messages = builder.build_vision_messages(to_base64(screenshot_bytes), context=context)

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat(
                    self.model, messages, stream=False, temperature=0.3, timeout=600.0
                )
                content = (response.get("message") or {}).get("content", "")
                parsed = self._parse_json(content)
                if parsed is not None:
                    return {
                        "success": bool(parsed.get("success", False)),
                        "assessment": parsed.get("assessment", ""),
                        "fixes": parsed.get("fixes", []),
                        "raw": content,
                    }
                if attempt < max_retries:
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user",
                         "content": "That was not valid JSON. Respond with JSON only."}
                    )
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                image_input_rejected = rejected_image_input(exc)
                return {
                    "success": False,
                    "assessment": f"Vision model error: {exc}",
                    "fixes": [],
                    "raw": "",
                    "image_input_rejected": image_input_rejected,
                }
        return {
            "success": False,
            "assessment": "Could not parse vision response.",
            "fixes": [],
            "raw": "",
            "image_input_rejected": False,
        }

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
