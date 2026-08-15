"""Unit tests for configuration loading."""

import os
from pathlib import Path

from pixelpilot.config import Settings, load_settings


def test_defaults():
    settings = Settings()
    assert settings.ollama.base_url == "http://localhost:11434"
    assert settings.ollama.code_model == "pixelpilot-coder"
    assert settings.editor.default == "gimp"
    assert settings.safety.mode == "preview"


def test_load_from_yaml(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "ollama:\n"
        "  base_url: \"http://10.0.0.5:11434\"\n"
        "  code_model: \"qwen2.5-coder:7b\"\n"
        "editor:\n"
        "  default: \"krita\"\n",
        encoding="utf-8",
    )
    settings = load_settings(cfg, env_overrides=False)
    assert settings.ollama.base_url == "http://10.0.0.5:11434"
    assert settings.ollama.code_model == "qwen2.5-coder:7b"
    assert settings.editor.default == "krita"


def test_env_overrides(tmp_path):
    os.environ["PIXELPILOT_OLLAMA_BASE_URL"] = "http://example:1234"
    os.environ["PIXELPILOT_SAFETY_MODE"] = "strict"
    try:
        settings = load_settings(tmp_path / "nonexistent.yaml")
    finally:
        del os.environ["PIXELPILOT_OLLAMA_BASE_URL"]
        del os.environ["PIXELPILOT_SAFETY_MODE"]
    assert settings.ollama.base_url == "http://example:1234"
    assert settings.safety.mode == "strict"


def test_paths_expanded(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "safety:\n  allowed_write_dirs:\n    - \"~/Pictures/Out\"\n",
        encoding="utf-8",
    )
    settings = load_settings(cfg, env_overrides=False)
    expected = str(Path("~/Pictures/Out").expanduser())
    assert settings.safety.allowed_write_dirs[0] == expected


def test_load_missing_file_gives_defaults(tmp_path):
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.ollama.embed_model == "nomic-embed-text"
