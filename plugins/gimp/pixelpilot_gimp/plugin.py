#!/usr/bin/env python2
"""PixelPilot GIMP plugin - socket bridge into GIMP's Python-Fu environment.

Protocol: JSON-over-TCP with a ``PXPT1`` magic prefix and a 4-byte big-endian length.
Supports commands:
  execute       - run a Python-Fu script, return captured stdout
  canvas_state  - structured canvas info for :class:`CanvasState`
  screenshot    - current canvas as base64 PNG
  undo / redo   - editor undo / redo

This module runs *inside* GIMP's Python-Fu interpreter (Python 2.7 for GIMP 2.10),
so it deliberately avoids Python-3-only syntax (annotations, f-strings, daemon kwarg).
It is not importable outside a GIMP Python runtime.
"""

import base64
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time

try:
    from StringIO import StringIO  # Python 2 - io.StringIO there rejects str
except ImportError:  # pragma: no cover - Python 3
    from io import StringIO

try:
    from gimpfu import *
except Exception:  # noqa: S110, BLE001 - imported outside GIMP (e.g. for linting)
    pass


# The code model sometimes emits legacy / GIMP-3-style constant names that do
# not exist in GIMP 2.10's gimpfu. Provide forgiving aliases so generated
# scripts still run.
for _alias, _target in (
    ("FG_COLOR_FILL", "FOREGROUND_FILL"),
    ("BG_COLOR_FILL", "BACKGROUND_FILL"),
    ("LAYER_MODE_NORMAL", "NORMAL_MODE"),
    ("LAYER_MODE_MULTIPLY", "MULTIPLY_MODE"),
    ("LAYER_MODE_SCREEN", "SCREEN_MODE"),
    ("LAYER_MODE_OVERLAY", "OVERLAY_MODE"),
    ("SELECT_REGION", "ADD"),
    ("CHANNEL_OP_ADD", "ADD"),
):
    if _target in globals():
        globals()[_alias] = globals()[_target]

# Constants the model emits that do not exist in GIMP 2.10 gimpfu at all
# (values confirmed against the live 2.10 PDB). Injected into the exec
# namespace; `from gimpfu import *` only adds names gimpfu defines, so these
# survive the star-import.
ALIAS_CONSTANTS = {
    "FG_BG_LINEAR_BLEND": 0,                  # GIMP 3 name -> BLEND_FG_BG_RGB
    "FG_BG_RGB_BLEND": 0,                     # older GIMP 2.x name
    "FG_BG_HSV_CLOCKWISE_BLEND": 1,           # -> BLEND_FG_BG_HSV
    "FG_BG_HSV_COUNTER_CLOCKWISE_BLEND": 1,   # -> BLEND_FG_BG_HSV
    "FG_BG_HSV_BLEND": 1,                     # -> BLEND_FG_BG_HSV
    "BLEND_NORMAL": 0,                        # invented blend-mode name
    "BLEND_LINEAR": 0,                        # invented blend-mode name
    "PAINT_MODE_NORMAL": 0,
    "GRADIENT_SOLID": 1,
    "CHANNEL_OP_INTERSECT": 3,
    "REPLACE": 2,                             # selection operation (CHANNEL_OP_REPLACE)
    "SELECTION_REPLACE": 2,
    "SELECTION_ADD": 0,
    "SELECTION_SUBTRACT": 1,
    "SELECTION_INTERSECT": 3,
    "FROM_CENTER": 1,
}

PROTOCOL_MAGIC = b"PXPT1"
HOST = "127.0.0.1"
PORT = 10010


