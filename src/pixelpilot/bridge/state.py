"""Canvas state tracking (implementation_plan.md §4.5.4).

Maintains a structured, compact representation of the editor canvas that is injected
into the LLM context across turns (~200 tokens).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LayerState:
    name: str = ""
    type: str = "raster"
    visible: bool = True
    opacity: int = 100
    blend_mode: str = "normal"
    locked: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayerState:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CanvasState:
    image_path: str | None = None
    dimensions: list[int] = field(default_factory=lambda: [0, 0])
    color_mode: str = "RGB"
    bit_depth: int = 8
    dpi: int = 72
    layers: list[LayerState] = field(default_factory=list)
    active_layer: str | None = None
    has_selection: bool = False
    selection_bounds: list[int] | None = None
    undo_depth: int = 0

    # ------------------------------------------------------------ (de)serialise

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanvasState:
        layers = [LayerState.from_dict(l) for l in data.get("layers", [])]
        return cls(
            image_path=data.get("image_path"),
            dimensions=list(data.get("dimensions", [0, 0])),
            color_mode=data.get("color_mode", "RGB"),
            bit_depth=int(data.get("bit_depth", 8)),
            dpi=int(data.get("dpi", 72)),
            layers=layers,
            active_layer=data.get("active_layer"),
            has_selection=bool(data.get("has_selection", False)),
            selection_bounds=data.get("selection_bounds"),
            undo_depth=int(data.get("undo_depth", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_compact_json(self) -> str:
        """Compact JSON representation sized for the ~200-token context budget."""
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)

    def is_empty(self) -> bool:
        return not self.layers and (not self.dimensions or self.dimensions == [0, 0])


class CanvasStateTracker:
    """Tracks canvas state across turns and detects changes."""

    def __init__(self) -> None:
        self._state: CanvasState = CanvasState()
        self._previous: CanvasState | None = None
        self._initialized = False

    @property
    def state(self) -> CanvasState:
        return self._state

    def update(self, raw: dict[str, Any]) -> CanvasState:
        """Replace state from a bridge payload; returns the new state."""
        if self._initialized:
            self._previous = self._state
        self._state = CanvasState.from_dict(raw)
        self._initialized = True
        return self._state

    def has_changed(self) -> bool:
        return self._initialized and self._previous is not None and self._state != self._previous

    def summarize_changes(self) -> str:
        """Text description of what changed since the last update (text feedback)."""
        if self._previous is None or not self.has_changed():
            return "No observable change."
        before, after = self._previous, self._state
        changes: list[str] = []

        if before.dimensions != after.dimensions:
            changes.append(
                f"canvas resized from {before.dimensions} to {after.dimensions}"
            )
        if before.active_layer != after.active_layer and after.active_layer:
            changes.append(f"active layer is now '{after.active_layer}'")
        if len(before.layers) != len(after.layers):
            changes.append(
                f"layer count changed from {len(before.layers)} to {len(after.layers)}"
            )

        before_by_name = {l.name: l for l in before.layers}
        after_by_name = {l.name: l for l in after.layers}
        for name, new in after_by_name.items():
            old = before_by_name.get(name)
            if old is None:
                changes.append(f"layer '{name}' added")
                continue
            if old.opacity != new.opacity:
                changes.append(f"layer '{name}' opacity {old.opacity}->{new.opacity}")
            if old.blend_mode != new.blend_mode:
                changes.append(
                    f"layer '{name}' blend mode {old.blend_mode}->{new.blend_mode}"
                )
            if old.visible != new.visible:
                changes.append(f"layer '{name}' visibility set to {new.visible}")

        if before.has_selection != after.has_selection:
            changes.append("selection added" if after.has_selection else "selection cleared")

        return "; ".join(changes) if changes else "No observable change."
