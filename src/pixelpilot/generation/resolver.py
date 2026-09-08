"""Plan resolver — resolves attachments, dependency graphs, and constraints.

Given an ImagePlan with ``attach_to`` references and ``constraints``, the
resolver:

  1. Builds a dependency graph from ``attach_to`` references.
  2. Topologically sorts objects (errors on cycles).
  3. Computes each object's absolute position from its anchor + offset.
  4. Applies constraints as clamping (v1 — no full constraint solver).

The resolver mutates the plan **in-place** and returns it for chaining.

Usage::

    from pixelpilot.generation.resolver import PlanResolver

    resolver = PlanResolver()
    resolved_plan = resolver.resolve(plan)
"""

from __future__ import annotations

import copy
from collections import deque

from pixelpilot.generation.schema import (
    Anchor,
    AspectRatioConstraint,
    AttachTo,
    Constraint,
    ImagePlan,
    PositionRangeConstraint,
    ShapeObject,
    ShapeType,
    SizeRatioConstraint,
)


class ResolutionError(ValueError):
    """Raised when the plan cannot be resolved (e.g. cyclic dependencies)."""


# ---------------------------------------------------------------------------
# Anchor point computation
# ---------------------------------------------------------------------------

def _anchor_xy(obj: ShapeObject, anchor: Anchor) -> tuple[float, float]:
    """Return the (x, y) position of *anchor* on *obj* in normalised fractions."""

    if obj.type == ShapeType.RECT:
        x: float = obj.x  # type: ignore[assignment]
        y: float = obj.y  # type: ignore[assignment]
        w: float = obj.width  # type: ignore[assignment]
        h: float = obj.height  # type: ignore[assignment]
        return _rect_anchor(x, y, w, h, anchor)

    if obj.type == ShapeType.CIRCLE:
        cx: float = obj.cx  # type: ignore[assignment]
        cy: float = obj.cy  # type: ignore[assignment]
        r: float = obj.radius  # type: ignore[assignment]
        return _circle_anchor(cx, cy, r, r, anchor)

    if obj.type == ShapeType.ELLIPSE:
        cx = obj.cx  # type: ignore[assignment]
        cy = obj.cy  # type: ignore[assignment]
        rx = obj.rx  # type: ignore[assignment]
        ry = obj.ry  # type: ignore[assignment]
        return _circle_anchor(cx, cy, rx, ry, anchor)

    if obj.type == ShapeType.LINE:
        x1 = obj.x1  # type: ignore[assignment]
        y1 = obj.y1  # type: ignore[assignment]
        x2 = obj.x2  # type: ignore[assignment]
        y2 = obj.y2  # type: ignore[assignment]
        return _line_anchor(x1, y1, x2, y2, anchor)

    # polygon — use centroid approximation
    if obj.type == ShapeType.POLYGON and obj.points:
        return _polygon_anchor(obj.points, anchor)

    # Fallback: return center-ish (0.5, 0.5)
    return 0.5, 0.5


def _rect_anchor(
    x: float, y: float, w: float, h: float, anchor: Anchor
) -> tuple[float, float]:
    _ANCHORS: dict[Anchor, tuple[float, float]] = {
        Anchor.CENTER: (x + w / 2, y + h / 2),
        Anchor.TOP_LEFT: (x, y),
        Anchor.TOP_CENTER: (x + w / 2, y),
        Anchor.TOP_RIGHT: (x + w, y),
        Anchor.MIDDLE_LEFT: (x, y + h / 2),
        Anchor.MIDDLE_RIGHT: (x + w, y + h / 2),
        Anchor.BOTTOM_LEFT: (x, y + h),
        Anchor.BOTTOM_CENTER: (x + w / 2, y + h),
        Anchor.BOTTOM_RIGHT: (x + w, y + h),
    }
    return _ANCHORS.get(anchor, (x + w / 2, y + h / 2))


