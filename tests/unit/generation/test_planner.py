"""Unit tests for generation/planner.py — GenerationPlanner.

All tests mock OllamaClient so no network is required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from pixelpilot.generation.planner import GenerationPlanner, PlannerError
from pixelpilot.generation.schema import ImagePlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(responses: list[str]) -> MagicMock:
    """Return a mock OllamaClient whose chat() yields successive responses."""
    client = MagicMock()
    side_effects = [
        {"message": {"content": r}} for r in responses
    ]
    client.chat.side_effect = side_effects
    return client


def _valid_plan_json(width: int = 800, height: int = 600) -> str:
    plan = {
        "version": "1",
        "canvas": {"width": width, "height": height, "background_color": [255, 255, 255]},
        "objects": [
            {
                "id": "body",
                "type": "rect",
                "color": [200, 50, 50],
                "z_order": 1,
                "x": 0.15, "y": 0.4, "width": 0.7, "height": 0.3,
                "label": "car body",
            }
        ],
    }
    return json.dumps(plan)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestPlannerHappyPath:
    def test_returns_image_plan_on_valid_json(self):
        client = _make_client([_valid_plan_json()])
        planner = GenerationPlanner(client, model="test-model")
        plan = planner.plan("draw a red car")
        assert isinstance(plan, ImagePlan)
        assert len(plan.objects) == 1

    def test_canvas_size_overridden_from_args(self):
        """The planner must force the canvas to the requested size even if
        the model returns different dimensions."""
        client = _make_client([_valid_plan_json(width=400, height=300)])
        planner = GenerationPlanner(client, model="test-model")
        plan = planner.plan("draw a car", width=800, height=600)
        assert plan.canvas.width == 800
        assert plan.canvas.height == 600

    def test_model_called_with_correct_model_name(self):
        client = _make_client([_valid_plan_json()])
        planner = GenerationPlanner(client, model="my-coder-model")
        planner.plan("draw a tree")
        call_args = client.chat.call_args
        assert call_args[0][0] == "my-coder-model"

    def test_json_in_markdown_fence_accepted(self):
        """Model output wrapped in ```json ... ``` should still be parsed."""
        wrapped = f"```json\n{_valid_plan_json()}\n```"
        client = _make_client([wrapped])
        planner = GenerationPlanner(client, model="test-model")
        plan = planner.plan("draw a house")
        assert isinstance(plan, ImagePlan)


# ---------------------------------------------------------------------------
# Retry / self-correction
# ---------------------------------------------------------------------------

class TestPlannerRetry:
    def test_retries_on_invalid_json(self):
        """First response is gibberish; second is valid."""
        client = _make_client(["not json at all", _valid_plan_json()])
        planner = GenerationPlanner(client, model="test-model", max_retries=3)
        plan = planner.plan("draw a car")
        assert isinstance(plan, ImagePlan)
        assert client.chat.call_count == 2

    def test_retries_on_schema_violation(self):
        """First response is valid JSON but fails Pydantic validation."""
        bad_plan = {"version": "1", "canvas": {}, "objects": [
            {"id": "x", "type": "rect", "color": [0, 0, 0], "z_order": 1}
            # missing x, y, width, height for rect
        ]}
        client = _make_client([json.dumps(bad_plan), _valid_plan_json()])
        planner = GenerationPlanner(client, model="test-model", max_retries=3)
        plan = planner.plan("draw a car")
        assert isinstance(plan, ImagePlan)

    def test_raises_after_all_retries_exhausted(self):
        client = _make_client(["bad", "bad", "bad"])
        planner = GenerationPlanner(client, model="test-model", max_retries=3)
        with pytest.raises(PlannerError, match="valid ImagePlan"):
            planner.plan("draw a mountain")

    def test_error_feedback_appended_to_messages(self):
        """On retry the correction feedback must be appended to the conversation."""
        client = _make_client(["not json", _valid_plan_json()])
        planner = GenerationPlanner(client, model="test-model", max_retries=3)
        planner.plan("draw a tree")
        # Second call should have extra messages (the error feedback)
        second_call_messages = client.chat.call_args_list[1][0][1]
        roles = [m["role"] for m in second_call_messages]
        assert "assistant" in roles
        assert roles.count("user") >= 2


# ---------------------------------------------------------------------------
# Ollama failure
# ---------------------------------------------------------------------------

class TestPlannerOllamaFailure:
    def test_raises_on_client_exception(self):
        client = MagicMock()
        client.chat.side_effect = RuntimeError("Ollama connection refused")
        planner = GenerationPlanner(client, model="test-model")
        with pytest.raises(PlannerError, match="Ollama call failed"):
            planner.plan("draw a car")