class _PdbAlias(object):
    """Proxy around the GIMP ``pdb`` that maps commonly-hallucinated PDB names
    to the real GIMP 2.10 procedures, so generated scripts still run."""

    def __init__(self, real_pdb):
        self._pdb = real_pdb

    def __getattr__(self, name):
        if name == "gimp_image_get_width":
            return self._pdb.gimp_image_width
        if name == "gimp_image_get_height":
            return self._pdb.gimp_image_height
        if name == "gimp_selection_ellipse":
            return self._selection_ellipse
        if name == "gimp_selection_rectangle":
            return self._selection_rectangle
        if name == "gimp_ellipse_select":
            return self._ellipse_select
        if name == "gimp_rectangle_select":
            return self._rectangle_select
        if name == "gimp_layer_set_offset":
            return self._pdb.gimp_layer_set_offsets
        if name == "gimp_edit_blend":
            return self._edit_blend
        if name == "gimp_pencil":
            return self._pencil
        return getattr(self._pdb, name)

    def _find_image(self, args):
        for a in args:
            if isinstance(a, gimp.Image):
                return a
        return gimp.image_list()[0]

    def _selection_ellipse(self, *args, **kwargs):
        return self._image_select("gimp_image_select_ellipse", *args, **kwargs)

    def _selection_rectangle(self, *args, **kwargs):
        return self._image_select("gimp_image_select_rectangle", *args, **kwargs)

    def _ellipse_select(self, *args, **kwargs):
        return self._flex_select("gimp_image_select_ellipse", *args, **kwargs)

    def _rectangle_select(self, *args, **kwargs):
        return self._flex_select("gimp_image_select_rectangle", *args, **kwargs)

    def _flex_select(self, proc, *args, **kwargs):
        """Accept the real PDB call shape or the model's common wrong shapes.

        The model often emits ``gimp_ellipse_select(canvas_w, canvas_h, w, h,
        cx, cy, antialias, from_center)`` (GIMP-3 style). Rebuild a correct
        2.10 call, defaulting to replace-mode and handling from-center.
        """
        if args and isinstance(args[0], gimp.Image):
            return getattr(self._pdb, proc)(*args)
        image = self._find_image(args)
        nums = [a for a in args
                if not isinstance(a, gimp.Image) and not isinstance(a, gimp.Item)]
        if len(nums) == 4:
            return self._image_select(proc, *args, **kwargs)
        if len(nums) == 8 and not isinstance(nums[7], float):
            w, h = int(nums[2]), int(nums[3])
            x, y = int(nums[4]), int(nums[5])
            if nums[7]:
                x -= w // 2
                y -= h // 2
            return getattr(self._pdb, proc)(
                image, CHANNEL_OP_REPLACE, x, y, w, h
            )
        if len(nums) == 6:
            w, h = int(nums[0]), int(nums[1])
            x, y = int(nums[2]), int(nums[3])
            if nums[5]:
                x -= w // 2
                y -= h // 2
            return getattr(self._pdb, proc)(
                image, CHANNEL_OP_REPLACE, x, y, w, h
            )
        raise TypeError("could not interpret arguments for %s" % proc)

    def _edit_blend(self, *args, **kwargs):
        """Accept the real 16-arg gimp_edit_blend call or the model's shorter
        variants, filling in defaults (gradient endpoints default to the full
        drawable diagonal)."""
        kwargs.pop("run_mode", None)
        if not args:
            raise TypeError("gimp_edit_blend needs a drawable")
        drawable = args[0]
        nums = [a for a in args[1:]
                if not isinstance(a, gimp.Image) and not isinstance(a, gimp.Item)]
        if kwargs:
            kw = dict(kwargs)
            get = lambda *names: next((kw.pop(n) for n in names if n in kw), None)
            blend = get("blend_mode", "blend-mode", "blend") or 0
            paint = get("paint_mode", "paint-mode", "paint") or 0
            grad = get("gradient_type", "gradient-type", "gradient") or 0
            opacity = get("opacity") or 100
            offset = get("offset") or 0
            repeat = get("repeat") or 0
            rev = get("reverse")
            reverse = rev if rev is not None else True
            ss = get("supersample")
            supersample = bool(ss) if ss is not None else False
            maxdepth = get("max_depth", "max-depth") or 3
            srcx = get("src_x", "src-x", "x1") or 0
            srcy = get("src_y", "src-y", "y1") or 0
            dstx = get("dst_x", "dst-x", "x2") or int(drawable.width)
            dsty = get("dst_y", "dst-y", "y2") or int(drawable.height)
        else:
            non_bools = [a for a in nums if not isinstance(a, bool)]
            bools = [a for a in nums if isinstance(a, bool)]
            if not bools:
                reverse = True
                supersample = False
            elif len(bools) == 1:
                reverse = bool(bools[0])
                supersample = False
            else:
                reverse = bool(bools[0])
                supersample = bool(bools[1])
            slots = [int(a) for a in non_bools]
            if len(slots) >= 9:
                # Full positional form: blend, paint, grad, opacity, offset,
                # repeat, max_depth, src_x, src_y, dst_x, dst_y.
                def s(i, default):
                    return slots[i] if len(slots) > i else default
                blend = s(0, 0)
                paint = s(1, 0)
                grad = s(2, 0)
                opacity = s(3, 100)
                offset = s(4, 0)
                repeat = s(5, 0)
                maxdepth = s(6, 3)
                srcx = s(7, 0)
                srcy = s(8, 0)
                dstx = s(9, int(drawable.width))
                dsty = s(10, int(drawable.height))
            else:
                # Short model forms drop paint_mode and offset:
                #   (blend, gradient, opacity[, repeat[, ...]])
                blend = slots[0] if len(slots) > 0 else 0
                grad = slots[1] if len(slots) > 1 else 0
                opacity = slots[2] if len(slots) > 2 else 100
                repeat = slots[3] if len(slots) > 3 else 0
                paint = 0
                offset = 0
                maxdepth = 3
                srcx = 0
                srcy = 0
                dstx = int(drawable.width)
                dsty = int(drawable.height)
        return self._pdb.gimp_edit_blend(
            drawable, int(blend), int(paint), int(grad), int(opacity), int(offset),
            int(repeat), bool(reverse), bool(supersample), int(maxdepth),
            int(srcx), int(srcy), int(dstx), int(dsty), 0, 0
        )

    def _pencil(self, *args, **kwargs):
        """gimp_pencil(drawable, num_points, points) where points may be a flat
        list or a list of (x, y) tuples - flatten tuples to the flat form."""
        if len(args) == 3:
            drawable, num, points = args
            flat = []
            for p in points:
                if isinstance(p, (list, tuple)):
                    flat.extend(int(v) for v in p)
                else:
                    flat.append(int(p))
            return self._pdb.gimp_pencil(drawable, len(flat) // 2, flat)
        return self._pdb.gimp_pencil(*args)

    def _image_select(self, proc, *args, **kwargs):
        kwargs.pop("run_mode", None)
        if kwargs:
            x = int(kwargs.pop("x", 0))
            y = int(kwargs.pop("y", 0))
            width = int(kwargs.pop("width", 0))
            height = int(kwargs.pop("height", 0))
            image = kwargs.pop("image", None)
        else:
            nums = [a for a in args
                    if not isinstance(a, gimp.Image) and not isinstance(a, gimp.Item)]
            if len(nums) < 4:
                raise TypeError("expected x, y, width, height")
            x, y, width, height = [int(n) for n in nums[-4:]]
            image = None
        if image is None:
            image = self._find_image(args)
        return getattr(self._pdb, proc)(image, CHANNEL_OP_REPLACE, x, y, width, height)


# Generated scripts start with "from gimpfu import *", which would otherwise
# re-bind `pdb` to the raw object and bypass the alias proxy. Patch gimpfu so
# the star-import picks up the proxy.
try:
    import gimpfu
    if hasattr(gimpfu, "pdb"):
        gimpfu.pdb = _PdbAlias(gimpfu.pdb)
except Exception:  # noqa: BLE001 - outside GIMP
    pass


# ---------------------------------------------------------------------- helpers

def _send(sock, payload):
    data = json.dumps(payload).encode("utf-8")
    sock.sendall(PROTOCOL_MAGIC + struct.pack(">I", len(data)) + data)


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise IOError("Client disconnected")
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(sock):
    magic = _recv_exact(sock, len(PROTOCOL_MAGIC))
    if magic != PROTOCOL_MAGIC:
        raise ValueError("Bad magic: %r" % (magic,))
    length = struct.unpack(">I", _recv_exact(sock, 4))[0]
    return json.loads(_recv_exact(sock, length).decode("utf-8"))


# ----------------------------------------------------------------------- canvas

DEFAULT_CANVAS_WIDTH = 1024
DEFAULT_CANVAS_HEIGHT = 768


def _ensure_image():
    """Guarantee at least one open image before a script runs.

    A freshly-started GIMP session (or one where the last image was closed)
    has zero open images. Generated scripts are told to grab the current one
    via `gimp.image_list()[0]` (see OUTPUT_FORMAT in prompts/gimp.py), which
    raises IndexError immediately if that list is empty - the script never
    gets a chance to draw anything. Rather than relying on every generated
    script to defensively create-or-reuse an image, guarantee the precondition
    here so `image_list()[0]` is always safe by the time user code runs.
    """
    images = gimp.image_list()
    if images:
        return images[0]
    image = pdb.gimp_image_new(DEFAULT_CANVAS_WIDTH, DEFAULT_CANVAS_HEIGHT, RGB)
    layer = pdb.gimp_layer_new(
        image, DEFAULT_CANVAS_WIDTH, DEFAULT_CANVAS_HEIGHT,
        RGB_IMAGE, "Background", 100.0, NORMAL_MODE,
    )
    pdb.gimp_image_insert_layer(image, layer, None, 0)
    pdb.gimp_context_set_background((255, 255, 255))
    pdb.gimp_image_select_rectangle(
        image, CHANNEL_OP_REPLACE, 0, 0, DEFAULT_CANVAS_WIDTH, DEFAULT_CANVAS_HEIGHT
    )
    pdb.gimp_edit_fill(layer, BACKGROUND_FILL)
    pdb.gimp_selection_none(image)
    pdb.gimp_display_new(image)
    pdb.gimp_displays_flush()
    return image


def _current_image():
    images = gimp.image_list()
    if not images:
        raise RuntimeError("No open images.")
    return images[0]


def _mode_name(value):
    for name, val in globals().items():
        if name.endswith("_MODE") and val == value:
            return name.rsplit("_MODE", 1)[0].lower()
    return "normal"


def _canvas_state():
    images = gimp.image_list()
    if not images:
        return {
            "image_path": None,
            "dimensions": [0, 0],
            "color_mode": "RGB",
            "bit_depth": 8,
            "dpi": 72,
            "layers": [],
            "active_layer": None,
            "has_selection": False,
            "selection_bounds": None,
            "undo_depth": 0,
        }
    image = images[0]
    layers = []
    for layer in image.layers:
        layers.append(
            {
                "name": layer.name,
                "type": "raster",
                "visible": bool(layer.visible),
                "opacity": layer.opacity,
                "blend_mode": _mode_name(layer.mode) if hasattr(layer, "mode") else "normal",
                "locked": False,
            }
        )
    return {
        "image_path": getattr(image, "filename", None),
        "dimensions": [image.width, image.height],
        "color_mode": "RGB" if image.base_type == 0 else "RGBA",
        "bit_depth": 8,
        "dpi": getattr(image, "resolution_x", 72),
        "layers": layers,
        "active_layer": image.active_layer.name if image.active_layer else None,
        "has_selection": bool(pdb.gimp_selection_is_empty(image) is False),
        "selection_bounds": None,
        "undo_depth": 0,
    }


def _screenshot():
    image = _ensure_image()  # same guarantee as execute - screenshot must never
                              # crash just because nothing has been drawn yet
    copy = pdb.gimp_image_duplicate(image)
    tmp = tempfile.mkdtemp(prefix="pixelpilot_")
    try:
        flat = pdb.gimp_image_flatten(copy)
        path = os.path.join(tmp, "pixelpilot_canvas.png")
        pdb.gimp_file_save(copy, flat, path, path)
        with open(path, "rb") as fh:
            data = fh.read()
        return base64.b64encode(data).decode("ascii")
    finally:
        shutil.rmtree(tmp)
        pdb.gimp_image_delete(copy)


# -------------------------------------------------------------------- dispatch

def _handle(cmd):
    name = cmd.get("cmd")
    if name == "execute":
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            _ensure_image()  # scripts assume an image already exists - guarantee it
            code = cmd.get("code", "")
            # Python-Fu 2.10 runs Python 2.7, where `1/4 == 0` (integer
            # division). Generated scripts assume Python 3 semantics, so force
            # true division; `//` still floors explicitly.
            code = "from __future__ import division\n" + code
            compiled = compile(code, "<pixelpilot-plugin>", "exec")
            ns = dict(globals())
            for _name, _value in ALIAS_CONSTANTS.items():
                ns.setdefault(_name, _value)
            exec(compiled, ns)
            result = sys.stdout.getvalue()
            return {"status": "ok", "result": result}
        except Exception as exc:  # noqa: BLE001 - must report script failures
            return {"status": "error", "error": "%s: %s" % (type(exc).__name__, exc)}
        finally:
            sys.stdout = old_stdout
    if name == "canvas_state":
        try:
            return {"status": "ok", "result": _canvas_state()}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
    if name == "screenshot":
        try:
            return {"status": "ok", "result": _screenshot()}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
    if name == "undo":
        pdb.gimp_undo(_current_image())
        return {"status": "ok", "result": None}
    if name == "redo":
        pdb.gimp_redo(_current_image())
        return {"status": "ok", "result": None}
    return {"status": "error", "error": "Unknown command: %s" % name}


def _handle_client(conn):
    try:
        while True:
            cmd = _read_frame(conn)
            response = _handle(cmd)
            _send(conn, response)
    except (IOError, OSError, ValueError):
        pass
    finally:
        conn.close()


def _server_loop():
    # Self-healing accept loop: if the socket ever errors (a generated script
    # can crash the bridge thread), rebind and keep serving instead of dying.
    while True:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # No SO_REUSEADDR: on Windows it allows two sockets to bind the
            # same port (e.g. a stale bridge process), which routes connections
            # to a dying socket.
            server.bind((HOST, PORT))
            server.listen(5)
            while True:
                conn, _ = server.accept()
                threading.Thread(target=_handle_client, args=(conn,)).start()
        except Exception:  # noqa: BLE001 - keep the bridge alive at all costs
            try:
                server.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1)


