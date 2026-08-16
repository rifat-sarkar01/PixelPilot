"""Regression tests for the plugin's PDB typo-correction proxy.

plugin.py only imports cleanly inside GIMP's own Python-Fu interpreter (it
does `from gimpfu import *`), so these tests stub a minimal fake `gimpfu`
module in sys.modules before importing it - mirroring the manual
verification used to build and confirm the fix in the first place.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "gimp"

REAL_NAMES = [
    "gimp-image-select-ellipse",
    "gimp-image-select-rectangle",
    "gimp-image-select-polygon",
    "gimp-pencil",
    "gimp-edit-fill",
    "gimp-selection-none",
    "gimp-context-set-foreground",
    "gimp-image-width",
    "gimp-image-height",
    "gimp-displays-flush",
]


class _GimpError(RuntimeError):
    pass


_GimpError.__name__ = "error"  # mirrors GIMP's own exception class name


class _FakeRealPdb:
    """Mimics real GIMP's pdb: attribute access always succeeds (lazy);
    the procedure name is only validated when the returned callable is
    actually invoked - matching observed real-GIMP behavior."""

    def __init__(self, extra_failure=None):
        self.calls = []
        self._extra_failure = extra_failure or {}

    def query(self, *_args):
        return (REAL_NAMES,)

    def __getattr__(self, name):
        def fn(*args, **kwargs):
            self.calls.append(name)
            if name in self._extra_failure:
                raise self._extra_failure[name]
            underscored = {n.replace("-", "_") for n in REAL_NAMES}
            if name not in underscored:
                raise _GimpError("procedure not found")
            return MagicMock()

        return fn


class _FakeImage:
    def __init__(self):
        self.active_drawable = MagicMock(name="drawable")


@pytest.fixture
def plugin_module(monkeypatch):
    """Import plugin.py fresh against a fake gimpfu, per test."""
    sys.path.insert(0, str(PLUGIN_DIR))
    fake_gimpfu = types.ModuleType("gimpfu")
    constants = {
        "RGB": 0,
        "RGB_IMAGE": 0,
        "NORMAL_MODE": 0,
        "CHANNEL_OP_ADD": 0,
        "CHANNEL_OP_SUBTRACT": 1,
        "CHANNEL_OP_REPLACE": 2,
        "CHANNEL_OP_INTERSECT": 3,
        "FOREGROUND_FILL": 0,
        "BACKGROUND_FILL": 1,
        "WHITE_FILL": 2,
        "TRANSPARENT_FILL": 3,
    }
    for name, val in constants.items():
        setattr(fake_gimpfu, name, val)

    real_pdb = _FakeRealPdb()
    fake_gimpfu.pdb = real_pdb
    fake_gimpfu.gimp = types.SimpleNamespace(
        image_list=lambda: [_FakeImage()],
        Image=type("Image", (), {}),
        Item=type("Item", (), {}),
    )
    monkeypatch.setitem(sys.modules, "gimpfu", fake_gimpfu)

    if "pixelpilot_gimp.plugin" in sys.modules:
        module = importlib.reload(sys.modules["pixelpilot_gimp.plugin"])
    else:
        module = importlib.import_module("pixelpilot_gimp.plugin")
    module._PDB_NAME_CACHE["names"] = None  # each test gets a fresh query() cache
    yield module, real_pdb


def test_typo_in_procedure_name_is_auto_corrected(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "image = gimp.image_list()[0]\n"
        "drawable = image.active_drawable\n"
        "pdb.gimp_image_select_ipse(image, CHANNEL_OP_REPLACE, 10, 10, 20, 20)\n"
        "pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})

    assert result["status"] == "ok"
    assert "gimp_image_select_ellipse" in result["result"]
    assert "gimp_image_select_ipse" in real_pdb.calls  # the bad name was tried first
    assert "gimp_image_select_ellipse" in real_pdb.calls  # then corrected


def test_unmatchable_procedure_name_fails_cleanly(plugin_module):
    plugin, _real_pdb = plugin_module
    script = "from gimpfu import *\npdb.completely_made_up_nonexistent_call_xyz()\n"

    result = plugin._handle({"cmd": "execute", "code": script})

    assert result["status"] == "error"
    assert "completely_made_up_nonexistent_call_xyz" in result["error"]


def test_unrelated_real_error_is_not_swallowed_or_retried(plugin_module):
    plugin, real_pdb = plugin_module
    real_pdb._extra_failure["gimp_edit_fill"] = RuntimeError(
        "Procedure 'gimp-edit-fill' has been called with an invalid ID for argument 'drawable'."
    )
    script = "from gimpfu import *\npdb.gimp_edit_fill(None, FOREGROUND_FILL)\n"

    result = plugin._handle({"cmd": "execute", "code": script})

    assert result["status"] == "error"
    assert real_pdb.calls.count("gimp_edit_fill") == 1


def test_flexible_rectangle_selection_5_args(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "image = gimp.image_list()[0]\n"
        "pdb.gimp_image_select_rectangle(image, 10, 20, 100, 50)\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_image_select_rectangle" in real_pdb.calls


def test_flexible_rectangle_selection_4_args(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "pdb.gimp_image_select_rectangle(10, 20, 100, 50)\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_image_select_rectangle" in real_pdb.calls


def test_flexible_context_set_foreground_3_args(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "pdb.gimp_context_set_foreground(255, 128, 0)\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_context_set_foreground" in real_pdb.calls


def test_injected_add_rectangle_helper(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "add_rectangle(10, 20, 100, 50, (255, 0, 0))\n"
        "pdb.add_rectangle(0, 0, 50, 50)\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_image_select_rectangle" in real_pdb.calls
    assert "gimp_edit_fill" in real_pdb.calls
    assert "gimp_selection_none" in real_pdb.calls


def test_flexible_polygon_selection_3_args(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "image = gimp.image_list()[0]\n"
        "pdb.gimp_image_select_polygon(image, CHANNEL_OP_REPLACE, [10, 10, 50, 10, 50, 50, 10, 50])\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_image_select_polygon" in real_pdb.calls


def test_flexible_polygon_selection_4_args_with_len(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "image = gimp.image_list()[0]\n"
        "pts = [10, 10, 50, 10, 50, 50, 10, 50]\n"
        "pdb.gimp_image_select_polygon(image, CHANNEL_OP_REPLACE, len(pts), pts)\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_image_select_polygon" in real_pdb.calls


def test_flexible_polygon_selection_tuples_and_implicit_image(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "pdb.gimp_image_select_polygon(CHANNEL_OP_REPLACE, [(10, 10), (50, 10), (50, 50), (10, 50)])\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_image_select_polygon" in real_pdb.calls


def test_injected_add_polygon_helper(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "add_polygon([10, 10, 50, 10, 50, 50, 10, 50], color=(200, 200, 200))\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert "gimp_image_select_polygon" in real_pdb.calls
    assert "gimp_edit_fill" in real_pdb.calls
    assert "gimp_selection_none" in real_pdb.calls


def test_pencil_2_and_3_args(plugin_module):
    plugin, real_pdb = plugin_module
    script = (
        "from gimpfu import *\n"
        "image = gimp.image_list()[0]\n"
        "drawable = image.active_drawable\n"
        "pdb.gimp_pencil(drawable, [0, 0, 100, 100])\n"
        "pdb.gimp_pencil(drawable, 2, [0, 0, 100, 100])\n"
    )
    result = plugin._handle({"cmd": "execute", "code": script})
    assert result["status"] == "ok"
    assert real_pdb.calls.count("gimp_pencil") == 2

