"""Context window budget manager (implementation_plan.md §2.7).

Local models have small context windows. Every token must earn its place. This module
estimates token usage, enforces per-component budgets, truncates oversized content, and
compresses conversation history.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

# Rough heuristic: ~4 characters per token for code + English prose.
CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Estimate token count from character count (approximate, fast, dependency-free)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


_TRUNCATE_MARKER_START = "...[truncated]\n"
_TRUNCATE_MARKER_END = "\n...[truncated]"


def truncate_text(text: str, max_tokens: int, from_start: bool = False) -> str:
    """Truncate ``text`` to roughly ``max_tokens`` tokens.

    By default keeps the *tail* of the text (most recent/important content for prompts).
    Set ``from_start=True`` to keep the beginning instead. The truncation marker is
    accounted for so the result never exceeds ``max_tokens``.
    """
    if estimate_tokens(text) <= max_tokens:
        return text
    marker = _TRUNCATE_MARKER_START if from_start else _TRUNCATE_MARKER_END
    # Keep total (content + marker) within max_tokens using the chars-per-token heuristic.
    budget_chars = max(0, int(max_tokens * CHARS_PER_TOKEN) - len(marker))
    if from_start:
        return text[:budget_chars] + marker
    return marker + text[-budget_chars:]


@dataclass
class ComponentBudget:
    """Token budget for a single prompt component."""

    name: str
    max_tokens: int
    # Whether truncation should keep the beginning (True) or the end (False).
    keep_start: bool = False

    def fit(self, text: str) -> str:
        return truncate_text(text, self.max_tokens, from_start=self.keep_start)


class ContextBudget:
    """Per-model-scaling component budgets, per the §2.7 table.

    Defaults assume an 8K context window and scale proportionally for larger models.
    """

    CORE: ClassVar[dict[str, int]] = {
        "system": 500,
        "api_reference": 1500,
        "canvas_state": 200,
        "examples": 800,
        "history": 2000,
        "user_message": 200,
        "output": 2000,
    }

    def __init__(self, num_ctx: int = 8192) -> None:
        self.num_ctx = num_ctx
        self.budgets: dict[str, ComponentBudget] = {
            name: ComponentBudget(name=name, max_tokens=tokens)
            for name, tokens in self.CORE.items()
        }
        if num_ctx > 0:
            self._scale(num_ctx)

    def _scale(self, num_ctx: int) -> None:
        """Scale the default 8K budgets up (or down) for the model's context window."""
        reference = 8192
        factor = num_ctx / reference
        for comp in self.budgets.values():
            comp.max_tokens = max(50, int(comp.max_tokens * factor))

    def fit(self, component: str, text: str) -> str:
        comp = self.budgets.get(component)
        if comp is None:
            raise KeyError(f"Unknown context component: {component}")
        return comp.fit(text)

    def total_budget(self) -> int:
        return sum(c.max_tokens for c in self.budgets.values())

    def fits_within(self, component_tokens: dict[str, int]) -> bool:
        return all(
            tokens <= self.budgets[name].max_tokens
            for name, tokens in component_tokens.items()
        )

    # ------------------------------------------------------------------ history

    def summarize_history(self, history: list[dict], max_turns: int, max_tokens: int) -> str:
        """Collapse conversation history into a compact summary.

        Keeps the last ``max_turns`` verbatim and folds everything older into a short
        summary line - the "aggressive summarization" strategy from §2.7/§4.1.5.
        """
        if not history:
            return ""
        if len(history) <= max_turns * 2:
            return self._render_history(history, max_tokens)

        keep = history[-max_turns * 2 :]
        older = history[: -max_turns * 2]
        summary = self._summarize_older(older)
        rendered = self._render_history(keep, max_tokens)
        combined = f"[earlier conversation summary] {summary}\n\n{rendered}" if summary else rendered
        return truncate_text(combined, max_tokens, from_start=True)

    @staticmethod
    def _summarize_older(messages: list[dict]) -> str:
        user_requests = [
            m["content"].strip().replace("\n", " ")
            for m in messages
            if m.get("role") == "user" and m.get("content")
        ]
        if not user_requests:
            return ""
        snippet = " | ".join(user_requests)
        return f"User previously asked for: {truncate_text(snippet, 150, from_start=True)}"

    @staticmethod
    def _render_history(messages: list[dict], max_tokens: int) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        return truncate_text("\n".join(parts), max_tokens, from_start=True)
