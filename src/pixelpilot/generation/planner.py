"""LLM-backed image plan generator.

Calls the Ollama code model with a structured prompt and parses the response
into a validated :class:`ImagePlan`.  All retry logic and fallback behaviour
is contained here — callers receive either an ``ImagePlan`` or a clear error.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from pixelpilot.generation.schema import ImagePlan
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.prompts.generation import PLAN_EMIT_SYSTEM, PLAN_EMIT_USER

# Matches the outermost {...} block in LLM output (handles markdown fences)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

# Default canvas when the user gives no size hint
DEFAULT_CANVAS_WIDTH = 800
DEFAULT_CANVAS_HEIGHT = 600


class PlannerError(RuntimeError):
    """Raised when the planner cannot produce a valid ImagePlan."""


class GenerationPlanner:
    """Ask the Ollama model to emit an :class:`ImagePlan` JSON.

    Usage::

        planner = GenerationPlanner(client, model="pixelpilot-coder")
        plan = planner.plan("draw a red car")
    """

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        max_retries: int = 3,
        temperature: float = 0.3,
        think: bool = False,
    ) -> None:
        self.client = client
        self.model = model
        self.max_retries = max_retries
        self.temperature = temperature
        self.think = think

    def plan(
        self,
        request: str,
        width: int = DEFAULT_CANVAS_WIDTH,
        height: int = DEFAULT_CANVAS_HEIGHT,
    ) -> ImagePlan:
        """Generate an :class:`ImagePlan` for *request*.

        Retries up to ``max_retries`` times if the model returns invalid JSON
        or a plan that fails Pydantic validation.

        Raises:
            PlannerError: if all attempts fail.
        """
        user_msg = PLAN_EMIT_USER.format(request=request, width=width, height=height)
        messages = [
            {"role": "system", "content": PLAN_EMIT_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        last_error: str = "unknown"
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat(
                    self.model,
                    messages,
                    stream=False,
                    temperature=self.temperature,
                    think=self.think,
                )
                content: str = (response.get("message") or {}).get("content", "")
            except Exception as exc:
                raise PlannerError(f"Ollama call failed: {exc}") from exc

            plan, error = self._parse(content)
            if plan is not None:
                # Ensure canvas matches requested size
                plan.canvas.width = width
                plan.canvas.height = height
                return plan

            last_error = error
            # Feed the error back so the model can self-correct
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    f"Your response could not be parsed: {error}\n"
                    "Output ONLY valid JSON matching the ImagePlan schema. "
                    "No markdown fences, no prose — just the JSON object."
                ),
            })

        raise PlannerError(
            f"Model did not produce a valid ImagePlan after {self.max_retries} "
            f"attempts. Last error: {last_error}"
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _parse(content: str) -> tuple[ImagePlan | None, str]:
        """Try to extract and validate an ImagePlan from raw model output.

        Returns ``(plan, "")`` on success or ``(None, error_message)`` on failure.
        """
        # Strip markdown fences if present (```json ... ```)
        stripped = re.sub(r"```(?:json)?\s*", "", content).strip()

        # Find the outermost JSON object
        match = _JSON_BLOCK_RE.search(stripped)
        if not match:
            return None, "No JSON object found in response"

        json_text = match.group(0)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            return None, f"JSON parse error: {exc}"

        try:
            plan = ImagePlan.from_dict(data)
        except ValidationError as exc:
            # Summarise validation errors concisely
            errors = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            return None, f"Schema validation failed: {errors}"

        return plan, ""
