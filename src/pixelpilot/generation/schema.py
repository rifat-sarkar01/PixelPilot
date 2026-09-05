"""Pydantic schema for the structured ImagePlan.

The LLM emits a JSON object matching this schema for generation intents.
The executor consumes it deterministically — no LLM-written code is ever
executed in the generation path.

All positional coordinates are normalised fractions (0.0–1.0) of the canvas
width/height.  The executor multiplies by actual canvas pixel dimensions so
the plan is resolution-independent.

Schema version: "1"
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ShapeType(str, Enum):
    """Primitive shape types supported by the executor in v1."""

    RECT = "rect"
    CIRCLE = "circle"
    ELLIPSE = "ellipse"
    POLYGON = "polygon"
    LINE = "line"


def _validate_color(v: Any) -> list[int]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ValueError("color must be a list of 3 integers [R, G, B]")
    result = [int(c) for c in v]
    for c in result:
        if not (0 <= c <= 255):
            raise ValueError(f"color channel {c} out of range 0–255")
    return result


# ---------------------------------------------------------------------------
# Fraction helper — clamps to [0, 1] and coerces numeric strings
# ---------------------------------------------------------------------------

def _clamp(v: Any, name: str = "value") -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {v!r}") from exc
    return max(0.0, min(1.0, f))


# ---------------------------------------------------------------------------
# Shape object
# ---------------------------------------------------------------------------

class ShapeObject(BaseModel):
    """A single shape in the image plan."""

    id: str = Field(..., description="Unique identifier within this plan")
    type: ShapeType
    color: list[int] = Field(..., description="Fill color as [R, G, B]")
    z_order: int = Field(..., ge=1, description="Render order; 1 = furthest back")
    label: str = Field("", description="Human-readable name for debugging")
    opacity: float = Field(1.0, ge=0.0, le=1.0)

    # rect
    x: float | None = Field(None, description="Left edge, fraction of canvas width")
    y: float | None = Field(None, description="Top edge, fraction of canvas height")
    width: float | None = Field(None, description="Width, fraction of canvas width")
    height: float | None = Field(None, description="Height, fraction of canvas height")

    # circle / ellipse centre
    cx: float | None = Field(None, description="Centre X, fraction of canvas width")
    cy: float | None = Field(None, description="Centre Y, fraction of canvas height")

    # circle
    radius: float | None = Field(None, description="Radius, fraction of canvas width")

    # ellipse
    rx: float | None = Field(None, description="X-radius, fraction of canvas width")
    ry: float | None = Field(None, description="Y-radius, fraction of canvas height")

    # polygon — list of [x, y] pairs, each a fraction
    points: list[list[float]] | None = Field(
        None, description="Vertices as [[x,y], …], fractions"
    )

    # line
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    stroke_width: float = Field(0.005, description="Line width, fraction of canvas width")

    @field_validator("color", mode="before")
    @classmethod
    def _validate_color(cls, v: Any) -> list[int]:
        return _validate_color(v)

    @model_validator(mode="after")
    def _validate_shape_fields(self) -> "ShapeObject":
        """Check that required type-specific fields are present."""
        t = self.type
        if t == ShapeType.RECT:
            _require(self, "x", "y", "width", "height")
            self.x = _clamp(self.x, "x")
            self.y = _clamp(self.y, "y")
            self.width = _clamp(self.width, "width")
            self.height = _clamp(self.height, "height")
        elif t == ShapeType.CIRCLE:
            _require(self, "cx", "cy", "radius")
            self.cx = _clamp(self.cx, "cx")
            self.cy = _clamp(self.cy, "cy")
            self.radius = _clamp(self.radius, "radius")
        elif t == ShapeType.ELLIPSE:
            _require(self, "cx", "cy", "rx", "ry")
            self.cx = _clamp(self.cx, "cx")
            self.cy = _clamp(self.cy, "cy")
            self.rx = _clamp(self.rx, "rx")
            self.ry = _clamp(self.ry, "ry")
        elif t == ShapeType.POLYGON:
            if not self.points or len(self.points) < 3:
                raise ValueError("polygon requires at least 3 points")
            self.points = [
                [_clamp(p[0], "point x"), _clamp(p[1], "point y")]
                for p in self.points
            ]
        elif t == ShapeType.LINE:
            _require(self, "x1", "y1", "x2", "y2")
            self.x1 = _clamp(self.x1, "x1")
            self.y1 = _clamp(self.y1, "y1")
            self.x2 = _clamp(self.x2, "x2")
            self.y2 = _clamp(self.y2, "y2")
        return self


def _require(obj: ShapeObject, *fields: str) -> None:
    missing = [f for f in fields if getattr(obj, f) is None]
    if missing:
        raise ValueError(
            f"shape type '{obj.type}' requires fields: {', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Canvas spec
# ---------------------------------------------------------------------------

class CanvasSpec(BaseModel):
    """Canvas dimensions and background."""

    width: int = Field(800, ge=1, le=16384)
    height: int = Field(600, ge=1, le=16384)
    background_color: list[int] = Field(
        default_factory=lambda: [255, 255, 255],
        description="Background fill as [R, G, B]",
    )

    @field_validator("background_color", mode="before")
    @classmethod
    def _validate_bg(cls, v: Any) -> list[int]:
        return _validate_color(v)


# ---------------------------------------------------------------------------
# Top-level ImagePlan
# ---------------------------------------------------------------------------

class ImagePlan(BaseModel):
    """Root object emitted by the LLM for generation intents."""

    version: str = Field("1", description="Schema version — must be '1'")
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    objects: list[ShapeObject] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != "1":
            raise ValueError(f"Unsupported ImagePlan version: {v!r} (expected '1')")
        return v

    def sorted_objects(self) -> list[ShapeObject]:
        """Return objects sorted by z_order ascending (back → front)."""
        return sorted(self.objects, key=lambda o: o.z_order)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_json(cls, text: str) -> "ImagePlan":
        """Parse an ImagePlan from a JSON string.

        Raises:
            json.JSONDecodeError: if *text* is not valid JSON.
            pydantic.ValidationError: if the JSON structure doesn't match the schema.
        """
        data = json.loads(text)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImagePlan":
        return cls.model_validate(data)

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
