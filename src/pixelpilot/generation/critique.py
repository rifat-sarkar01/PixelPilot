"""Critique loop — render → critique → re-emit plan → repeat.

The loop runs up to ``max_rounds`` iterations.  Each iteration:
  1. Renders the current plan to PNG via PlanExecutor.
  2. Asks the CritiqueBackend to assess the PNG against the original request.
  3. If the critique says OK (or max rounds exhausted), returns the PNG.
  4. Otherwise asks the LLM to re-emit a corrected plan, validates it, and
     continues.

Re-emit strategy: full plan re-emission (not patch/diff) for v1 simplicity.
The critique issues are injected as natural language into the re-emit prompt.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from pixelpilot.generation.backends import CritiqueBackend, CritiqueResult
from pixelpilot.generation.executor import PlanExecutor
from pixelpilot.generation.schema import ImagePlan
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.prompts.generation import PLAN_EMIT_SYSTEM, REEMIT_USER

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class CritiqueLoop:
    """Run a render→critique→re-emit loop for image generation.

    Usage::

        loop = CritiqueLoop(
            executor=PlanExecutor(),
            critique_backend=LocalCritiqueBackend(client, model),
            plan_client=client,
            plan_model="pixelpilot-coder",
            max_rounds=2,
        )
        final_plan, png_bytes = loop.run(initial_plan, request="draw a red car")
    """

    def __init__(
        self,
        executor: PlanExecutor,
        critique_backend: CritiqueBackend,
        plan_client: OllamaClient,
        plan_model: str,
        max_rounds: int = 2,
        temperature: float = 0.3,
        think: bool = False,
        on_progress: "((str) -> None) | None" = None,
    ) -> None:
        self.executor = executor
        self.critique = critique_backend
        self.plan_client = plan_client
        self.plan_model = plan_model
        self.max_rounds = max_rounds
        self.temperature = temperature
        self.think = think
        self._on_progress = on_progress or (lambda msg: None)

    def run(self, plan: ImagePlan, request: str) -> tuple[ImagePlan, bytes]:
        """Run the critique loop.

        Returns:
            (final_plan, png_bytes) — the best plan found and its rendering.
        """
        current_plan = plan

        for round_num in range(self.max_rounds + 1):  # +1: always render at least once
            self._on_progress(f"Rendering (round {round_num})...")
            png_bytes = self.executor.render(current_plan)

            if round_num >= self.max_rounds:
                self._on_progress("Max critique rounds reached — using last render.")
                return current_plan, png_bytes

            self._on_progress("Critiquing render...")
            result = self.critique.analyze(png_bytes, request)

            if result.ok:
                self._on_progress("Critique: looks good.")
                return current_plan, png_bytes

            issues_text = "\n".join(f"- {i}" for i in result.issues)
            self._on_progress(
                f"Critique found {len(result.issues)} issue(s) "
                f"(round {round_num + 1}/{self.max_rounds}) — re-planning..."
            )

            corrected = self._reemit(request, current_plan, issues_text)
            if corrected is None:
                # Re-emit failed validation — keep current plan and stop
                self._on_progress("Re-emit produced invalid plan — keeping current render.")
                return current_plan, png_bytes

            current_plan = corrected

        # Should not reach here, but satisfy type checker
        return current_plan, self.executor.render(current_plan)

    # ------------------------------------------------------------------

    def _reemit(
        self, request: str, current_plan: ImagePlan, issues_text: str
    ) -> ImagePlan | None:
        """Ask the LLM to produce a corrected plan.

        Returns None if the model output cannot be parsed or validated.
        """
        user_msg = REEMIT_USER.format(
            request=request,
            issues=issues_text,
            current_plan=current_plan.to_json(indent=2),
        )
        messages = [
            {"role": "system", "content": PLAN_EMIT_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        try:
            response = self.plan_client.chat(
                self.plan_model,
                messages,
                stream=False,
                temperature=self.temperature,
                think=self.think,
            )
            content: str = (response.get("message") or {}).get("content", "")
        except Exception as exc:  # noqa: BLE001
            self._on_progress(f"Re-emit model call failed: {exc}")
            return None

        return self._parse_plan(content, current_plan)

    def _parse_plan(self, content: str, fallback: ImagePlan) -> ImagePlan | None:
        """Parse a plan JSON from model output. Returns None on any failure."""
        stripped = re.sub(r"```(?:json)?\s*", "", content).strip()
        match = _JSON_RE.search(stripped)
        if not match:
            self._on_progress("Re-emit: no JSON object found in response.")
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            self._on_progress(f"Re-emit: JSON parse error: {exc}")
            return None
        try:
            plan = ImagePlan.from_dict(data)
            # Preserve canvas dimensions from the original plan
            plan.canvas.width = fallback.canvas.width
            plan.canvas.height = fallback.canvas.height
            return plan
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            self._on_progress(f"Re-emit: schema validation failed: {errors}")
            return None
