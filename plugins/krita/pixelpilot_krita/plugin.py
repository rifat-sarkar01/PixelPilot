"""PixelPilot Krita plugin - socket bridge into Krita's PyKrita environment.

Protocol: JSON-over-TCP with a ``PXPT1`` magic prefix + 4-byte big-endian
length, identical to the GIMP plugin so the same SocketEditorBridge client
works for both editors.

Supported commands
------------------
execute       - exec() a Python script in Krita's namespace, return result
canvas_state  - structured canvas info (dimensions, layers, active layer …)
screenshot    - current canvas flattened to base64-encoded PNG bytes
undo          - Krita document undo
redo          - Krita document redo

Installation (automatic via PixelPilot launcher)
-------------------------------------------------
The PixelPilot CLI auto-deploys this package into::

    %APPDATA%/krita/pykrita/pixelpilot_krita/        (Windows)
    ~/Library/Application Support/krita/pykrita/     (macOS)
    ~/.local/share/krita/pykrita/                    (Linux)

along with ``pixelpilot_krita.desktop`` and restarts Krita.
You can also do it manually - see README.md.
"""

from __future__ import annotations

import base64
import io
import json
import socket
import struct
import threading
import traceback

try:
    from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita
    _KRITA_AVAILABLE = True
except Exception:  # noqa: BLE001 - imported outside Krita (linting / tests)
    _KRITA_AVAILABLE = False

try:
    from PyQt5.QtCore import QTimer, pyqtSignal
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (
        QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget
    )
    _QT_AVAILABLE = True
except Exception:  # noqa: BLE001
    _QT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
PROTOCOL_MAGIC = b"PXPT1"
HOST = "127.0.0.1"
PORT = 10020

# ---------------------------------------------------------------------------
# Low-level framing helpers
# ---------------------------------------------------------------------------

def _send_frame(sock: socket.socket, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sock.sendall(PROTOCOL_MAGIC + struct.pack(">I", len(data)) + data)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Client disconnected mid-frame")
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(sock: socket.socket) -> dict:
    magic = _recv_exact(sock, len(PROTOCOL_MAGIC))
    if magic != PROTOCOL_MAGIC:
        raise ValueError(f"Bad magic: {magic!r}")
    length = struct.unpack(">I", _recv_exact(sock, 4))[0]
    body = _recv_exact(sock, length)
    return json.loads(body.decode("utf-8"))

# ---------------------------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------------------------

def _active_document():
    if not _KRITA_AVAILABLE:
        raise RuntimeError("Not running inside Krita.")
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        raise RuntimeError("No active document is open in Krita.")
    return app, doc


def _canvas_state() -> dict:
    app, doc = _active_document()
    layers = []

    def _walk(node):
        try:
            layers.append({
                "name": node.name(),
                "type": node.type(),
                "visible": node.visible(),
                "opacity": round(node.opacity() / 255 * 100),
                "blend_mode": node.blendingMode(),
                "locked": node.locked(),
            })
        except Exception:  # noqa: BLE001
            pass
        try:
            for child in node.childNodes():
                _walk(child)
        except Exception:  # noqa: BLE001
            pass

    try:
        _walk(doc.rootNode())
    except Exception:  # noqa: BLE001
        pass

    active = None
    try:
        active_node = doc.activeNode()
        active = active_node.name() if active_node else None
    except Exception:  # noqa: BLE001
        pass

    sel = None
    sel_bounds = None
    try:
        s = doc.selection()
        if s is not None:
            sel = True
            sel_bounds = [s.x(), s.y(), s.width(), s.height()]
    except Exception:  # noqa: BLE001
        pass

    return {
        "image_path": doc.fileName() or None,
        "dimensions": [doc.width(), doc.height()],
        "color_mode": doc.colorModel() or "RGBA",
        "bit_depth": doc.colorDepth() or "U8",
        "dpi": doc.resolution(),
        "layers": layers,
        "active_layer": active,
        "has_selection": bool(sel),
        "selection_bounds": sel_bounds,
        "undo_depth": 0,
    }


def _screenshot_png() -> str:
    """Export the flattened canvas as base64-encoded PNG bytes."""
    _app, doc = _active_document()
    # Krita's thumbnail() returns a QImage; exportImage writes to a path.
    # We use a temp in-memory approach via QByteArray.
    try:
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        from PyQt5.QtGui import QImage

        # Flatten the document to a QImage
        img: QImage = doc.thumbnail(doc.width(), doc.height())
        if img is None or img.isNull():
            raise RuntimeError("Could not generate thumbnail from Krita document.")

        # Encode to PNG in memory
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        buf.close()

        return base64.b64encode(bytes(ba)).decode("ascii")
    except Exception:
        # Fallback: export to a temp file
        import os
        import tempfile
        tmp = tempfile.mktemp(suffix=".png")
        try:
            doc.exportImage(tmp, doc.exportConfiguration())
            with open(tmp, "rb") as fh:
                return base64.b64encode(fh.read()).decode("ascii")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

def _handle_command(cmd: dict) -> dict:
    name = cmd.get("cmd", "")

    if name == "execute":
        code = cmd.get("code", "")
        try:
            namespace: dict = {}
            if _KRITA_AVAILABLE:
                namespace["Krita"] = Krita
                namespace["Application"] = Krita.instance()
                namespace["Document"] = (
                    Krita.instance().activeDocument()
                    if Krita.instance().activeDocument() else None
                )
            compiled = compile(code, "<pixelpilot>", "exec")
            exec(compiled, namespace)  # noqa: S102 - intentional scripting
            result = namespace.get("_result")
            return {"status": "ok", "result": result}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"}

    if name == "canvas_state":
        try:
            return {"status": "ok", "result": _canvas_state()}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    if name == "screenshot":
        try:
            return {"status": "ok", "result": _screenshot_png()}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    if name == "undo":
        try:
            _, doc = _active_document()
            doc.undo()
            return {"status": "ok", "result": None}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    if name == "redo":
        try:
            _, doc = _active_document()
            doc.redo()
            return {"status": "ok", "result": None}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    return {"status": "error", "error": f"Unknown command: {name!r}"}

# ---------------------------------------------------------------------------
# TCP server
# ---------------------------------------------------------------------------

# Tracks how many clients are currently connected (for the docker UI).
_active_clients: int = 0
_active_clients_lock = threading.Lock()

# Called by the docker when the client count changes.
_on_client_change = None  # type: ignore[assignment]


def _handle_client(conn: socket.socket) -> None:
    global _active_clients
    with _active_clients_lock:
        _active_clients += 1
    try:
        if _on_client_change:
            _on_client_change(_active_clients)
    except Exception:  # noqa: BLE001
        pass

    try:
        while True:
            cmd = _read_frame(conn)
            reply = _handle_command(cmd)
            _send_frame(conn, reply)
    except (ConnectionError, OSError, ValueError, EOFError):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass
        with _active_clients_lock:
            _active_clients -= 1
        try:
            if _on_client_change:
                _on_client_change(_active_clients)
        except Exception:  # noqa: BLE001
            pass


def _server_loop() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, PORT))
    except OSError:
        return
    srv.listen(5)
    while True:
        try:
            conn, _addr = srv.accept()
        except OSError:
            break
        t = threading.Thread(target=_handle_client, args=(conn,), daemon=True)
        t.start()