def _circle_anchor(
    cx: float, cy: float, rx: float, ry: float, anchor: Anchor
) -> tuple[float, float]:
    _ANCHORS: dict[Anchor, tuple[float, float]] = {
        Anchor.CENTER: (cx, cy),
        Anchor.NORTH: (cx, cy - ry),
        Anchor.SOUTH: (cx, cy + ry),
        Anchor.EAST: (cx + rx, cy),
        Anchor.WEST: (cx - rx, cy),
        Anchor.TOP_LEFT: (cx - rx, cy - ry),
        Anchor.TOP_CENTER: (cx, cy - ry),
        Anchor.TOP_RIGHT: (cx + rx, cy - ry),
        Anchor.MIDDLE_LEFT: (cx - rx, cy),
        Anchor.MIDDLE_RIGHT: (cx + rx, cy),
        Anchor.BOTTOM_LEFT: (cx - rx, cy + ry),
        Anchor.BOTTOM_CENTER: (cx, cy + ry),
        Anchor.BOTTOM_RIGHT: (cx + rx, cy + ry),
    }
    return _ANCHORS.get(anchor, (cx, cy))


def _line_anchor(
    x1: float, y1: float, x2: float, y2: float, anchor: Anchor
) -> tuple[float, float]:
    _ANCHORS: dict[Anchor, tuple[float, float]] = {
        Anchor.CENTER: ((x1 + x2) / 2, (y1 + y2) / 2),
        Anchor.TOP_LEFT: (min(x1, x2), min(y1, y2)),
        Anchor.BOTTOM_RIGHT: (max(x1, x2), max(y1, y2)),
        Anchor.MIDDLE_LEFT: (min(x1, x2), (y1 + y2) / 2),
        Anchor.MIDDLE_RIGHT: (max(x1, x2), (y1 + y2) / 2),
    }
    return _ANCHORS.get(anchor, ((x1 + x2) / 2, (y1 + y2) / 2))


def _polygon_anchor(
    points: list[list[float]], anchor: Anchor
) -> tuple[float, float]:
    if not points:
        return 0.5, 0.5
    if anchor == Anchor.CENTER:
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        return cx, cy
    # For other anchors on polygons, approximate with bounding box
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return _rect_anchor(
        min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), anchor
    )


# ---------------------------------------------------------------------------
# Dependency graph & topological sort
# ---------------------------------------------------------------------------

def _build_dependency_graph(objects: list[ShapeObject]) -> dict[str, set[str]]:
    """Build adjacency list: object_id → set of IDs it depends on."""
    graph: dict[str, set[str]] = {}
    for obj in objects:
        deps: set[str] = set()
        if obj.attach_to and obj.attach_to.object:
            deps.add(obj.attach_to.object)
        graph[obj.id] = deps
    return graph


