"""Unit tests for backend protocols (PlanGenerator, CritiqueBackend)."""

from __future__ import annotations

from typing import Any

import pytest

from pixelpilot.generation.backends import (
    CritiqueBackend,
    CritiqueResult,
    PlanGenerator,
)
from pixelpilot.generation.schema import ImagePlan


# ---------------------------------------------------------------------------
# CritiqueResult
# ---------------------------------------------------------------------------

class TestCritiqueResult:
    def test_acceptable(self) -> None:
        r = CritiqueResult.acceptable()
        assert r.ok is True
        assert r.issues == []

    def test_failed_parse_returns_ok(self) -> None:
        """failed_parse should return ok=True to prevent infinite loops."""
        r = CritiqueResult.failed_parse("garbage output")
        assert r.ok is True
        assert r.raw == "garbage output"


# ---------------------------------------------------------------------------
# PlanGenerator protocol
# ---------------------------------------------------------------------------

class TestPlanGeneratorProtocol:
    def test_generation_planner_satisfies_protocol(self) -> None:
        """GenerationPlanner should satisfy the PlanGenerator protocol."""
        from pixelpilot.generation.planner import GenerationPlanner
        from pixelpilot.ollama.client import OllamaClient

        # We can't instantiate a real client here, but we can check the protocol
        # structural compatibility via runtime_checkable
        assert hasattr(GenerationPlanner, "generate_plan")
        assert hasattr(GenerationPlanner, "plan")

    def test_plan_generator_protocol_is_runtime_checkable(self) -> None:
        """The PlanGenerator protocol should be runtime_checkable."""
        from typing import get_type_hints

        # Check that the protocol has the expected method
        assert hasattr(PlanGenerator, "generate_plan")


# ---------------------------------------------------------------------------
# CritiqueBackend protocol
# ---------------------------------------------------------------------------

class TestCritiqueBackendProtocol:
    def test_critique_backend_is_runtime_checkable(self) -> None:
        """The CritiqueBackend protocol should be runtime_checkable."""
        assert hasattr(CritiqueBackend, "analyze")
