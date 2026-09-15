"""GIMP bridge - connects to the PixelPilot GIMP plugin over JSON/TCP."""

from __future__ import annotations

import socket

from pixelpilot.bridge.base import BridgeConnectionError, SocketEditorBridge


class GimpBridge(SocketEditorBridge):
    """Talk to the PixelPilot GIMP plugin (default port 10010)."""

    def __init__(self, host: str = "localhost", port: int = 10010, timeout: float = 30.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)

    def connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise BridgeConnectionError(
                f"Could not connect to GIMP plugin at {self.host}:{self.port}. "
                "Is GIMP running with the PixelPilot plugin enabled?"
            ) from exc

    def get_pdb_catalog(self) -> set[str]:
        """Return procedure names registered by this exact GIMP instance.

        GIMP's PDB differs across versions and plug-in installations, so the
        running editor is the authoritative source for API validation.
        """
        procedures = self._rpc("pdb_catalog")
        if not isinstance(procedures, list) or not all(
            isinstance(name, str) for name in procedures
        ):
            raise BridgeConnectionError("GIMP returned an invalid PDB catalog.")
        return set(procedures)
