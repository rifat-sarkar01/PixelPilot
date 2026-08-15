"""PixelPilot Krita plugin - socket bridge into Krita's PyKrita environment.

Same JSON-over-TCP protocol as the GIMP plugin (``PXPT1`` magic + 4-byte length).
Runs inside Krita via the pykrita plugin loader.
"""

import json
import socket
import struct
import threading

try:
    from krita import Krita
except Exception:  # noqa: S110, BLE001 - imported outside Krita (e.g. for linting)
    pass

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

PROTOCOL_MAGIC = b"PXPT1"
HOST = "127.0.0.1"
PORT = 10020


def _send(sock: socket.socket, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    sock.sendall(PROTOCOL_MAGIC + struct.pack(">I", len(data)) + data)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Client disconnected")
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(sock: socket.socket) -> dict:
    magic = _recv_exact(sock, len(PROTOCOL_MAGIC))
    if magic != PROTOCOL_MAGIC:
        raise ValueError(f"Bad magic: {magic!r}")
    length = struct.unpack(">I", _recv_exact(sock, 4))[0]
    return json.loads(_recv_exact(sock, length).decode("utf-8"))


def _document():
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        raise RuntimeError("No active document open.")
    return app, doc


def _canvas_state() -> dict:
    _, doc = _document()
    layers = []
    root = doc.rootNode()

    def walk(node, depth=0):
        name = node.name() if hasattr(node, "name") else str(node)
        layers.append(
            {
                "name": name,
                "type": node.type() if hasattr(node, "type") else "unknown",
                "visible": node.visible() if hasattr(node, "visible") else True,
                "opacity": int((node.opacity() if hasattr(node, "opacity") else 1.0) * 100),
                "blend_mode": node.blendingMode() if hasattr(node, "blendingMode") else "normal",
                "locked": False,
            }
        )
        if hasattr(node, "childNodes"):
            for child in node.childNodes():
                walk(child, depth + 1)

    walk(root)
    active = doc.activeNode()
    return {
        "image_path": doc.fileName() if hasattr(doc, "fileName") else None,
        "dimensions": [doc.width(), doc.height()],
        "color_mode": str(doc.colorModel()) if hasattr(doc, "colorModel") else "RGBA",
        "bit_depth": 8,
        "dpi": doc.resolution() if hasattr(doc, "resolution") else 72,
        "layers": layers,
        "active_layer": active.name() if active and hasattr(active, "name") else None,
        "has_selection": False,
        "selection_bounds": None,
        "undo_depth": 0,
    }


def _handle(cmd: dict) -> dict:
    name = cmd.get("cmd")
    if name == "execute":
        try:
            code = cmd.get("code", "")
            compiled = compile(code, "<pixelpilot-plugin>", "exec")
            namespace = {"Krita": Krita, "Krita_instance": Krita.instance, "__builtins__": __builtins__}
            exec(compiled, namespace)  # noqa: S102 - core purpose: run generated scripts
            return {"status": "ok", "result": None}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    if name == "canvas_state":
        try:
            return {"status": "ok", "result": _canvas_state()}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
    if name == "undo":
        doc = _document()[1]
        doc.undo()
        return {"status": "ok", "result": None}
    if name == "redo":
        doc = _document()[1]
        doc.redo()
        return {"status": "ok", "result": None}
    if name == "screenshot":
        return {"status": "error", "error": "Krita screenshot capture not implemented in scaffold."}
    return {"status": "error", "error": f"Unknown command: {name}"}


def _handle_client(conn: socket.socket) -> None:
    try:
        while True:
            cmd = _read_frame(conn)
            _send(conn, _handle(cmd))
    except (ConnectionError, OSError, ValueError):
        pass
    finally:
        conn.close()


def _server_loop() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    while True:
        conn, _ = server.accept()
        threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()


def start_bridge() -> None:
    if any(t.name == "pixelpilot-bridge" for t in threading.enumerate()):
        return
    thread = threading.Thread(target=_server_loop, name="pixelpilot-bridge", daemon=True)
    thread.start()


class PixelPilotDocker(QWidget):
    """Minimal docker showing the bridge status."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"PixelPilot bridge running on port {PORT}"))
        self.setLayout(layout)


class Extension:
    """Krita extension entry point."""

    def __init__(self, parent):
        self.parent = parent

    def setup(self):
        pass

    def createActions(self, window):
        pass


# Krita's pykrita loader looks for a module-level `Krita.instance().addExtension(...)`
# registration in the extension's `init.py`; the docker factory is referenced from
# pixelpilot.desktop via `DockerManager` in the parent package. For the scaffold this
# module provides the socket bridge plus the docker widget class.
