"""Auto-launch support for the GIMP and Krita bridges.

Previously, ``pixelpilot --editor gimp`` only ever *tried* to connect to an
already-running GIMP instance; if GIMP wasn't already open with the
PixelPilot plugin registered, the CLI would silently continue in a
"not connected" state (scripts got generated and validated but never
executed, and no PNG was ever produced). The user had to know to run a
separate, Windows-only, hand-edited script (``start_gimp_bridge.ps1``) before
starting the CLI.

This module closes that gap: it finds a GIMP/Krita install, deploys the bridge
plugin into the editor's plug-ins directory, launches the editor with the
bridge procedure invoked, and polls the bridge socket until it comes up (or
the timeout elapses).
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


# ----------------------------------------------------------------- Krita

def _krita_candidate_dirs() -> list[Path]:
    """Common Krita install directories (Windows / macOS / Linux)."""
    if sys.platform == "win32":
        dirs: list[Path] = []
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                base = Path(root)
                dirs.append(base / "Krita (x64)" / "bin")
                dirs.append(base / "Krita" / "bin")
                dirs.extend(
                    p / "bin"
                    for p in base.glob("Krita*")
                    if p.is_dir()
                )
        # Also scan inside D:/Krita and similar parent dirs for versioned sub-dirs
        for parent in [Path("D:/Krita"), Path("C:/Krita")]:
            if parent.is_dir():
                dirs.append(parent / "bin")
                dirs.extend(
                    p / "bin"
                    for p in parent.glob("Krita*")
                    if p.is_dir()
                )
        return dirs
    if sys.platform == "darwin":
        return [
            Path("/Applications/krita.app/Contents/MacOS"),
            Path("/Applications/Krita.app/Contents/MacOS"),
        ]
    # Linux
    return [
        Path("/usr/bin"),
        Path("/usr/local/bin"),
        Path("/snap/bin"),
        Path.home() / ".local" / "bin",
    ]


def find_krita_binary(configured_path: str | None = None) -> str | None:
    """Best-effort search for a Krita executable.

    Checks, in order: an explicitly configured path
    (``editor.krita.binary_path``), ``PATH``, then common per-platform
    install locations (including D:/Krita on Windows).
    """
    krita_names_win = ["krita.exe", "krita_shell.exe", "krita.com"]
    krita_names_other = ["krita"]

    if configured_path:
        p = Path(configured_path).expanduser()
        # If the path points directly at a directory, probe known exe names
        # AND look one level deeper for versioned sub-dirs like "Krita (x64)".
        if p.is_dir():
            names = krita_names_win if sys.platform == "win32" else krita_names_other
            # Direct hit
            for name in names:
                for candidate in [p / name, p / "bin" / name]:
                    if candidate.is_file():
                        return str(candidate)
            # Versioned sub-directory (e.g. D:/Krita/Krita (x64)/bin/krita.exe)
            for sub in sorted(p.iterdir()):
                if sub.is_dir():
                    for name in names:
                        for candidate in [sub / name, sub / "bin" / name]:
                            if candidate.is_file():
                                return str(candidate)
        elif p.is_file():
            return str(p)

    names = krita_names_win if sys.platform == "win32" else krita_names_other
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    for directory in _krita_candidate_dirs():
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)

    return None


# ----------------------------------------------------------------- Krita deploy

def krita_plugin_dir() -> Path:
    """Return the platform-appropriate Krita pykrita plug-ins directory."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "krita" / "pykrita"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "krita" / "pykrita"
    return Path.home() / ".local" / "share" / "krita" / "pykrita"


