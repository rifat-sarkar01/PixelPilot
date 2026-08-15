"""Auto-launch support for the GIMP bridge.

Previously, ``pixelpilot --editor gimp`` only ever *tried* to connect to an
already-running GIMP instance; if GIMP wasn't already open with the
PixelPilot plugin registered, the CLI would silently continue in a
"not connected" state (scripts got generated and validated but never
executed, and no PNG was ever produced). The user had to know to run a
separate, Windows-only, hand-edited script (``start_gimp_bridge.ps1``) before
starting the CLI.

This module closes that gap: it finds a GIMP install, deploys the bridge
plugin into GIMP's plug-ins directory, launches GIMP with the bridge
procedure invoked as a batch expression, and polls the bridge socket until
it comes up (or the timeout elapses).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

PROTOCOL_MAGIC = b"PXPT1"
BATCH_EXPR = "(python-fu-pixelpilot-bridge RUN-NONINTERACTIVE)"
PLUGIN_FILENAME = "pixelpilot_plugin.py"


class LauncherError(RuntimeError):
    """Could not locate or launch GIMP."""


# --------------------------------------------------------------------- paths

def _repo_plugin_source() -> Path | None:
    """Locate the bundled ``plugin.py`` source next to this editable checkout.

    The plugin lives outside the installed ``pixelpilot`` package (under
    ``plugins/gimp/pixelpilot_gimp/plugin.py`` at the repo root) because it
    must run standalone inside GIMP's own Python-Fu interpreter. For an
    editable install (``pip install -e .``, as the README instructs) the
    installed package still points at the checkout, so we can find it
    relative to this file.
    """
    import pixelpilot

    pkg_root = Path(pixelpilot.__file__).resolve().parent  # .../src/pixelpilot
    candidates = [
        pkg_root.parents[1] / "plugins" / "gimp" / "pixelpilot_gimp" / "plugin.py",
        pkg_root.parents[0] / "plugins" / "gimp" / "pixelpilot_gimp" / "plugin.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def gimp_plugin_dir() -> Path:
    """Return the platform-appropriate GIMP 2.10 plug-ins directory."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "GIMP" / "2.10" / "plug-ins"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "GIMP" / "2.10" / "plug-ins"
    return Path.home() / ".config" / "GIMP" / "2.10" / "plug-ins"


def deploy_plugin() -> Path:
    """Copy the bridge plugin into GIMP's plug-ins directory.

    Removes any stale ``.pyc`` next to it first: GIMP 2.10's Python-Fu
    (Python 2.7) writes one on first import, and if GIMP later tries to
    treat that ``.pyc`` as the plug-in itself (e.g. after the source is
    updated) registration fails with "Exec format error".
    """
    source = _repo_plugin_source()
    if source is None:
        raise LauncherError(
            "Could not find the bundled GIMP plugin source "
            "(plugins/gimp/pixelpilot_gimp/plugin.py). If PixelPilot was "
            "installed as a regular (non-editable) package, deploy the "
            "plugin manually - see README.md."
        )
    dest_dir = gimp_plugin_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / PLUGIN_FILENAME
    shutil.copyfile(source, dest)
    stale_pyc = dest_dir / (PLUGIN_FILENAME + "c")
    stale_pyc.unlink(missing_ok=True)
    if sys.platform != "win32":
        # GIMP on Linux/macOS only scans plug-ins that are executable.
        dest.chmod(dest.stat().st_mode | 0o111)
    return dest


# ------------------------------------------------------------------- discovery

def _candidate_names() -> list[str]:
    if sys.platform == "win32":
        return ["gimp-2.10.exe", "gimp-2.10.6.exe", "gimp.exe"]
    return ["gimp-2.10", "gimp2.10", "gimp"]


def _candidate_dirs() -> list[Path]:
    if sys.platform == "win32":
        roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
        dirs = []
        for root in roots:
            if not root:
                continue
            base = Path(root)
            dirs.append(base / "GIMP 2" / "bin")
            if base.is_dir():
                # Also try any "GIMP*" folder (version-numbered installs).
                dirs.extend(p / "bin" for p in base.glob("GIMP*") if p.is_dir())
        return dirs
    if sys.platform == "darwin":
        return [
            Path("/Applications/GIMP.app/Contents/MacOS"),
            Path("/Applications/GIMP-2.10.app/Contents/MacOS"),
        ]
    return [Path("/usr/bin"), Path("/usr/local/bin"), Path("/snap/bin")]


def find_gimp_binary(configured_path: str | None = None) -> str | None:
    """Best-effort search for a GIMP 2.10 executable.

    Checks, in order: an explicitly configured path
    (``editor.gimp.binary_path``), ``PATH``, then common per-platform
    install locations.
    """
    if configured_path:
        p = Path(configured_path).expanduser()
        if p.is_file():
            return str(p)

    for name in _candidate_names():
        found = shutil.which(name)
        if found:
            return found

    for directory in _candidate_dirs():
        for name in _candidate_names():
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)

    return None


# --------------------------------------------------------------------- launch

def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def launch_and_wait(
    host: str = "localhost",
    port: int = 10010,
    binary_path: str | None = None,
    timeout: float = 90.0,
    on_progress=None,
) -> bool:
    """Deploy the plugin, launch GIMP with the bridge invoked, and wait.

    Returns True once the bridge socket answers, False if ``timeout`` elapses
    first. Raises :class:`LauncherError` if GIMP can't be found at all.
    """
    if _port_is_open(host, port):
        return True  # Something (a previous GIMP instance) is already up.

    binary = find_gimp_binary(binary_path)
    if binary is None:
        raise LauncherError(
            "Could not find a GIMP 2.10 install. Set editor.gimp.binary_path "
            "in your config, or launch GIMP with the PixelPilot plugin "
            "manually before starting pixelpilot."
        )

    deploy_plugin()

    env = dict(os.environ)
    # Python 2.7 (GIMP's Python-Fu interpreter) would otherwise write a
    # pixelpilot_plugin.pyc next to the source; GIMP can end up trying to
    # exec that .pyc as the plug-in on a later scan and fail.
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )

    subprocess.Popen(
        [binary, "-b", BATCH_EXPR],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=(sys.platform != "win32"),
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_open(host, port):
            return True
        if on_progress is not None:
            on_progress()
        time.sleep(1.5)
    return False
