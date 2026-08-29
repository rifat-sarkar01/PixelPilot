"""Regression tests for Krita auto-launch (pixelpilot.bridge.launcher).

Three confirmed bugs are covered here:

1. The bundled .desktop file was missing X-KDE-Library=pixelpilot_krita.
   Without it Krita has no way to associate the .desktop descriptor with the
   pixelpilot_krita Python module - the plugin never even appears in the
   Python Plugin Manager list, so it can never be enabled, so setup() (which
   starts the bridge) is never called. Confirmed against Krita's own plugin
   loading docs/examples, not guessed.

2. enable_krita_plugin() writes kritarc directly (the equivalent of checking
   the box in Settings -> Configure Krita -> Python Plugin Manager) so a
   fresh install doesn't need that manual step - it must create the file/
   section if missing, and must not clobber the user's other settings.

3. launch_krita_and_wait() used to always spawn a new krita.exe process even
   when Krita was already running. Krita is single-instance in practice -
   relaunching it just opens a new window in the SAME process, which never
   re-scans the pykrita folder, so newly deployed/enabled plugin files are
   never picked up and the bridge silently never comes up (confirmed live:
   Krita was open, 'PixelPilot' never appeared in the Plugin Manager list at
   all even after deploy+enable). This must fail fast with a clear "quit
   Krita completely" message instead of polling for the full timeout.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from pixelpilot.bridge import launcher

DESKTOP_FILE = (
    Path(__file__).resolve().parents[2]
    / "plugins" / "krita" / "pixelpilot_krita" / "pixelpilot.desktop"
)


def test_desktop_file_declares_x_kde_library():
    content = DESKTOP_FILE.read_text(encoding="utf-8")
    assert "X-KDE-Library=pixelpilot_krita" in content, (
        "without X-KDE-Library, Krita cannot load this plugin at all - "
        "it won't appear in the Python Plugin Manager, let alone run"
    )


def test_desktop_file_has_no_stale_krita_version_field():
    # X-Krita-Version=28 shipped in the original file. A KDE bug report
    # (bugs.kde.org #390624) confirms 28 was already a known-stale
    # placeholder years ago, and several verified currently-working
    # community plugins (ArtKrit, Krita-UI-Redesign) omit this field
    # entirely. Live-confirmed: with X-Krita-Version=28 present, Krita
    # never listed the plugin in the Python Plugin Manager at all, even
    # with X-KDE-Library correctly set and the files deployed to the right
    # location.
    content = DESKTOP_FILE.read_text(encoding="utf-8")
    assert "X-Krita-Version" not in content


def test_kritarc_path_is_platform_specific_and_not_the_pykrita_dir(monkeypatch):
    # kritarc lives under LOCALAPPDATA on Windows, NOT the same APPDATA/krita
    # directory the pykrita plugin files are deployed to - mixing these up
    # means writes silently land in the wrong place. Forward slashes here
    # (matching the existing GIMP platform test) avoid POSIX-vs-Windows
    # path-separator ambiguity when this test runs on a non-Windows CI box.
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/u/AppData/Local")
    monkeypatch.setenv("APPDATA", "C:/Users/u/AppData/Roaming")
    assert launcher._kritarc_path() == Path("C:/Users/u/AppData/Local/kritarc")
    assert launcher.krita_plugin_dir() == Path("C:/Users/u/AppData/Roaming/krita/pykrita")


def test_enable_krita_plugin_creates_file_and_section(tmp_path, monkeypatch):
    fake_kritarc = tmp_path / "kritarc"
    monkeypatch.setattr(launcher, "_kritarc_path", lambda: fake_kritarc)

    launcher.enable_krita_plugin("pixelpilot_krita")

    assert fake_kritarc.is_file()
    parser = configparser.ConfigParser()
    parser.read(fake_kritarc)
    assert parser.get("python", "enable_pixelpilot_krita") == "true"


def test_enable_krita_plugin_preserves_existing_settings(tmp_path, monkeypatch):
    fake_kritarc = tmp_path / "kritarc"
    fake_kritarc.write_text(
        "[General]\nSomeExistingUserSetting=keepme\n\n[python]\nenable_other_plugin=true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "_kritarc_path", lambda: fake_kritarc)

    launcher.enable_krita_plugin("pixelpilot_krita")

    parser = configparser.ConfigParser()
    parser.read(fake_kritarc)
    assert parser.get("General", "SomeExistingUserSetting") == "keepme"
    assert parser.get("python", "enable_other_plugin") == "true"
    assert parser.get("python", "enable_pixelpilot_krita") == "true"


def test_enable_krita_plugin_never_raises_on_unwritable_path(monkeypatch):
    # A directory that can never be created (parent is a file, not a dir)
    # must degrade silently, not crash the launch flow.
    def _boom(*a, **k):
        raise OSError("simulated permission error")

    monkeypatch.setattr(launcher, "_kritarc_path", lambda: Path("/nonexistent/kritarc"))
    monkeypatch.setattr(Path, "mkdir", _boom)

    launcher.enable_krita_plugin("pixelpilot_krita")  # must not raise


def test_launch_fails_fast_when_krita_already_running(monkeypatch, tmp_path):
    # Reproduces the exact live failure: Krita already open, bridge port
    # closed. Must not spawn another process or poll for the full timeout -
    # it must raise immediately with actionable guidance.
    monkeypatch.setattr(launcher, "_port_is_open", lambda host, port: False)
    monkeypatch.setattr(launcher, "_krita_process_running", lambda: True)

    deploy_calls = []
    enable_calls = []
    monkeypatch.setattr(launcher, "deploy_krita_plugin", lambda: deploy_calls.append(1))
    monkeypatch.setattr(launcher, "verify_krita_plugin", lambda: (True, "ok"))
    monkeypatch.setattr(launcher, "enable_krita_plugin", lambda name: enable_calls.append(name))

    def _must_not_be_called(*a, **k):
        raise AssertionError("must not spawn a new process when Krita is already running")

    monkeypatch.setattr(launcher.subprocess, "Popen", _must_not_be_called)

    with pytest.raises(launcher.LauncherError, match="already running"):
        launcher.launch_krita_and_wait(timeout=90.0)

    # Files should still be deployed/enabled so they're ready for when the
    # user does restart Krita - just not launched into the stale process.
    assert deploy_calls == [1]
    assert enable_calls == ["pixelpilot_krita"]


def test_launch_proceeds_normally_when_krita_not_running(monkeypatch):
    monkeypatch.setattr(launcher, "_port_is_open", lambda host, port: False)
    monkeypatch.setattr(launcher, "_krita_process_running", lambda: False)
    monkeypatch.setattr(launcher, "find_krita_binary", lambda configured: "/fake/krita")
    monkeypatch.setattr(launcher, "deploy_krita_plugin", lambda: None)
    monkeypatch.setattr(launcher, "verify_krita_plugin", lambda: (True, "ok"))
    monkeypatch.setattr(launcher, "enable_krita_plugin", lambda name: None)

    popen_calls = []
    monkeypatch.setattr(
        launcher.subprocess, "Popen",
        lambda *a, **k: popen_calls.append((a, k)),
    )
    # Simulate the bridge coming up right after launch.
    call_count = {"n": 0}
    def _port_check(host, port):
        call_count["n"] += 1
        return call_count["n"] > 1
    monkeypatch.setattr(launcher, "_port_is_open", _port_check)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)

    result = launcher.launch_krita_and_wait(timeout=5.0)

    assert result is True
    assert len(popen_calls) == 1
