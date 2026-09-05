"""Unit tests for generation/schema.py — ImagePlan Pydantic models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pixelpilot.generation.schema import (
    CanvasSpec,
    ImagePlan,
    ShapeObject,
    ShapeType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rect(**kw) -> dict:
    base = {
        "id": "r1", "type": "rect", "color": [255, 0, 0], "z_order": 1,
        "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.3,
    }
    base.update(kw)
    return base


def _circle(**kw) -> dict:
    base = {
        "id": "c1", "type": "circle", "color": [0, 255, 0], "z_order": 2,
        "cx": 0.5, "cy": 0.5, "radius": 0.2,
    }
    base.update(kw)
    return base


def _ellipse(**kw) -> dict:
    base = {
        "id": "e1", "type": "ellipse", "color": [0, 0, 255], "z_order": 3,
        "cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.15,
    }
    base.update(kw)
    return base


def _polygon(**kw) -> dict:
    base = {
        "id": "p1", "type": "polygon", "color": [128, 128, 0], "z_order": 4,
        "points": [[0.1, 0.9], [0.5, 0.1], [0.9, 0.9]],
    }
    base.update(kw)
    return base


def _line(**kw) -> dict:
    base = {
        "id": "l1", "type": "line", "color": [0, 0, 0], "z_order": 5,
        "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0,
    }
    base.update(kw)
    return base


def _minimal_plan(*objects) -> dict:
    return {
        "version": "1",
        "canvas": {"width": 800, "height": 600, "background_color": [255, 255, 255]},
        "objects": list(objects),
    }


# ---------------------------------------------------------------------------
# CanvasSpec
# ---------------------------------------------------------------------------

class TestCanvasSpec:
    def test_defaults(self):
        c = CanvasSpec()
        assert c.width == 800
        assert c.height == 600
        assert c.background_color == [255, 255, 255]

    def test_custom(self):
        c = CanvasSpec(width=1920, height=1080, background_color=[0, 0, 0])
        assert c.width == 1920
        assert c.background_color == [0, 0, 0]

    def test_invalid_color_channel(self):
        with pytest.raises(ValidationError):
            CanvasSpec(background_color=[256, 0, 0])

    def test_invalid_color_length(self):
        with pytest.raises(ValidationError):
            CanvasSpec(background_color=[255, 255])

    def test_zero_dimensions_rejected(self):
        with pytest.raises(ValidationError):
            CanvasSpec(width=0, height=600)


# ---------------------------------------------------------------------------
# ShapeObject — rect
# ---------------------------------------------------------------------------

class TestShapeRect:
    def test_valid_rect(self):
        obj = ShapeObject.model_validate(_rect())
        assert obj.type == ShapeType.RECT
        assert obj.x == pytest.approx(0.1)
        assert obj.width == pytest.approx(0.5)

    def test_missing_field(self):
        d = _rect()
        del d["width"]
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(d)

    def test_out_of_bounds_clamped(self):
        obj = ShapeObject.model_validate(_rect(x=1.5, y=-0.2))
        assert obj.x == 1.0   # clamped
        assert obj.y == 0.0   # clamped

    def test_invalid_color(self):
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(_rect(color=[300, 0, 0]))


# ---------------------------------------------------------------------------
# ShapeObject — circle
# ---------------------------------------------------------------------------

class TestShapeCircle:
    def test_valid_circle(self):
        obj = ShapeObject.model_validate(_circle())
        assert obj.type == ShapeType.CIRCLE
        assert obj.radius == pytest.approx(0.2)

    def test_missing_radius(self):
        d = _circle()
        del d["radius"]
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(d)


# ---------------------------------------------------------------------------
# ShapeObject — ellipse
# ---------------------------------------------------------------------------

class TestShapeEllipse:
    def test_valid_ellipse(self):
        obj = ShapeObject.model_validate(_ellipse())
        assert obj.type == ShapeType.ELLIPSE
        assert obj.rx == pytest.approx(0.3)
        assert obj.ry == pytest.approx(0.15)

    def test_missing_ry(self):
        d = _ellipse()
        del d["ry"]
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(d)


# ---------------------------------------------------------------------------
# ShapeObject — polygon
# ---------------------------------------------------------------------------

class TestShapePolygon:
    def test_valid_polygon(self):
        obj = ShapeObject.model_validate(_polygon())
        assert obj.type == ShapeType.POLYGON
        assert len(obj.points) == 3

    def test_too_few_points(self):
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(_polygon(points=[[0.1, 0.1], [0.5, 0.5]]))

    def test_point_clamped(self):
        obj = ShapeObject.model_validate(_polygon(points=[[1.5, -0.1], [0.5, 0.5], [0.9, 0.9]]))
        assert obj.points[0][0] == 1.0
        assert obj.points[0][1] == 0.0


# ---------------------------------------------------------------------------
# ShapeObject — line
# ---------------------------------------------------------------------------

class TestShapeLine:
    def test_valid_line(self):
        obj = ShapeObject.model_validate(_line())
        assert obj.type == ShapeType.LINE

    def test_missing_endpoint(self):
        d = _line()
        del d["x2"]
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(d)


# ---------------------------------------------------------------------------
# ImagePlan
# ---------------------------------------------------------------------------

class TestImagePlan:
    def test_minimal_plan(self):
        plan = ImagePlan.from_dict(_minimal_plan(_rect()))
        assert plan.version == "1"
        assert plan.canvas.width == 800
        assert len(plan.objects) == 1

    def test_z_order_sort(self):
        plan = ImagePlan.from_dict(_minimal_plan(_circle(z_order=5), _rect(z_order=1)))
        sorted_objs = plan.sorted_objects()
        assert sorted_objs[0].z_order == 1
        assert sorted_objs[1].z_order == 5

    def test_wrong_version_rejected(self):
        data = _minimal_plan(_rect())
        data["version"] = "2"
        with pytest.raises(ValidationError):
            ImagePlan.from_dict(data)

    def test_from_json_roundtrip(self):
        plan = ImagePlan.from_dict(_minimal_plan(_rect(), _circle()))
        json_str = plan.to_json()
        plan2 = ImagePlan.from_json(json_str)
        assert len(plan2.objects) == 2
        assert plan2.canvas.width == plan.canvas.width

    def test_from_json_invalid(self):
        with pytest.raises(json.JSONDecodeError):
            ImagePlan.from_json("not json at all")

    def test_empty_objects_allowed(self):
        plan = ImagePlan.from_dict(_minimal_plan())
        assert plan.objects == []

    def test_all_shape_types_in_one_plan(self):
        plan = ImagePlan.from_dict(
            _minimal_plan(_rect(), _circle(), _ellipse(), _polygon(), _line())
        )
        types = {o.type for o in plan.objects}
        assert types == {
            ShapeType.RECT, ShapeType.CIRCLE, ShapeType.ELLIPSE,
            ShapeType.POLYGON, ShapeType.LINE,
        }

    def test_default_canvas_if_omitted(self):
        data = {"version": "1", "objects": []}
        plan = ImagePlan.from_dict(data)
        assert plan.canvas.width == 800

    def test_opacity_bounds(self):
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(_rect(opacity=1.5))
        with pytest.raises(ValidationError):
            ShapeObject.model_validate(_rect(opacity=-0.1))

    def test_opacity_default_is_one(self):
        obj = ShapeObject.model_validate(_rect())
        assert obj.opacity == 1.0
