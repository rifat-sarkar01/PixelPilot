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
    string_types = (str, unicode)
except NameError:
    string_types = (str,)

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


def _parse_color(val):
    if val is None:
        return None
    if isinstance(val, (tuple, list)):
        if len(val) >= 3:
            return tuple(int(x) for x in val[:3])
    if isinstance(val, string_types):
        s = val.strip().lstrip("#")
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        if len(s) == 3:
            return (int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16))
    return None


def _is_image(obj):
    if obj is None:
        return False
    try:
        if isinstance(obj, gimp.Image):
            return True
    except Exception:
        pass
    return hasattr(obj, "active_drawable") or hasattr(obj, "layers") or hasattr(obj, "base_type") or hasattr(obj, "filename")


def _is_drawable(obj):
    if obj is None:
        return False
    try:
        if isinstance(obj, gimp.Item):
            return True
    except Exception:
        pass
    return hasattr(obj, "drawable_id") or hasattr(obj, "is_layer") or hasattr(obj, "is_channel")


def _helper_add_rectangle(*args, **kwargs):
    image = kwargs.get("image")
    drawable = kwargs.get("drawable")
    op = kwargs.get("op", kwargs.get("operation", CHANNEL_OP_REPLACE))
    color = _parse_color(kwargs.get("color"))

    pos_args = list(args)
    if pos_args and _is_image(pos_args[0]):
        image = pos_args.pop(0)
    if pos_args and _is_drawable(pos_args[0]):
        drawable = pos_args.pop(0)

    if len(pos_args) == 5:
        c = _parse_color(pos_args[4])
        if c is not None:
            color = c
            pos_args.pop(4)

    if len(pos_args) >= 4:
        x, y, w, h = [int(v) for v in pos_args[:4]]
    else:
        x = int(kwargs.get("x", 0))
        y = int(kwargs.get("y", 0))
        w = int(kwargs.get("width", kwargs.get("w", 0)))
        h = int(kwargs.get("height", kwargs.get("h", 0)))

    if image is None:
        image = _ensure_image()
    if drawable is None:
        drawable = image.active_drawable if getattr(image, "active_drawable", None) else (image.layers[0] if getattr(image, "layers", None) else None)

    if color is not None:
        pdb.gimp_context_set_foreground(color)

    pdb.gimp_image_select_rectangle(image, op, x, y, w, h)
    if drawable is not None:
        pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)


def _helper_add_ellipse(*args, **kwargs):
    image = kwargs.get("image")
    drawable = kwargs.get("drawable")
    op = kwargs.get("op", kwargs.get("operation", CHANNEL_OP_REPLACE))
    color = _parse_color(kwargs.get("color"))

    pos_args = list(args)
    if pos_args and _is_image(pos_args[0]):
        image = pos_args.pop(0)
    if pos_args and _is_drawable(pos_args[0]):
        drawable = pos_args.pop(0)

    if len(pos_args) == 5:
        c = _parse_color(pos_args[4])
        if c is not None:
            color = c
            pos_args.pop(4)

    if len(pos_args) >= 4:
        x, y, w, h = [int(v) for v in pos_args[:4]]
    else:
        x = int(kwargs.get("x", 0))
        y = int(kwargs.get("y", 0))
        w = int(kwargs.get("width", kwargs.get("w", 0)))
        h = int(kwargs.get("height", kwargs.get("h", 0)))

    if image is None:
        image = _ensure_image()
    if drawable is None:
        drawable = image.active_drawable if getattr(image, "active_drawable", None) else (image.layers[0] if getattr(image, "layers", None) else None)

    if color is not None:
        pdb.gimp_context_set_foreground(color)

    pdb.gimp_image_select_ellipse(image, op, x, y, w, h)
    if drawable is not None:
        pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)


def _helper_add_circle(*args, **kwargs):
    image = kwargs.get("image")
    drawable = kwargs.get("drawable")
    op = kwargs.get("op", kwargs.get("operation", CHANNEL_OP_REPLACE))
    color = _parse_color(kwargs.get("color"))

    pos_args = list(args)
    if pos_args and _is_image(pos_args[0]):
        image = pos_args.pop(0)
    if pos_args and _is_drawable(pos_args[0]):
        drawable = pos_args.pop(0)

    if len(pos_args) == 4:
        c = _parse_color(pos_args[3])
        if c is not None:
            color = c
            pos_args.pop(3)

    if len(pos_args) >= 3:
        cx, cy, r = [int(v) for v in pos_args[:3]]
    else:
        cx = int(kwargs.get("cx", kwargs.get("x", 0)))
        cy = int(kwargs.get("cy", kwargs.get("y", 0)))
        r = int(kwargs.get("r", kwargs.get("radius", 0)))

    x = cx - r
    y = cy - r
    w = 2 * r
    h = 2 * r

    if image is None:
        image = _ensure_image()
    if drawable is None:
        drawable = image.active_drawable if getattr(image, "active_drawable", None) else (image.layers[0] if getattr(image, "layers", None) else None)

    if color is not None:
        pdb.gimp_context_set_foreground(color)

    pdb.gimp_image_select_ellipse(image, op, x, y, w, h)
    if drawable is not None:
        pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)


