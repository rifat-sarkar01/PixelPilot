"""Krita bridge - connects to the PixelPilot Krita plugin over JSON/TCP."""

from __future__ import annotations

import socket

from pixelpilot.bridge.base import BridgeConnectionError, SocketEditorBridge


class KritaBridge(SocketEditorBridge):
    """Talk to the PixelPilot Krita plugin (default port 10020)."""

    def __init__(self, host: str = "localhost", port: int = 10020, timeout: float = 30.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)

    def connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise BridgeConnectionError(
                f"Could not connect to Krita plugin at {self.host}:{self.port}. "
                "Is Krita running with the PixelPilot docker enabled?"
            ) from exc
