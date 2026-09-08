"""Unit tests for the plan resolver (Phase 2: attachments & constraints)."""

from __future__ import annotations

import pytest

from pixelpilot.generation.resolver import PlanResolver, ResolutionError
from pixelpilot.generation.schema import (
    Anchor,
    AttachTo,
    CanvasSpec,
    ImagePlan,
    ShapeObject,
    ShapeType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rect(
    id: str,
    x: float = 0.1,
    y: float = 0.1,
    w: float = 0.3,
    h: float = 0.4,
    z: int = 1,
    **kwargs: object,
) -> ShapeObject:
    return ShapeObject(
        id=id, type=ShapeType.RECT, color=[255, 0, 0], z_order=z,
        x=x, y=y, width=w, height=h, **kwargs,  # type: ignore[arg-type]
    )


def _ellipse(
    id: str,
    cx: float = 0.5,
    cy: float = 0.5,
    rx: float = 0.2,
    ry: float = 0.15,
    z: int = 1,
    **kwargs: object,
) -> ShapeObject:
    return ShapeObject(
        id=id, type=ShapeType.ELLIPSE, color=[0, 255, 0], z_order=z,
        cx=cx, cy=cy, rx=rx, ry=ry, **kwargs,  # type: ignore[arg-type]
    )


def _plan(*objects: ShapeObject, constraints=None) -> ImagePlan:
    return ImagePlan(
        canvas=CanvasSpec(width=800, height=600),
        objects=list(objects),
        constraints=constraints or [],
    )


# ---------------------------------------------------------------------------
# No attachments — passthrough
# ---------------------------------------------------------------------------

class TestNoAttachments:
    def test_plan_without_attachments_unchanged(self) -> None:
        r = PlanResolver()
        obj = _rect("a", x=0.2, y=0.3)
        plan = _plan(obj)
        resolved = r.resolve(plan)
        assert resolved.objects[0].x == 0.2
        assert resolved.objects[0].y == 0.3

    def test_plan_without_objects(self) -> None:
        r = PlanResolver()
        plan = _plan()
        resolved = r.resolve(plan)
        assert resolved.objects == []


# ---------------------------------------------------------------------------
# Basic attachment
# ---------------------------------------------------------------------------

class TestAttachment:
    def test_attach_rect_to_rect_center(self) -> None:
        parent = _rect("parent", x=0.2, y=0.2, w=0.4, h=0.4)
        child = _rect("child", x=0.0, y=0.0, w=0.1, h=0.1)
        child.attach_to = AttachTo(object="parent", anchor=Anchor.CENTER)
        plan = _plan(parent, child)
        resolved = PlanResolver().resolve(plan)

        child_resolved = next(o for o in resolved.objects if o.id == "child")
        # parent center: (0.2 + 0.4/2, 0.2 + 0.4/2) = (0.4, 0.4)
        assert abs(child_resolved.x - 0.4) < 0.001
        assert abs(child_resolved.y - 0.4) < 0.001

    def test_attach_with_offset(self) -> None:
        parent = _rect("parent", x=0.2, y=0.2, w=0.4, h=0.4)
        child = _rect("child", x=0.0, y=0.0, w=0.1, h=0.1)
        child.attach_to = AttachTo(
            object="parent", anchor=Anchor.TOP_CENTER, offset=[0.0, -0.05]
        )
        plan = _plan(parent, child)
        resolved = PlanResolver().resolve(plan)

        child_resolved = next(o for o in resolved.objects if o.id == "child")
        # parent top center: (0.2 + 0.4/2, 0.2) = (0.4, 0.2)
        assert abs(child_resolved.x - 0.4) < 0.001
        assert abs(child_resolved.y - 0.15) < 0.001

    def test_attach_ellipse_to_rect(self) -> None:
        parent = _rect("base", x=0.3, y=0.3, w=0.4, h=0.4)
        child = _ellipse("top", rx=0.1, ry=0.1)
        child.attach_to = AttachTo(object="base", anchor=Anchor.CENTER)
        plan = _plan(parent, child)
        resolved = PlanResolver().resolve(plan)

        child_resolved = next(o for o in resolved.objects if o.id == "top")
        assert abs(child_resolved.cx - 0.5) < 0.001
        assert abs(child_resolved.cy - 0.5) < 0.001


# ---------------------------------------------------------------------------
# Dependency ordering
# ---------------------------------------------------------------------------

class TestDependencyOrdering:
    def test_chain_of_attachments(self) -> None:
        """A -> B -> C should resolve in order: A, B, C."""
        a = _rect("a", x=0.1, y=0.1, w=0.2, h=0.2)
        b = _rect("b", w=0.05, h=0.05)
        b.attach_to = AttachTo(object="a", anchor=Anchor.CENTER)
        c = _rect("c", w=0.05, h=0.05)
        c.attach_to = AttachTo(object="b", anchor=Anchor.CENTER)

        plan = _plan(a, b, c)
        resolved = PlanResolver().resolve(plan)

        a_r = next(o for o in resolved.objects if o.id == "a")
        b_r = next(o for o in resolved.objects if o.id == "b")
        c_r = next(o for o in resolved.objects if o.id == "c")

        # a center: (0.1 + 0.2/2, 0.1 + 0.2/2) = (0.2, 0.2)
        assert abs(b_r.x - 0.2) < 0.001
        assert abs(b_r.y - 0.2) < 0.001
        # b center: (0.2 + 0.05/2, 0.2 + 0.05/2) = (0.225, 0.225)
        assert abs(c_r.x - 0.225) < 0.001
        assert abs(c_r.y - 0.225) < 0.001


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    def test_self_reference_raises(self) -> None:
        obj = _rect("a")
        obj.attach_to = AttachTo(object="a", anchor=Anchor.CENTER)
        plan = _plan(obj)
        with pytest.raises(ResolutionError, match="Cyclic"):
            PlanResolver().resolve(plan)

    def test_mutual_reference_raises(self) -> None:
        a = _rect("a")
        b = _rect("b")
        a.attach_to = AttachTo(object="b", anchor=Anchor.CENTER)
        b.attach_to = AttachTo(object="a", anchor=Anchor.CENTER)
        plan = _plan(a, b)
        with pytest.raises(ResolutionError, match="Cyclic"):
            PlanResolver().resolve(plan)

    def test_three_cycle_raises(self) -> None:
        a = _rect("a")
        b = _rect("b")
        c = _rect("c")
        a.attach_to = AttachTo(object="b", anchor=Anchor.CENTER)
        b.attach_to = AttachTo(object="c", anchor=Anchor.CENTER)
        c.attach_to = AttachTo(object="a", anchor=Anchor.CENTER)
        plan = _plan(a, b, c)
        with pytest.raises(ResolutionError, match="Cyclic"):
            PlanResolver().resolve(plan)


# ---------------------------------------------------------------------------
# Missing reference
# ---------------------------------------------------------------------------

class TestMissingReference:
    def test_attach_to_unknown_object_raises(self) -> None:
        obj = _rect("a")
        obj.attach_to = AttachTo(object="nonexistent", anchor=Anchor.CENTER)
        plan = _plan(obj)
        with pytest.raises(ResolutionError, match="unknown object"):
            PlanResolver().resolve(plan)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

class TestConstraints:
    def test_aspect_ratio_clamping(self) -> None:
        from pixelpilot.generation.schema import AspectRatioConstraint

        obj = _rect("a", w=0.01, h=0.5)  # ratio = 0.02, way below min
        constraint = AspectRatioConstraint(
            type="aspect_ratio_range", object="a", min=0.5, max=2.0
        )
        plan = _plan(obj, constraints=[constraint])
        resolved = PlanResolver().resolve(plan)

        resolved_obj = resolved.objects[0]
        ratio = resolved_obj.width / resolved_obj.height  # type: ignore[union-attr]
        assert ratio >= 0.5 - 0.001

    def test_size_ratio_clamping(self) -> None:
        from pixelpilot.generation.schema import SizeRatioConstraint

        big = _rect("big", w=0.5, h=0.5)
        small = _rect("small", w=0.01, h=0.01)
        constraint = SizeRatioConstraint(
            type="size_ratio", a="small", b="big", dimension="width",
            min=0.5, max=2.0,
        )
        plan = _plan(big, small, constraints=[constraint])
        resolved = PlanResolver().resolve(plan)

        small_r = next(o for o in resolved.objects if o.id == "small")
        assert small_r.width >= 0.25 - 0.001  # 0.5 * 0.5 = 0.25


# ---------------------------------------------------------------------------
# Anchor points
# ---------------------------------------------------------------------------

class TestAnchorPoints:
    def test_rect_all_anchors(self) -> None:
        from pixelpilot.generation.resolver import _anchor_xy

        obj = _rect("r", x=0.2, y=0.3, w=0.4, h=0.4)

        assert _anchor_xy(obj, Anchor.TOP_LEFT) == pytest.approx((0.2, 0.3))
        assert _anchor_xy(obj, Anchor.TOP_CENTER) == pytest.approx((0.4, 0.3))
        assert _anchor_xy(obj, Anchor.TOP_RIGHT) == pytest.approx((0.6, 0.3))
        assert _anchor_xy(obj, Anchor.MIDDLE_LEFT) == pytest.approx((0.2, 0.5))
        assert _anchor_xy(obj, Anchor.CENTER) == pytest.approx((0.4, 0.5))
        assert _anchor_xy(obj, Anchor.MIDDLE_RIGHT) == pytest.approx((0.6, 0.5))
        assert _anchor_xy(obj, Anchor.BOTTOM_LEFT) == pytest.approx((0.2, 0.7))
        assert _anchor_xy(obj, Anchor.BOTTOM_CENTER) == pytest.approx((0.4, 0.7))
        assert _anchor_xy(obj, Anchor.BOTTOM_RIGHT) == pytest.approx((0.6, 0.7))

    def test_ellipse_cardinal_anchors(self) -> None:
        from pixelpilot.generation.resolver import _anchor_xy

        obj = _ellipse("e", cx=0.5, cy=0.5, rx=0.2, ry=0.15)

        assert _anchor_xy(obj, Anchor.CENTER) == pytest.approx((0.5, 0.5))
        assert _anchor_xy(obj, Anchor.NORTH) == pytest.approx((0.5, 0.35))
        assert _anchor_xy(obj, Anchor.SOUTH) == pytest.approx((0.5, 0.65))
        assert _anchor_xy(obj, Anchor.EAST) == pytest.approx((0.7, 0.5))
        assert _anchor_xy(obj, Anchor.WEST) == pytest.approx((0.3, 0.5))


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

class TestImmutability:
    def test_original_plan_not_mutated(self) -> None:
        parent = _rect("parent", x=0.2, y=0.2, w=0.4, h=0.4)
        child = _rect("child", x=0.0, y=0.0, w=0.1, h=0.1)
        child.attach_to = AttachTo(object="parent", anchor=Anchor.CENTER)
        plan = _plan(parent, child)

        _ = PlanResolver().resolve(plan)

        # Original child should still be at (0, 0)
        orig_child = next(o for o in plan.objects if o.id == "child")
        assert orig_child.x == 0.0
        assert orig_child.y == 0.0
