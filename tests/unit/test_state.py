"""Unit tests for canvas state tracking."""

import json

from pixelpilot.bridge.state import CanvasState, CanvasStateTracker, LayerState


def _sample_state() -> dict:
    return {
        "image_path": "photo.jpg",
        "dimensions": [1920, 1080],
        "color_mode": "RGB",
        "bit_depth": 8,
        "dpi": 300,
        "layers": [
            {"name": "Background", "type": "raster", "visible": True, "opacity": 100,
             "blend_mode": "normal", "locked": False},
            {"name": "Retouching", "type": "raster", "visible": True, "opacity": 85,
             "blend_mode": "normal", "locked": False},
        ],
        "active_layer": "Retouching",
        "has_selection": False,
        "selection_bounds": None,
        "undo_depth": 12,
    }


def test_canvas_state_from_dict():
    state = CanvasState.from_dict(_sample_state())
    assert state.dimensions == [1920, 1080]
    assert len(state.layers) == 2
    assert state.active_layer == "Retouching"
    assert isinstance(state.layers[0], LayerState)
    assert state.layers[1].opacity == 85


def test_compact_json_roundtrip():
    state = CanvasState.from_dict(_sample_state())
    payload = json.loads(state.to_compact_json())
    assert payload["image_path"] == "photo.jpg"
    assert len(payload["layers"]) == 2


def test_tracker_detects_changes():
    tracker = CanvasStateTracker()
    tracker.update(_sample_state())
    assert not tracker.has_changed()

    changed = _sample_state()
    changed["layers"][1]["opacity"] = 40
    tracker.update(changed)
    assert tracker.has_changed()
    summary = tracker.summarize_changes()
    assert "opacity 85->40" in summary


def test_tracker_no_change_summary():
    tracker = CanvasStateTracker()
    tracker.update(_sample_state())
    tracker.update(_sample_state())
    assert tracker.summarize_changes() == "No observable change."
