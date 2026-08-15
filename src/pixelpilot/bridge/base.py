"""Unified editor-bridge interface (implementation_plan.md §4.4.3).

Bridges talk to a companion plugin running inside GIMP/Krita over a simple
JSON-over-TCP protocol. The plugin executes Python in the editor's own
environment, so scripts have full access to ``gimp`` / ``Krita``.
"""

from __future__ import annotations

import json
import socket
import struct
from abc import ABC, abstractmethod
from typing import Any

PROTOCOL_MAGIC = b"PXPT1"


class BridgeConnectionError(RuntimeError):
    """Could not connect to the editor bridge."""


class BridgeExecutionError(RuntimeError):
    """The editor plugin reported an execution error."""


class EditorBridge(ABC):
    """Abstract bridge; concrete implementations speak to a specific editor."""

    host: str = "localhost"
    port: int = 10010

    def __init__(self, host: str | None = None, port: int | None = None,
                 timeout: float = 30.0) -> None:
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------ lifecycle

    @abstractmethod
    def connect(self) -> None:
        """Establish the connection; raise :class:`BridgeConnectionError` on failure."""

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def is_connected(self) -> bool:
        return self._sock is not None

    # ------------------------------------------------------------- execution

    @abstractmethod
    def execute_script(self, code: str) -> dict[str, Any]:
        """Execute raw editor code; return ``{"result": ...}`` or raise."""

    @abstractmethod
    def get_canvas_state(self) -> dict[str, Any]:
        """Return structured canvas info (see :class:`CanvasState`)."""

    @abstractmethod
    def capture_screenshot(self) -> bytes:
        """Return the current canvas as PNG bytes."""

    # ---------------------------------------------------------- canvas queries

    @abstractmethod
    def undo(self) -> dict[str, Any]:
        """Undo the last editor operation."""

    @abstractmethod
    def redo(self) -> dict[str, Any]:
        """Redo the last undone operation."""

    # ------------------------------------------------------------- convenience

    def get_image_info(self) -> dict[str, Any]:
        state = self.get_canvas_state()
        return {
            "image_path": state.get("image_path"),
            "dimensions": state.get("dimensions"),
            "color_mode": state.get("color_mode"),
            "bit_depth": state.get("bit_depth"),
            "dpi": state.get("dpi"),
        }

    def get_layers(self) -> list[dict[str, Any]]:
        return self.get_canvas_state().get("layers", [])


class SocketEditorBridge(EditorBridge):
    """JSON-over-TCP bridge shared by the GIMP and Krita plugins.

    Frame format: ``PXPT1`` magic + 4-byte big-endian length + UTF-8 JSON.
    """

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._sock is None:
            # Lazy reconnect: the plugin's bridge thread is self-healing, so a
            # dropped connection can often be re-established transparently.
            try:
                self.connect()
            except BridgeConnectionError:
                raise BridgeConnectionError("Bridge is not connected - call connect() first.") from None
        data = json.dumps(payload).encode("utf-8")
        frame = PROTOCOL_MAGIC + struct.pack(">I", len(data)) + data
        try:
            self._sock.sendall(frame)
        except OSError as exc:
            self.disconnect()
            raise BridgeConnectionError(f"Lost connection to editor: {exc}") from exc
        return self._recv()

    def _recv(self) -> dict[str, Any]:
        if self._sock is None:
            raise BridgeConnectionError("Bridge is not connected.")
        try:
            magic = self._sock.recv(len(PROTOCOL_MAGIC))
            if magic != PROTOCOL_MAGIC:
                raise BridgeConnectionError(f"Bad bridge protocol magic: {magic!r}")
            length = struct.unpack(">I", self._recv_exact(4))[0]
            body = self._recv_exact(length)
        except (OSError, struct.error) as exc:
            self.disconnect()
            raise BridgeConnectionError(f"Failed to read from editor: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BridgeConnectionError(f"Malformed bridge response: {exc}") from exc

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        assert self._sock is not None
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise BridgeConnectionError("Connection closed while reading frame.")
            buf.extend(chunk)
        return bytes(buf)

    def _rpc(self, cmd: str, **kwargs: Any) -> Any:
        response = self._send({"cmd": cmd, **kwargs})
        if response.get("status") == "error":
            raise BridgeExecutionError(response.get("error", "Unknown bridge error"))
        return response.get("result")

    # ------------------------------------------------------------- execution

    def execute_script(self, code: str) -> dict[str, Any]:
        return self._rpc("execute", code=code)

    def get_canvas_state(self) -> dict[str, Any]:
        return self._rpc("canvas_state")

    def capture_screenshot(self) -> bytes:
        import base64

        encoded = self._rpc("screenshot")
        return base64.b64decode(encoded)

    def undo(self) -> dict[str, Any]:
        return self._rpc("undo")

    def redo(self) -> dict[str, Any]:
        return self._rpc("redo")