def _helper_draw_line(*args, **kwargs):
    drawable = kwargs.get("drawable")
    pos = list(args)
    if pos and _is_drawable(pos[0]):
        drawable = pos.pop(0)
    elif pos and _is_image(pos[0]):
        img = pos.pop(0)
        if pos and _is_drawable(pos[0]):
            drawable = pos.pop(0)
        else:
            drawable = getattr(img, "active_drawable", None)

    if drawable is None:
        img = _ensure_image()
        drawable = img.active_drawable

    color = _parse_color(kwargs.get("color"))
    if color is not None:
        pdb.gimp_context_set_foreground(color)

    if len(pos) == 1 and isinstance(pos[0], (list, tuple)):
        raw = pos[0]
    elif len(pos) >= 4:
        raw = pos[:4]
    else:
        raw = kwargs.get("points", [])

    flat = []
    for p in raw:
        if isinstance(p, (list, tuple)):
            flat.extend(int(v) for v in p)
        else:
            flat.append(int(p))

    if len(flat) >= 4 and drawable is not None:
        try:
            pdb.gimp_pencil(drawable, flat)
        except Exception:
            pdb.gimp_pencil(drawable, len(flat) // 2, flat)


def _helper_add_polygon(*args, **kwargs):
    image = kwargs.get("image")
    drawable = kwargs.get("drawable")
    op = kwargs.get("op", kwargs.get("operation", CHANNEL_OP_REPLACE))
    color = _parse_color(kwargs.get("color"))

    pos = list(args)
    if pos and _is_image(pos[0]):
        image = pos.pop(0)
    if pos and _is_drawable(pos[0]):
        drawable = pos.pop(0)

    if pos and len(pos) >= 1 and (
        pos[0] in (0, 1, 2, 3)
        or (isinstance(pos[0], string_types) and pos[0] in (
            "CHANNEL_OP_REPLACE", "CHANNEL_OP_ADD", "CHANNEL_OP_SUBTRACT", "CHANNEL_OP_INTERSECT",
            "REPLACE", "ADD", "SUBTRACT", "INTERSECT"
        ))
    ):
        op = _parse_op(pos.pop(0))

    if len(pos) == 2 and isinstance(pos[0], (int, float)) and isinstance(pos[1], (list, tuple)):
        raw_points = pos[1]
    elif len(pos) == 1 and isinstance(pos[0], (list, tuple)):
        raw_points = pos[0]
    elif len(pos) >= 2 and all(isinstance(v, (int, float)) for v in pos):
        raw_points = pos
    else:
        raw_points = kwargs.get("points", kwargs.get("segs", []))

    flat = []
    for p in raw_points:
        if isinstance(p, (list, tuple)):
            flat.extend(float(v) for v in p)
        else:
            flat.append(float(p))

    if image is None:
        image = _ensure_image()
    if drawable is None:
        drawable = getattr(image, "active_drawable", None) or (image.layers[0] if getattr(image, "layers", None) else None)

    if color is not None:
        pdb.gimp_context_set_foreground(color)

    op_code = _parse_op(op)
    try:
        pdb.gimp_image_select_polygon(image, op_code, flat)
    except Exception:
        pdb.gimp_image_select_polygon(image, op_code, len(flat), flat)
    if drawable is not None:
        pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)


HELPERS = {
    "add_rectangle": _helper_add_rectangle,
    "draw_rectangle": _helper_add_rectangle,
    "fill_rectangle": _helper_add_rectangle,
    "add_ellipse": _helper_add_ellipse,
    "draw_ellipse": _helper_add_ellipse,
    "fill_ellipse": _helper_add_ellipse,
    "add_circle": _helper_add_circle,
    "draw_circle": _helper_add_circle,
    "fill_circle": _helper_add_circle,
    "draw_line": _helper_draw_line,
    "add_line": _helper_draw_line,
    "add_polygon": _helper_add_polygon,
    "draw_polygon": _helper_add_polygon,
    "fill_polygon": _helper_add_polygon,
}


