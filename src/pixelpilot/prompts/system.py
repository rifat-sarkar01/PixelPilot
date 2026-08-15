"""Layered system-prompt builder (implementation_plan.md §4.1.4).

Assembles the runtime context from five layers:
1. Core identity & rules (baked into the Modelfile at runtime - cost 0 tokens,
   but we still inject editor rules here for models used without the Modelfile).
2. Editor API reference - retrieved per query via RAG.
3. Current canvas state (compact JSON).
4. Conversation history (summarized).
5. Few-shot example (1-2, quality over quantity).
"""

from __future__ import annotations

import json

from pixelpilot.prompts import gimp as gimp_prompts
from pixelpilot.prompts import krita as krita_prompts
from pixelpilot.prompts.context import ContextBudget
from pixelpilot.prompts.templates import render

VALID_EDITORS = ("gimp", "krita")


class SystemPromptBuilder:
    """Build chat messages with enforced per-component token budgets."""

    def __init__(self, editor: str = "gimp", num_ctx: int = 8192, vision: bool = False) -> None:
        if editor not in VALID_EDITORS:
            raise ValueError(f"Unsupported editor: {editor!r} (expected one of {VALID_EDITORS})")
        self.editor = editor
        self.vision = vision
        self.budget = ContextBudget(num_ctx)

    # ------------------------------------------------------------ layer sources

    def editor_rules(self) -> str:
        if self.editor == "krita":
            return krita_prompts.build_system_rules()
        return gimp_prompts.build_system_rules()

    def format_procedures(self, procedures: list[dict] | None) -> str:
        if not procedures:
            return "(no specific procedures retrieved - rely on your knowledge)"
        lines = []
        for proc in procedures:
            name = proc.get("name", "?")
            sig = proc.get("signature") or proc.get("gimp3_signature") or ""
            desc = proc.get("description", "")
            entry = f"- {name}"
            if sig:
                entry += f" : {sig}"
            if desc:
                entry += f"  -- {desc}"
            lines.append(entry)
        return "\n".join(lines)

    def format_example(self, example: dict | None) -> str:
        if not example:
            return "(none)"
        prompt = example.get("prompt") or example.get("instruction", "")
        code = example.get("code") or example.get("script", "")
        parts = []
        if prompt:
            parts.append(f"User request: {prompt}")
        if code:
            parts.append(f"Correct script:\n```python\n{code}\n```")
        return "\n".join(parts)

    # ------------------------------------------------------------- composition

    def build_messages(
        self,
        user_text: str,
        canvas_state: dict | None = None,
        procedures: list[dict] | None = None,
        example: dict | None = None,
        history: list[dict] | None = None,
    ) -> list[dict]:
        system = self.build_system_prompt(
            canvas_state=canvas_state,
            procedures=procedures,
            example=example,
            history=history,
        )
        return [{"role": "system", "content": system},
                {"role": "user", "content": self.budget.fit("user_message", user_text)}]

    def build_system_prompt(
        self,
        canvas_state: dict | None = None,
        procedures: list[dict] | None = None,
        example: dict | None = None,
        history: list[dict] | None = None,
    ) -> str:
        canvas_json = json.dumps(canvas_state or {}, indent=2) if canvas_state else "{}"
        history_text = self.budget.summarize_history(
            history or [], self.budget.budgets["history"].max_tokens, self.budget.budgets["history"].max_tokens
        ) if history else "(new conversation)"

        injected = render(
            "base_chat.txt",
            canvas_state=self.budget.fit("canvas_state", canvas_json),
            procedures=self.budget.fit("api_reference", self.format_procedures(procedures)),
            example=self.budget.fit("examples", self.format_example(example)),
            history=history_text,
        )

        rules = self.budget.fit("system", self.editor_rules())
        return f"{rules}\n\n{injected}"

    # ------------------------------------------------------------- vision prompt

    def build_vision_messages(
        self, image_base64: str, context: str | None = None
    ) -> list[dict]:
        """Messages for the vision model given a base64-encoded screenshot."""
        content = (
            "Analyze this screenshot of an image editor canvas. "
            "Describe what the image currently looks like, whether the last editing "
            "operation achieved the intended result, and what specific adjustments "
            "would improve it. Respond with JSON only:\n"
            '{"success": true/false, "assessment": "...", "fixes": ["..."]}'
        )
        if context:
            content += f"\n\nContext from the last operation:\n{context}"
        return [{"role": "user", "content": content, "images": [image_base64]}]

    # ---------------------------------------------------------------- utilities

    def report_budget(self) -> dict[str, int]:
        return {name: c.max_tokens for name, c in self.budget.budgets.items()}