def start_bridge():
    """Start the bridge in a background thread (idempotent)."""
    for t in threading.enumerate():
        if t.name == "pixelpilot-bridge":
            return
    thread = threading.Thread(target=_server_loop, name="pixelpilot-bridge")
    if hasattr(thread, "setDaemon"):
        thread.setDaemon(True)  # Python 2
    else:
        thread.daemon = True  # Python 3
    thread.start()


def plugin_main():
    start_bridge()
    # Block forever: the procedure's host process must stay alive to keep the
    # bridge socket (and the ability to call pdb) around for PixelPilot.
    while True:
        time.sleep(1)


# The bridge is started ONLY from plugin_main() (i.e. when the registered
# procedure is invoked via the launcher's -b batch expression). It must NOT
# auto-start at import time: GIMP imports this script during its plugin scan
# in a short-lived process that dies, and its socket on port 10010 would then
# answer the first PixelPilot connection with a reset.


if __name__ == "__main__":
    register(
        "python-fu-pixelpilot-bridge",
        "PixelPilot bridge server",
        "Listens for PixelPilot commands and executes Python-Fu in GIMP.",
        "PixelPilot",
        "MIT",
        "2026",
        "PixelPilot Bridge",
        "*",
        [],
        [],
        plugin_main,
    )
    main()
