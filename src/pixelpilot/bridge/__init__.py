"""Editor bridge layer: GIMP / Krita IPC plus canvas-state tracking."""

from pixelpilot.bridge.base import (
    BridgeConnectionError,
    BridgeExecutionError,
    EditorBridge,
)
from pixelpilot.bridge.gimp_bridge import GimpBridge
from pixelpilot.bridge.krita_bridge import KritaBridge
from pixelpilot.bridge.launcher import LauncherError, find_gimp_binary, launch_and_wait
from pixelpilot.bridge.state import CanvasState, CanvasStateTracker, LayerState

__all__ = [
    "BridgeConnectionError",
    "BridgeExecutionError",
    "CanvasState",
    "CanvasStateTracker",
    "EditorBridge",
    "GimpBridge",
    "KritaBridge",
    "LauncherError",
    "LayerState",
    "find_gimp_binary",
    "launch_and_wait",
]