def _topological_sort(graph: dict[str, set[str]]) -> list[str]:
    """Kahn's algorithm. Raises ResolutionError on cycles."""
    # Compute in-degree
    in_degree: dict[str, int] = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[node] += 1

    queue: deque[str] = deque(
        node for node, deg in in_degree.items() if deg == 0
    )
    order: list[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for other, deps in graph.items():
            if node in deps:
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    queue.append(other)

    if len(order) != len(graph):
        visited = set(order)
        missing = sorted(set(graph) - visited)
        raise ResolutionError(
            f"Cyclic dependency detected among objects: {', '.join(missing)}"
        )

    return order


# ---------------------------------------------------------------------------
# Position computation
# ---------------------------------------------------------------------------

def _apply_attachment(
    child: ShapeObject, parent: ShapeObject
) -> None:
    """Reposition *child* based on its ``attach_to`` relative to *parent*."""
    if child.attach_to is None:
        return

    anchor = child.attach_to.anchor
    offset_x, offset_y = child.attach_to.offset
    px, py = _anchor_xy(parent, anchor)

    new_x = px + offset_x
    new_y = py + offset_y

    if child.type == ShapeType.RECT:
        child.x = new_x
        child.y = new_y
    elif child.type in (ShapeType.CIRCLE, ShapeType.ELLIPSE):
        child.cx = new_x
        child.cy = new_y
    elif child.type == ShapeType.LINE:
        dx = (child.x2 or 0) - (child.x1 or 0)
        dy = (child.y2 or 0) - (child.y1 or 0)
        child.x1 = new_x
        child.y1 = new_y
        child.x2 = new_x + dx
        child.y2 = new_y + dy
    elif child.type == ShapeType.POLYGON and child.points:
        # Shift all polygon vertices so their centroid lands on (new_x, new_y)
        cx = sum(p[0] for p in child.points) / len(child.points)
        cy = sum(p[1] for p in child.points) / len(child.points)
        dx = new_x - cx
        dy = new_y - cy
        child.points = [[p[0] + dx, p[1] + dy] for p in child.points]


# ---------------------------------------------------------------------------
# Constraint enforcement
# ---------------------------------------------------------------------------

def _object_dimension(obj: ShapeObject, dim: str) -> float:
    """Read a named dimension from a shape object."""
    val = getattr(obj, dim, None)
    if val is None:
        return 0.0
    return float(val)


def _apply_constraints(
    objects: list[ShapeObject], constraints: list[Constraint]
) -> None:
    """Apply constraints by clamping values. Mutates objects in-place."""
    by_id = {o.id: o for o in objects}

    for c in constraints:
        if isinstance(c, AspectRatioConstraint):
            _clamp_aspect_ratio(by_id.get(c.object), c)
        elif isinstance(c, SizeRatioConstraint):
            _clamp_size_ratio(by_id.get(c.a), by_id.get(c.b), c)
        elif isinstance(c, PositionRangeConstraint):
            _clamp_position_range(by_id.get(c.object), c)


def _clamp_aspect_ratio(obj: ShapeObject | None, c: AspectRatioConstraint) -> None:
    if obj is None:
        return
    if obj.type == ShapeType.RECT:
        w = obj.width or 0.001  # type: ignore[operator]
        h = obj.height or 0.001  # type: ignore[operator]
        ratio = w / h
        if ratio < c.min:
            obj.width = h * c.min  # type: ignore[operator]
        elif ratio > c.max:
            obj.width = h * c.max  # type: ignore[operator]
    elif obj.type == ShapeType.ELLIPSE:
        rx = obj.rx or 0.001  # type: ignore[operator]
        ry = obj.ry or 0.001  # type: ignore[operator]
        ratio = rx / ry
        if ratio < c.min:
            obj.rx = ry * c.min  # type: ignore[operator]
        elif ratio > c.max:
            obj.rx = ry * c.max  # type: ignore[operator]


def _clamp_size_ratio(
    a: ShapeObject | None,
    b: ShapeObject | None,
    c: SizeRatioConstraint,
) -> None:
    if a is None or b is None:
        return
    dim_a = _object_dimension(a, c.dimension)
    dim_b = _object_dimension(b, c.dimension)
    if dim_b <= 0:
        return
    ratio = dim_a / dim_b
    if ratio < c.min:
        setattr(a, c.dimension, dim_b * c.min)
    elif ratio > c.max:
        setattr(a, c.dimension, dim_b * c.max)


def _clamp_position_range(
    obj: ShapeObject | None, c: PositionRangeConstraint
) -> None:
    if obj is None:
        return
    if obj.type == ShapeType.RECT:
        obj.x = max(c.x_min, min(c.x_max, obj.x))  # type: ignore[operator]
        obj.y = max(c.y_min, min(c.y_max, obj.y))  # type: ignore[operator]
    elif obj.type in (ShapeType.CIRCLE, ShapeType.ELLIPSE):
        obj.cx = max(c.x_min, min(c.x_max, obj.cx))  # type: ignore[operator]
        obj.cy = max(c.y_min, min(c.y_max, obj.cy))  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------

class PlanResolver:
    """Resolve attachments, dependencies, and constraints in an ImagePlan.

    Usage::

        resolver = PlanResolver()
        resolved = resolver.resolve(plan)
    """

    def resolve(self, plan: ImagePlan) -> ImagePlan:
        """Return a **new** plan with all attachments and constraints resolved.

        The original plan is not mutated.

        Raises:
            ResolutionError: on cyclic dependencies or missing referenced IDs.
        """
        resolved = copy.deepcopy(plan)

        if not resolved.objects:
            return resolved

        # Validate that all attach_to references point to existing objects
        id_set = {o.id for o in resolved.objects}
        for obj in resolved.objects:
            if obj.attach_to and obj.attach_to.object not in id_set:
                raise ResolutionError(
                    f"Object '{obj.id}' attaches to unknown object '{obj.attach_to.object}'"
                )

        # Build dependency graph and topologically sort
        graph = _build_dependency_graph(resolved.objects)
        order = _topological_sort(graph)

        # Build id→object lookup (rebuilt after sort to match order)
        by_id = {o.id: o for o in resolved.objects}

        # Resolve attachments in dependency order
        for obj_id in order:
            obj = by_id[obj_id]
            if obj.attach_to:
                parent = by_id.get(obj.attach_to.object)
                if parent is not None:
                    _apply_attachment(obj, parent)

        # Apply constraints (clamping)
        _apply_constraints(resolved.objects, resolved.constraints)

        return resolved