def _parse_op(op):
    if op is None:
        return 2  # CHANNEL_OP_REPLACE
    if isinstance(op, int):
        return op
    if isinstance(op, string_types):
        op_map = {
            "CHANNEL_OP_ADD": 0, "ADD": 0, "SELECTION_ADD": 0,
            "CHANNEL_OP_SUBTRACT": 1, "SUBTRACT": 1, "SELECTION_SUBTRACT": 1,
            "CHANNEL_OP_REPLACE": 2, "REPLACE": 2, "SELECTION_REPLACE": 2,
            "CHANNEL_OP_INTERSECT": 3, "INTERSECT": 3, "SELECTION_INTERSECT": 3,
        }
        if op in op_map:
            return op_map[op]
        try:
            return int(op)
        except ValueError:
            return 2
    return 2


class _PdbAlias(object):
    """Proxy around the GIMP ``pdb`` that maps commonly-hallucinated PDB names
    to the real GIMP 2.10 procedures, and adapts forgiving argument lists,
    so generated scripts still run."""

    def __init__(self, real_pdb):
        self._pdb = real_pdb

    def __getattr__(self, name):
        if name in HELPERS:
            return HELPERS[name]
        if name == "gimp_image_get_width":
            return self._pdb.gimp_image_width
        if name == "gimp_image_get_height":
            return self._pdb.gimp_image_height
        if name in (
            "gimp_selection_rectangle", "gimp_rectangle_select", "gimp_image_select_rectangle",
            "gimp_rect_select", "rect_select", "select_rectangle"
        ):
            return self._selection_rectangle
        if name in (
            "gimp_selection_ellipse", "gimp_ellipse_select", "gimp_image_select_ellipse",
            "select_ellipse", "ellipse_select"
        ):
            return self._selection_ellipse
        if name in ("gimp_image_select_polygon", "gimp_polygon_select", "gimp_selection_polygon", "select_polygon"):
            return self._polygon_select
        if name in ("gimp_layer_new", "gimp_layer_new_with_mode"):
            return self._flex_layer_new
        if name in ("gimp_image_insert_layer", "gimp_image_add_layer"):
            return self._flex_insert_layer
        if name in ("gimp_context_set_foreground", "gimp_context_set_fg_color"):
            return self._flex_set_foreground
        if name in ("gimp_context_set_background", "gimp_context_set_bg_color"):
            return self._flex_set_background
        if name == "gimp_selection_none":
            return self._flex_selection_none
        if name == "gimp_selection_all":
            return self._flex_selection_all
        if name == "gimp_selection_invert":
            return self._flex_selection_invert
        if name == "gimp_displays_flush":
            return self._flex_displays_flush
        if name == "gimp_image_undo_group_start":
            return self._flex_undo_group_start
        if name == "gimp_image_undo_group_end":
            return self._flex_undo_group_end
        if name == "gimp_file_save":
            return self._flex_file_save
        if name == "gimp_image_resize":
            return self._flex_image_resize
        if name in ("gimp_layer_set_offset", "gimp_layer_set_offsets"):
            return self._pdb.gimp_layer_set_offsets
        if name == "gimp_edit_blend":
            return self._edit_blend
        if name == "gimp_pencil":
            return self._pencil
        return _CorrectingProc(self._pdb, name)

    def _find_image(self, args):
        for a in args:
            if _is_image(a):
                return a
        images = gimp.image_list()
        if images:
            return images[0]
        return _ensure_image()

    def _selection_rectangle(self, *args, **kwargs):
        return self._flex_select_shape("gimp_image_select_rectangle", *args, **kwargs)

    def _selection_ellipse(self, *args, **kwargs):
        return self._flex_select_shape("gimp_image_select_ellipse", *args, **kwargs)

    def _flex_select_shape(self, proc, *args, **kwargs):
        kwargs.pop("run_mode", None)
        image = kwargs.pop("image", None)
        op = kwargs.pop("op", kwargs.pop("operation", None))

        pos_args = list(args)
        if pos_args and _is_image(pos_args[0]):
            image = pos_args.pop(0)
        elif pos_args and _is_drawable(pos_args[0]):
            pos_args.pop(0)

        if len(pos_args) == 6 and not _is_image(pos_args[0]) and not _is_drawable(pos_args[0]):
            if pos_args[0] in (0, 1, 2, 3, CHANNEL_OP_REPLACE, CHANNEL_OP_ADD):
                op = _parse_op(pos_args.pop(0))
                x, y, w, h = [int(v) for v in pos_args[:4]]
            else:
                w, h = int(pos_args[0]), int(pos_args[1])
                x, y = int(pos_args[2]), int(pos_args[3])
                if pos_args[5]:
                    x -= w // 2
                    y -= h // 2
        elif len(pos_args) == 8 and not isinstance(pos_args[7], float):
            w, h = int(pos_args[2]), int(pos_args[3])
            x, y = int(pos_args[4]), int(pos_args[5])
            if pos_args[7]:
                x -= w // 2
                y -= h // 2
        elif len(pos_args) == 5:
            # Check if first arg is image-like or non-numeric
            if not isinstance(pos_args[0], (int, float)) and _is_image(pos_args[0]):
                image = pos_args.pop(0)
                x, y, w, h = [int(v) for v in pos_args[:4]]
            elif op is None and pos_args[0] in (0, 1, 2, 3, CHANNEL_OP_REPLACE, CHANNEL_OP_ADD):
                op = _parse_op(pos_args.pop(0))
                x, y, w, h = [int(v) for v in pos_args[:4]]
            else:
                # If first arg is not op or image, could be (image, x, y, w, h)
                if not isinstance(pos_args[0], (int, float)):
                    image = pos_args.pop(0)
                    x, y, w, h = [int(v) for v in pos_args[:4]]
                else:
                    x, y, w, h = [int(v) for v in pos_args[:4]]
        elif len(pos_args) == 4:
            x, y, w, h = [int(v) for v in pos_args]
        elif kwargs:
            x = int(kwargs.get("x", 0))
            y = int(kwargs.get("y", 0))
            w = int(kwargs.get("width", kwargs.get("w", 0)))
            h = int(kwargs.get("height", kwargs.get("h", 0)))
        else:
            nums = [a for a in pos_args if not _is_image(a) and not _is_drawable(a)]
            if len(nums) >= 4:
                x, y, w, h = [int(n) for n in nums[-4:]]
            else:
                raise TypeError("could not interpret arguments for %s" % proc)

        if image is None:
            image = self._find_image(args)
        op_code = _parse_op(op)
        return getattr(self._pdb, proc)(image, op_code, int(x), int(y), int(w), int(h))

    def _polygon_select(self, *args, **kwargs):
        kwargs.pop("run_mode", None)
        image = kwargs.pop("image", None)
        op = kwargs.pop("operation", kwargs.pop("op", None))
        pos = list(args)
        if pos and _is_image(pos[0]):
            image = pos.pop(0)

        if len(pos) >= 1 and (
            pos[0] in (0, 1, 2, 3, CHANNEL_OP_REPLACE, CHANNEL_OP_ADD)
            or (isinstance(pos[0], string_types) and pos[0] in (
                "CHANNEL_OP_REPLACE", "CHANNEL_OP_ADD", "CHANNEL_OP_SUBTRACT", "CHANNEL_OP_INTERSECT",
                "REPLACE", "ADD", "SUBTRACT", "INTERSECT"
            ))
        ):
            op = _parse_op(pos.pop(0))

        if len(pos) == 2 and isinstance(pos[0], (int, float)) and isinstance(pos[1], (list, tuple)):
            raw_points = pos[1]
        elif len(pos) == 1 and isinstance(pos[0], (list, tuple)):
            raw_points = pos[0]
        elif len(pos) >= 2 and all(isinstance(v, (int, float)) for v in pos):
            raw_points = pos
        elif len(pos) >= 1 and isinstance(pos[-1], (list, tuple)):
            raw_points = pos[-1]
        else:
            raw_points = kwargs.get("points", kwargs.get("segs", []))

        flat = []
        for p in raw_points:
            if isinstance(p, (list, tuple)):
                flat.extend(float(v) for v in p)
            else:
                flat.append(float(p))

        if image is None:
            image = self._find_image(args)
        op_code = _parse_op(op)

        # In GIMP Python-Fu (gimpfu / pygimp), pdb.gimp_image_select_polygon takes 3 arguments:
        # (image, operation, segs) where segs is a list/tuple of float coords.
        # Passing count as a 4th argument raises TypeError: wrong number of parameters.
        try:
            return self._pdb.gimp_image_select_polygon(image, op_code, flat)
        except TypeError as exc:
            if "wrong number of parameters" in str(exc) or "arguments" in str(exc):
                return self._pdb.gimp_image_select_polygon(image, op_code, len(flat), flat)
            raise

    def _flex_layer_new(self, *args, **kwargs):
        image = kwargs.get("image")
        pos = list(args)
        if pos and _is_image(pos[0]):
            image = pos.pop(0)
        if image is None:
            image = self._find_image(args)

        if pos and isinstance(pos[0], string_types) and len(pos) >= 3 and isinstance(pos[1], (int, float)):
            name = str(pos.pop(0))
            w = int(pos.pop(0))
            h = int(pos.pop(0))
            ltype = int(pos.pop(0)) if pos else RGB_IMAGE
            opacity = float(pos.pop(0)) if pos else 100.0
            mode = int(pos.pop(0)) if pos else NORMAL_MODE
        elif len(pos) >= 3:
            w = int(pos[0])
            h = int(pos[1])
            ltype = int(pos[2])
            name = str(pos[3]) if len(pos) > 3 else "Layer"
            opacity = float(pos[4]) if len(pos) > 4 else 100.0
            mode = int(pos[5]) if len(pos) > 5 else NORMAL_MODE
        else:
            w = int(kwargs.get("width", getattr(image, "width", 800)))
            h = int(kwargs.get("height", getattr(image, "height", 600)))
            ltype = int(kwargs.get("type", kwargs.get("layer_type", RGB_IMAGE)))
            name = str(kwargs.get("name", "Layer"))
            opacity = float(kwargs.get("opacity", 100.0))
            mode = int(kwargs.get("mode", NORMAL_MODE))

        return self._pdb.gimp_layer_new(image, w, h, ltype, name, opacity, mode)

    def _flex_insert_layer(self, *args, **kwargs):
        image = kwargs.get("image")
        layer = kwargs.get("layer")
        parent = kwargs.get("parent", None)
        position = kwargs.get("position", 0)

        pos = list(args)
        if pos and _is_image(pos[0]):
            image = pos.pop(0)
        if pos and _is_drawable(pos[0]):
            layer = pos.pop(0)
        if len(pos) == 1:
            if isinstance(pos[0], int):
                position = pos[0]
            else:
                parent = pos[0]
        elif len(pos) >= 2:
            parent = pos[0]
            position = int(pos[1])

        if image is None:
            image = self._find_image(args)
        return self._pdb.gimp_image_insert_layer(image, layer, parent, int(position))

    def _flex_set_foreground(self, *args, **kwargs):
        color = self._extract_color(args, kwargs)
        return self._pdb.gimp_context_set_foreground(color)

    def _flex_set_background(self, *args, **kwargs):
        color = self._extract_color(args, kwargs)
        return self._pdb.gimp_context_set_background(color)

    def _extract_color(self, args, kwargs):
        if "color" in kwargs:
            c = _parse_color(kwargs["color"])
            if c:
                return c
        if len(args) == 1:
            c = _parse_color(args[0])
            if c:
                return c
            return args[0]
        if len(args) >= 3:
            return (int(args[0]), int(args[1]), int(args[2]))
        return (0, 0, 0)

    def _flex_selection_none(self, *args, **kwargs):
        image = self._find_image(args)
        return self._pdb.gimp_selection_none(image)

    def _flex_selection_all(self, *args, **kwargs):
        image = self._find_image(args)
        return self._pdb.gimp_selection_all(image)

    def _flex_selection_invert(self, *args, **kwargs):
        image = self._find_image(args)
        return self._pdb.gimp_selection_invert(image)

    def _flex_undo_group_start(self, *args, **kwargs):
        image = self._find_image(args)
        return self._pdb.gimp_image_undo_group_start(image)

    def _flex_undo_group_end(self, *args, **kwargs):
        image = self._find_image(args)
        return self._pdb.gimp_image_undo_group_end(image)

    def _flex_displays_flush(self, *args, **kwargs):
        return self._pdb.gimp_displays_flush()

    def _flex_file_save(self, *args, **kwargs):
        if len(args) == 3:
            return self._pdb.gimp_file_save(args[0], args[1], args[2], args[2])
        return self._pdb.gimp_file_save(*args, **kwargs)

    def _flex_image_resize(self, *args, **kwargs):
        if len(args) == 3:
            return self._pdb.gimp_image_resize(args[0], args[1], args[2], 0, 0)
        return self._pdb.gimp_image_resize(*args, **kwargs)

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
        """gimp_pencil(drawable, num_points, points) or gimp_pencil(drawable, points)
        where points may be a flat list or a list of (x, y) tuples."""
        kwargs.pop("run_mode", None)
        drawable = kwargs.pop("drawable", None)
        pos = list(args)
        if pos and _is_drawable(pos[0]):
            drawable = pos.pop(0)
        elif pos and _is_image(pos[0]):
            img = pos.pop(0)
            if pos and _is_drawable(pos[0]):
                drawable = pos.pop(0)
            else:
                drawable = getattr(img, "active_drawable", None)

        if drawable is None:
            img = _ensure_image()
            drawable = getattr(img, "active_drawable", None)

        if len(pos) == 2 and isinstance(pos[0], (int, float)) and isinstance(pos[1], (list, tuple)):
            raw_points = pos[1]
        elif len(pos) == 1 and isinstance(pos[0], (list, tuple)):
            raw_points = pos[0]
        elif len(pos) >= 2 and all(isinstance(v, (int, float)) for v in pos):
            raw_points = pos
        else:
            raw_points = kwargs.get("points", kwargs.get("strokes", []))

        flat = []
        for p in raw_points:
            if isinstance(p, (list, tuple)):
                flat.extend(float(v) for v in p)
            else:
                flat.append(float(p))

        try:
            return self._pdb.gimp_pencil(drawable, flat)
        except TypeError as exc:
            if "wrong number of parameters" in str(exc) or "arguments" in str(exc):
                return self._pdb.gimp_pencil(drawable, len(flat) // 2, flat)
            raise


# ------------------------------------------------------------ typo correction

_PDB_NAME_CACHE = {"names": None}


def _all_pdb_procedure_names(real_pdb):
    """Every procedure name the live GIMP PDB actually has registered, queried
    once and cached. Source of truth is GIMP itself, not a bundled static
    list, so this works for the full ~2000-procedure PDB, not just the small
    curated set PixelPilot ships few-shot examples for."""
    if _PDB_NAME_CACHE["names"] is not None:
        return _PDB_NAME_CACHE["names"]
    names = set()
    try:
        result = real_pdb.query(".*", ".*", ".*", ".*", ".*", ".*", ".*")
        if result and isinstance(result[0], (list, tuple)):
            result = result[0]
        for raw in result:
            names.add(str(raw).replace("-", "_"))
    except Exception:  # noqa: BLE001 - introspection failing must not break execution
        pass
    _PDB_NAME_CACHE["names"] = names
    return names


def _closest_pdb_name(real_pdb, name, cutoff=0.75):
    import difflib
    candidates = _all_pdb_procedure_names(real_pdb)
    if not candidates or name in candidates:
        return None
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def _looks_like_missing_procedure(exc):
    text = str(exc).lower()
    return ("procedure" in text and ("not found" in text or "does not exist" in text
                                      or "no such" in text or "unknown" in text))


class _CorrectingProc(object):
    """Lazily resolves one PDB attribute. If GIMP itself reports the name
    doesn't exist (e.g. a hallucinated typo like ``gimp_image_select_ipse``
    for ``gimp_image_select_ellipse``), retries once against the closest
    real procedure name from the live PDB before giving up. This only ever
    engages after GIMP has confirmed the original name is invalid, so it
    can't misfire on a real call this proxy simply doesn't special-case."""

    def __init__(self, real_pdb, name):
        self._pdb = real_pdb
        self._name = name

    def __call__(self, *args, **kwargs):
        try:
            return getattr(self._pdb, self._name)(*args, **kwargs)
        except AttributeError:
            missing = True
        except Exception as exc:  # noqa: BLE001 - only intercept "not found" style errors
            if not _looks_like_missing_procedure(exc):
                raise
            missing = True
        if not missing:  # pragma: no cover - unreachable, kept for clarity
            raise AttributeError(self._name)
        corrected = _closest_pdb_name(self._pdb, self._name)
        if not corrected:
            raise AttributeError("Unknown PDB procedure: %s" % self._name)
        sys.stdout.write(
            "[pixelpilot] %r is not a real PDB procedure - retrying as %r\n"
            % (self._name, corrected)
        )
        return getattr(self._pdb, corrected)(*args, **kwargs)


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
            for _name, _func in HELPERS.items():
                ns.setdefault(_name, _func)
            exec(compiled, ns)
            result = sys.stdout.getvalue()
            return {"status": "ok", "result": result}
        except Exception as exc:  # noqa: BLE001 - must report script failures
            import traceback
            tb = traceback.format_exc()
            return {"status": "error", "error": "%s: %s\n%s" % (type(exc).__name__, exc, tb)}
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
