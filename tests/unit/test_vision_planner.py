"""Unit tests for VisionPlanner (vision-first scene planning)."""

from __future__ import annotations

import json

from pixelpilot.feedback.vision_planner import VisionPlanner


class _FakeClient:
    def __init__(self, content: str | None = None, raise_exc: Exception | None = None):
        self.content = content
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    def chat(self, model, messages, **kwargs):
        self.calls.append({"model": model, "messages": messages})
        if self.raise_exc:
            raise self.raise_exc
        return {"message": {"content": self.content}}


def _plan_json():
    return json.dumps(
        {
            "scene_description": "A blank canvas.",
            "elements": [
                {
                    "name": "car body",
                    "color_rgb": [178, 34, 34],
                    "size_fraction": "60% width, 18% height",
                    "grid_position": "center",
                    "notes": "wide rectangle",
                },
                {
                    "name": "left wheel",
                    "color_rgb": [40, 40, 40],
                    "size_fraction": "10% width",
                    "grid_position": "bot-left",
                    "notes": "",
                },
            ],
        }
    )


def test_plan_success_renders_plain_text():
    client = _FakeClient(content=_plan_json())
    planner = VisionPlanner(client, model="qwen3-vl:8b", enabled=True)

    result = planner.plan("draw a car", screenshot_bytes=b"fake-png-bytes", width=1024, height=768)

    assert result["success"] is True
    assert "car body" in result["plan_text"]
    assert "left wheel" in result["plan_text"]
    assert "bot-left" in result["plan_text"]
    # The image must actually be sent to the model.
    images = client.calls[0]["messages"][0]["images"]
    assert images and isinstance(images[0], str)


def test_plan_disabled_returns_no_plan_without_calling_model():
    client = _FakeClient(content=_plan_json())
    planner = VisionPlanner(client, model="qwen3-vl:8b", enabled=False)

    result = planner.plan("draw a car", screenshot_bytes=b"fake-png-bytes")

    assert result["success"] is False
    assert result["plan_text"] == ""
    assert client.calls == []


def test_plan_no_screenshot_returns_no_plan_without_calling_model():
    client = _FakeClient(content=_plan_json())
    planner = VisionPlanner(client, model="qwen3-vl:8b", enabled=True)

    result = planner.plan("draw a car", screenshot_bytes=None)

    assert result["success"] is False
    assert client.calls == []


def test_plan_degrades_gracefully_on_model_error():
    client = _FakeClient(raise_exc=RuntimeError("model unreachable"))
    planner = VisionPlanner(client, model="qwen3-vl:8b", enabled=True)

    result = planner.plan("draw a car", screenshot_bytes=b"fake-png-bytes")

    assert result["success"] is False
    assert result["plan_text"] == ""


def test_plan_degrades_gracefully_on_bad_json():
    client = _FakeClient(content="not json at all")
    planner = VisionPlanner(client, model="qwen3-vl:8b", enabled=True, )
    # max_retries=0 to keep the test fast/deterministic
    result = planner.plan("draw a car", screenshot_bytes=b"fake-png-bytes", max_retries=0)

    assert result["success"] is False
    assert result["plan_text"] == ""
