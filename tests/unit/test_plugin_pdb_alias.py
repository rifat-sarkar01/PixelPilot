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
    for name in [
        "RGB", "RGB_IMAGE", "NORMAL_MODE", "CHANNEL_OP_REPLACE", "CHANNEL_OP_ADD",
        "BACKGROUND_FILL", "FOREGROUND_FILL",
    ]:
        setattr(fake_gimpfu, name, name)

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
    assert "invalid ID" in result["error"]
    # Only tried once - must not have attempted a "correction" retry for a
    # failure that wasn't a missing-procedure error.
    assert real_pdb.calls.count("gimp_edit_fill") == 1
