"""Editor-agnostic intermediate representation (implementation_plan.md §4.3.1).

IR keeps the orchestration layer independent of any specific editor. Code generators
translate IR operations into GIMP Python-Fu or PyKrita scripts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Operation:
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "params": dict(self.params), "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Operation:
        return cls(
            type=data["type"],
            params=data.get("params", {}),
            description=data.get("description", ""),
        )


@dataclass
class ScriptPlan:
    editor: str
    operations: list[Operation] = field(default_factory=list)
    title: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "editor": self.editor,
            "title": self.title,
            "notes": self.notes,
            "operations": [op.to_dict() for op in self.operations],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def add(self, op: Operation) -> None:
        self.operations.append(op)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScriptPlan:
        return cls(
            editor=data.get("editor", "gimp"),
            title=data.get("title", ""),
            notes=data.get("notes", ""),
            operations=[Operation.from_dict(op) for op in data.get("operations", [])],
        )


def parse_ir(data: Any) -> ScriptPlan:
    """Parse IR from a dict or JSON string."""
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise TypeError("IR must be a dict or JSON string")
    return ScriptPlan.from_dict(data)


def render_ir_operations(plan: ScriptPlan) -> str:
    """Render a human-readable summary of a plan (for previews)."""
    lines = [f"Plan: {plan.title or '(untitled)'}  ({plan.editor})"]
    for i, op in enumerate(plan.operations, start=1):
        params = ", ".join(f"{k}={v}" for k, v in op.params.items())
        desc = f"  # {op.description}" if op.description else ""
        lines.append(f"  {i}. {op.type}({params}){desc}")
    if plan.notes:
        lines.append(f"Notes: {plan.notes}")
    return "\n".join(lines)