def start_bridge() -> None:
    """Start the TCP bridge server thread (idempotent)."""
    for t in threading.enumerate():
        if t.name == "pixelpilot-krita-bridge":
            return  # Already running
    thread = threading.Thread(target=_server_loop, name="pixelpilot-krita-bridge", daemon=True)
    thread.start()

# ---------------------------------------------------------------------------
# Docker panel (shown inside Krita's docker system)
# ---------------------------------------------------------------------------

if _QT_AVAILABLE and _KRITA_AVAILABLE:

    class PixelPilotDocker(DockWidget):
        """Docker panel showing bridge status and live connection count."""

        # Signal emitted from background threads to update UI on the main thread
        _client_changed = pyqtSignal(int)

        def __init__(self):
            super().__init__()
            self.setWindowTitle("PixelPilot")
            self._build_ui()
            self._client_changed.connect(self._update_status_label)
            # Register callback so background threads can signal us
            global _on_client_change
            _on_client_change = self._on_client_count_changed
            # Refresh status every 2 s even if no connections change
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh)
            self._timer.start(2000)

        def _build_ui(self):
            root = QWidget()
            layout = QVBoxLayout()
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(6)

            # Title
            title = QLabel("PixelPilot Bridge")
            font = QFont()
            font.setBold(True)
            font.setPointSize(10)
            title.setFont(font)
            layout.addWidget(title)

            # Port info
            port_label = QLabel(f"Listening on  {HOST}:{PORT}")
            port_label.setStyleSheet("color: #888; font-size: 9pt;")
            layout.addWidget(port_label)

            # Status indicator
            self._status_label = QLabel("● Starting…")
            self._status_label.setStyleSheet("color: #f0a500; font-size: 9pt;")
            layout.addWidget(self._status_label)

            # Connection count
            self._conn_label = QLabel("Connections: 0")
            self._conn_label.setStyleSheet("color: #aaa; font-size: 9pt;")
            layout.addWidget(self._conn_label)

            # Divider hint
            hint = QLabel("Run  pixelpilot --editor krita  to connect.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #666; font-size: 8pt; margin-top: 4px;")
            layout.addWidget(hint)

            layout.addStretch()

            root.setLayout(layout)
            self.setWidget(root)

        def _on_client_count_changed(self, n: int):
            """Called from background thread - emit signal to update on main thread."""
            try:
                self._client_changed.emit(n)
            except Exception:  # noqa: BLE001
                pass

        def _update_status_label(self, n: int):
            if n > 0:
                self._status_label.setText("● Connected")
                self._status_label.setStyleSheet("color: #4caf50; font-size: 9pt;")
            else:
                self._status_label.setText("● Waiting for PixelPilot…")
                self._status_label.setStyleSheet("color: #f0a500; font-size: 9pt;")
            self._conn_label.setText(f"Connections: {n}")

        def _refresh(self):
            with _active_clients_lock:
                n = _active_clients
            self._update_status_label(n)

        def canvasChanged(self, canvas):
            pass  # Required override

else:
    # Fallback when running outside Krita (e.g. for tests / linting)
    class PixelPilotDocker:  # type: ignore[no-redef]
        pass

# ---------------------------------------------------------------------------
# Krita extension entry point
# ---------------------------------------------------------------------------

if _KRITA_AVAILABLE:

    class PixelPilotExtension(Krita.Extension if hasattr(Krita, "Extension") else object):  # type: ignore[misc]
        """Krita Extension: starts the bridge socket on Krita startup."""

        def __init__(self, parent):
            super().__init__(parent)

        def setup(self):
            pass

        def createActions(self, window):
            pass

    def _register():
        app = Krita.instance()
        if app is None:
            return
        start_bridge()
        try:
            factory = DockWidgetFactory(
                "PixelPilotDocker",
                DockWidgetFactoryBase.DockRight,
                PixelPilotDocker,
            )
            app.addDockWidgetFactory(factory)
        except Exception:  # noqa: BLE001
            pass

    # Krita calls the module-level `setup()` when the plugin is loaded.
    def setup():
        _register()

else:
    # Outside Krita - start bridge anyway (useful for testing the socket)
    start_bridge()
