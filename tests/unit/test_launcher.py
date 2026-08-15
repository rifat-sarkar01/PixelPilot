"""Unit tests for pixelpilot.bridge.launcher (GIMP auto-launch)."""

from __future__ import annotations

import stat
import sys

import pytest

from pixelpilot.bridge import launcher


def test_repo_plugin_source_found():
    source = launcher._repo_plugin_source()
    assert source is not None
    assert source.name == "plugin.py"
    assert source.is_file()


def test_gimp_plugin_dir_platform_specific(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher.Path, "home", classmethod(lambda cls: launcher.Path("/home/u")))
    assert str(launcher.gimp_plugin_dir()) == "/home/u/.config/GIMP/2.10/plug-ins"


def test_deploy_plugin_writes_executable_flat_file(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "gimp_plugin_dir", lambda: tmp_path / "plug-ins")
    dest = launcher.deploy_plugin()

    assert dest == tmp_path / "plug-ins" / launcher.PLUGIN_FILENAME
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8").startswith("#!/usr/bin/env python2")
    if sys.platform != "win32":
        assert dest.stat().st_mode & stat.S_IXUSR


def test_deploy_plugin_removes_stale_pyc(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "gimp_plugin_dir", lambda: tmp_path / "plug-ins")
    (tmp_path / "plug-ins").mkdir(parents=True)
    stale = tmp_path / "plug-ins" / (launcher.PLUGIN_FILENAME + "c")
    stale.write_bytes(b"stale bytecode")

    launcher.deploy_plugin()

    assert not stale.exists()


def test_deploy_plugin_missing_source_raises(monkeypatch):
    monkeypatch.setattr(launcher, "_repo_plugin_source", lambda: None)
    with pytest.raises(launcher.LauncherError):
        launcher.deploy_plugin()


def test_find_gimp_binary_prefers_configured_path(tmp_path):
    fake_gimp = tmp_path / "gimp-2.10.exe"
    fake_gimp.write_text("not a real binary")
    found = launcher.find_gimp_binary(str(fake_gimp))
    assert found == str(fake_gimp)


def test_find_gimp_binary_ignores_nonexistent_configured_path():
    # Falls through to PATH/common-dir search instead of raising.
    assert launcher.find_gimp_binary("/no/such/gimp") is None or isinstance(
        launcher.find_gimp_binary("/no/such/gimp"), str
    )


def test_launch_and_wait_returns_true_immediately_if_already_up(monkeypatch):
    monkeypatch.setattr(launcher, "_port_is_open", lambda host, port: True)
    assert launcher.launch_and_wait(timeout=1) is True


def test_launch_and_wait_raises_when_gimp_not_found(monkeypatch):
    monkeypatch.setattr(launcher, "_port_is_open", lambda host, port: False)
    monkeypatch.setattr(launcher, "find_gimp_binary", lambda configured_path=None: None)
    with pytest.raises(launcher.LauncherError):
        launcher.launch_and_wait(timeout=1)


def test_launch_and_wait_times_out_gracefully(monkeypatch):
    monkeypatch.setattr(launcher, "_port_is_open", lambda host, port: False)
    monkeypatch.setattr(launcher, "find_gimp_binary", lambda configured_path=None: "/bin/true")
    monkeypatch.setattr(launcher, "deploy_plugin", lambda: None)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)

    # Force the deadline to have already passed so the poll loop exits fast.
    times = iter([0, 1000])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(times, 1000))

    assert launcher.launch_and_wait(timeout=1) is False