def _kritarc_path() -> Path:
    """Return the path to Krita's own settings file (``kritarc``).

    Per Krita's own docs this is a DIFFERENT directory than the pykrita plugin
    folder above: %LOCALAPPDATA% on Windows (not %APPDATA%), ~/.config on
    Linux, ~/Library/Preferences on macOS.
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "kritarc"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "kritarc"
    return Path.home() / ".config" / "kritarc"


def enable_krita_plugin(module_name: str = "pixelpilot_krita") -> None:
    """Mark the plugin enabled in kritarc so it loads without a manual trip
    through Settings -> Configure Krita -> Python Plugin Manager.

    Deploying the plugin files is necessary but NOT sufficient - Krita only
    loads a pykrita plugin's ``setup()`` (which is what starts the bridge
    socket) if it's been enabled via the Python Plugin Manager, and that flag
    is just a line in this ini-style config file: ``enable_<module>=true``
    under ``[python]``. Writing it directly here is exactly what checking the
    box in the UI would have done, so a fresh Krita install can pick up and
    start the bridge automatically on first launch instead of silently never
    running the plugin at all.

    IMPORTANT: kritarc is NOT a standard INI file. It starts with bare
    ``key=value`` lines before any ``[section]`` header, so configparser
    cannot parse it. We operate on lines directly to avoid corrupting the
    file.

    This intentionally never raises - if it fails for any reason (permissions,
    unexpected file format, etc.) the caller should still proceed with
    deployment and launch; worst case the user falls back to enabling the
    plugin manually, exactly as before this existed.
    """
    path = _kritarc_path()
    key = f"enable_{module_name}=true"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            lines = []

        # Check if the key already exists
        for line in lines:
            if line.strip() == key:
                return  # Already enabled

        # Find the [python] section and insert after it
        inserted = False
        new_lines = []
        for line in lines:
            new_lines.append(line)
            if line.strip() == "[python]":
                new_lines.append(key + "\n")
                inserted = True

        # If no [python] section found, append one at the end
        if not inserted:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append("[python]\n")
            new_lines.append(key + "\n")

        path.write_text("".join(new_lines), encoding="utf-8")
    except OSError:
        pass


def _krita_plugin_source() -> Path | None:
    """Locate the bundled Krita plugin source next to this editable checkout."""
    import pixelpilot

    pkg_root = Path(pixelpilot.__file__).resolve().parent  # .../src/pixelpilot
    candidates = [
        pkg_root.parents[1] / "plugins" / "krita" / "pixelpilot_krita",
        pkg_root.parents[0] / "plugins" / "krita" / "pixelpilot_krita",
    ]
    for candidate in candidates:
        if (candidate / "plugin.py").is_file():
            return candidate
    return None


def deploy_krita_plugin() -> Path:
    """Copy the PixelPilot plugin package + .desktop file into Krita's pykrita dir.

    Krita expects:
      <pykrita>/pixelpilot_krita/          <- Python package directory
      <pykrita>/pixelpilot_krita.desktop   <- service descriptor
    """
    source_dir = _krita_plugin_source()
    if source_dir is None:
        raise LauncherError(
            "Could not find the bundled Krita plugin source "
            "(plugins/krita/pixelpilot_krita/). If PixelPilot was installed as "
            "a non-editable package, deploy the plugin manually - see README.md."
        )

    pykrita = krita_plugin_dir()
    pykrita.mkdir(parents=True, exist_ok=True)

    # Copy the package directory
    dest_pkg = pykrita / "pixelpilot_krita"
    if dest_pkg.exists():
        shutil.rmtree(dest_pkg)
    shutil.copytree(source_dir, dest_pkg)

    # Copy the .desktop file one level up (in pykrita/, not inside the package)
    desktop_src = source_dir / "pixelpilot.desktop"
    desktop_dst = pykrita / "pixelpilot_krita.desktop"
    if desktop_src.is_file():
        shutil.copyfile(desktop_src, desktop_dst)

    return dest_pkg


def verify_krita_plugin() -> tuple[bool, str]:
    """Verify the Krita plugin is deployed correctly.

    Returns (ok, message) where ok is True if all checks pass.
    """
    pykrita = krita_plugin_dir()
    pkg_dir = pykrita / "pixelpilot_krita"
    desktop_file = pykrita / "pixelpilot_krita.desktop"
    init_file = pkg_dir / "__init__.py"
    plugin_file = pkg_dir / "plugin.py"

    errors = []

    if not pykrita.is_dir():
        errors.append(f"pykrita directory does not exist: {pykrita}")
    if not pkg_dir.is_dir():
        errors.append(f"Plugin package not found: {pkg_dir}")
    else:
        if not init_file.is_file():
            errors.append(f"Missing __init__.py in {pkg_dir}")
        if not plugin_file.is_file():
            errors.append(f"Missing plugin.py in {pkg_dir}")
    if not desktop_file.is_file():
        errors.append(f"Missing .desktop file: {desktop_file}")

    if errors:
        return False, "Plugin deployment issues:\n" + "\n".join(f"  - {e}" for e in errors)
    return True, f"Plugin deployed OK at {pkg_dir}"


def _krita_process_running() -> bool:
    """Check if any Krita process is currently running."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq krita.exe", "/NH"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            return "krita.exe" in result.stdout.lower()
        except Exception:  # noqa: BLE001
            return False
    else:
        try:
            result = subprocess.run(
                ["pgrep", "-x", "krita"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            return result.returncode == 0
        except Exception:  # noqa: BLE001
            return False


def launch_krita_and_wait(
    host: str = "localhost",
    port: int = 10020,
    binary_path: str | None = None,
    timeout: float = 90.0,
    on_progress=None,
) -> bool:
    """Launch Krita and wait for its bridge socket to come up.

    Returns True once the bridge socket answers, False if ``timeout`` elapses
    first. Raises :class:`LauncherError` if Krita can't be found at all.

    Krita's PixelPilot bridge is loaded as a Python plugin from Krita's
    ``pykrita`` directory; unlike GIMP it does not require a batch expression -
    once the plugin is active it opens its socket automatically on startup.
    """
    if _port_is_open(host, port):
        return True  # Already up (plugin is already running).

    if _krita_process_running():
        # Krita normally runs single-instance - launching the exe again just
        # messages the EXISTING process to open a new window, it does not
        # start a fresh process. Krita only scans the pykrita folder for
        # plugins at startup, so if that running instance started before the
        # plugin was deployed/enabled, no amount of relaunching or waiting
        # here will ever pick it up - this is what was actually happening
        # when Krita opened but 'PixelPilot' never appeared in the Python
        # Plugin Manager list at all. Deploy/enable now so the files are
        # ready, but the user has to fully quit Krita for any of it to be
        # read - failing fast here beats silently polling for 90 seconds.
        deploy_krita_plugin()
        ok, msg = verify_krita_plugin()
        if not ok:
            raise LauncherError(msg)
        enable_krita_plugin("pixelpilot_krita")
        raise LauncherError(
            "Krita is already running, so relaunching it just opened another "
            "window in that same process - it did NOT start fresh, and Krita "
            "only scans for plugins at startup. The PixelPilot plugin files "
            "are deployed and enabled now, but won't be picked up until "
            "Krita is FULLY closed (all windows - check the taskbar too, not "
            "just this one) and reopened. Quit Krita completely, then run "
            "/connect again."
        )

    binary = find_krita_binary(binary_path)
    if binary is None:
        raise LauncherError(
            "Could not find a Krita install. Set editor.krita.binary_path "
            "in your config (e.g. D:/Krita), or launch Krita with the "
            "PixelPilot plugin enabled manually before starting pixelpilot."
        )

    # Deploy the pykrita plugin so Krita's plugin manager picks it up.
    deploy_krita_plugin()

    # Verify deployment
    ok, msg = verify_krita_plugin()
    if not ok:
        raise LauncherError(msg)

    # Deploying the files is necessary but not sufficient - Krita also needs
    # the plugin explicitly enabled via the Python Plugin Manager before it
    # will ever call setup() (which starts the bridge). Do that automatically
    # so a first-time install doesn't hang here forever with no bridge and no
    # indication why - see enable_krita_plugin's docstring.
    enable_krita_plugin("pixelpilot_krita")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )

    subprocess.Popen(
        [binary],
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


def get_krita_connection_failure_message(host: str, port: int, binary: str | None = None) -> str:
    """Generate a detailed diagnostic message when Krita connection fails."""
    lines = []

    # Check if Krita is running
    if _krita_process_running():
        lines.append(f"Krita is running but the PixelPilot bridge is not responding on port {port}.")
        lines.append("")
        lines.append("The plugin is likely installed but NOT enabled. To fix this:")
        lines.append("  1. In Krita, go to  Settings -> Configure Krita -> Python Plugin Manager")
        lines.append("  2. Find 'PixelPilot' in the list and check the box to enable it")
        lines.append("  3. Click OK, then restart Krita completely")
        lines.append("  4. Return here and run /connect")
        lines.append("")
        lines.append("If 'PixelPilot' does not appear in the plugin list:")
        lines.append("  - Make sure Python scripting is enabled in Krita")
        lines.append("  - Close Krita, then run this command again to re-deploy the plugin")
    else:
        lines.append("Krita does not appear to be running.")
        lines.append("")
        lines.append("Possible causes:")
        lines.append(f"  - The Krita binary may have failed to start: {binary or '(unknown)'}")
        lines.append("  - Check if Krita opens normally when launched manually")
        lines.append("  - On Windows, check if a firewall or antivirus is blocking the process")
        lines.append("")
        lines.append("Troubleshooting steps:")
        lines.append("  1. Try launching Krita manually to see if it starts")
        lines.append("  2. In Krita, go to  Settings -> Configure Krita -> Python Plugin Manager")
        lines.append("  3. Ensure 'Enable Python Plugin Manager' is checked")
        lines.append("  4. Enable the 'PixelPilot' plugin and restart Krita")
        lines.append("  5. Return here and run /connect")

    # Check port conflict
    if _port_is_open(host, port):
        lines.append("")
        lines.append(f"Note: port {port} is open but not responding with the PixelPilot protocol.")
        lines.append("Another process may be using this port. Try a different port in your config.")

    return "\n".join(lines)
