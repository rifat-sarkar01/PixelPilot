"""Unit tests for the critique loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pixelpilot.generation.backends import CritiqueResult
from pixelpilot.generation.critique import CritiqueLoop
from pixelpilot.generation.executor import PlanExecutor
from pixelpilot.generation.schema import (
    CanvasSpec,
    ImagePlan,
    ShapeObject,
    ShapeType,
)
from pixelpilot.ollama.client import OllamaClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_plan() -> ImagePlan:
    return ImagePlan(
        canvas=CanvasSpec(width=100, height=100, background_color=[255, 255, 255]),
        objects=[
            ShapeObject(
                id="rect1",
                type=ShapeType.RECT,
                color=[255, 0, 0],
                z_order=1,
                x=0.1,
                y=0.1,
                width=0.8,
                height=0.8,
            )
        ],
    )


class FakeCritiqueBackend:
    """Test double that returns pre-configured results."""

    def __init__(self, results: list[CritiqueResult]) -> None:
        self._results = list(results)
        self._calls: list[tuple[bytes, str]] = []

    def analyze(self, image_png: bytes, request: str) -> CritiqueResult:
        self._calls.append((image_png, request))
        if self._results:
            return self._results.pop(0)
        return CritiqueResult.acceptable()


# ---------------------------------------------------------------------------
# CritiqueLoop tests
# ---------------------------------------------------------------------------

class TestCritiqueLoop:
    def test_returns_immediately_when_critique_ok(self) -> None:
        backend = FakeCritiqueBackend([CritiqueResult.acceptable()])
        executor = PlanExecutor()
        client = MagicMock(spec=OllamaClient)

        loop = CritiqueLoop(
            executor=executor,
            critique_backend=backend,  # type: ignore[arg-type]
            plan_client=client,
            plan_model="test",
            max_rounds=2,
        )

        plan = _simple_plan()
        final_plan, png = loop.run(plan, "draw a red square")

        assert final_plan is plan
        assert len(png) > 0
        assert len(backend._calls) == 1

    def test_reemit_on_critique_failure(self) -> None:
        backend = FakeCritiqueBackend([
            CritiqueResult(ok=False, issues=["too small"]),
            CritiqueResult.acceptable(),
        ])
        executor = PlanExecutor()
        client = MagicMock(spec=OllamaClient)

        # Mock the re-emit response
        reemit_response = _simple_plan().to_json()
        client.chat.return_value = {"message": {"content": reemit_response}}

        loop = CritiqueLoop(
            executor=executor,
            critique_backend=backend,  # type: ignore[arg-type]
            plan_client=client,
            plan_model="test",
            max_rounds=2,
        )

        plan = _simple_plan()
        final_plan, png = loop.run(plan, "draw a red square")

        assert len(png) > 0
        # Should have called the model for re-emit
        client.chat.assert_called()

    def test_max_rounds_exhausted(self) -> None:
        """When max_rounds is 0, should render once and return."""
        backend = FakeCritiqueBackend([
            CritiqueResult(ok=False, issues=["bad"]),
        ])
        executor = PlanExecutor()
        client = MagicMock(spec=OllamaClient)

        loop = CritiqueLoop(
            executor=executor,
            critique_backend=backend,  # type: ignore[arg-type]
            plan_client=client,
            plan_model="test",
            max_rounds=0,
        )

        plan = _simple_plan()
        final_plan, png = loop.run(plan, "draw")

        assert final_plan is plan
        assert len(png) > 0

    def test_reemit_failure_keeps_current_plan(self) -> None:
        """When re-emit returns invalid JSON, should keep current plan."""
        backend = FakeCritiqueBackend([
            CritiqueResult(ok=False, issues=["bad"]),
        ])
        executor = PlanExecutor()
        client = MagicMock(spec=OllamaClient)

        # Mock invalid re-emit response
        client.chat.return_value = {"message": {"content": "not valid json at all"}}

        loop = CritiqueLoop(
            executor=executor,
            critique_backend=backend,  # type: ignore[arg-type]
            plan_client=client,
            plan_model="test",
            max_rounds=1,
        )

        plan = _simple_plan()
        final_plan, png = loop.run(plan, "draw")

        # Should return the original plan since re-emit failed
        assert final_plan is plan
        assert len(png) > 0

    def test_progress_callback_called(self) -> None:
        backend = FakeCritiqueBackend([CritiqueResult.acceptable()])
        executor = PlanExecutor()
        client = MagicMock(spec=OllamaClient)
        progress_msgs: list[str] = []

        loop = CritiqueLoop(
            executor=executor,
            critique_backend=backend,  # type: ignore[arg-type]
            plan_client=client,
            plan_model="test",
            max_rounds=2,
            on_progress=lambda msg: progress_msgs.append(msg),
        )

        loop.run(_simple_plan(), "draw")
        assert len(progress_msgs) > 0
        assert any("Rendering" in m for m in progress_msgs)
