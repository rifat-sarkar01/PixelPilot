"""Typed configuration management.

Schema mirrors ``implementation_plan.md`` §7.2. Configuration is loaded from a YAML file
(``~/.config/pixelpilot/config.yaml`` by default) and may be overridden by environment
variables prefixed with ``PIXELPILOT_`` (e.g. ``PIXELPILOT_OLLAMA_BASE_URL``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

APP_DIR_NAME = "pixelpilot"


class OllamaSettings(BaseModel):
    base_url: str = "http://localhost:11434"
    code_model: str = "pixelpilot-coder"
    vision_model: str = "pixelpilot-vision"
    embed_model: str = "nomic-embed-text"

    temperature: float = 0.2
    num_predict: int = 4096
    num_ctx: int = 8192

    keep_vision_loaded: bool = False
    auto_select_models: bool = True
    stream: bool = True
    think: bool = False


class EditorBackendSettings(BaseModel):
    binary_path: str | None = None
    connection: str = "plugin"
    host: str = "localhost"
    port: int = 10010
    auto_launch: bool = True
    launch_timeout: float = 90.0


class EditorSettings(BaseModel):
    default: str = "gimp"
    gimp: EditorBackendSettings = Field(default_factory=lambda: EditorBackendSettings(port=10010))
    krita: EditorBackendSettings = Field(
        default_factory=lambda: EditorBackendSettings(
            port=10020,
            binary_path="D:/Krita",
        )
    )


class SafetySettings(BaseModel):
    mode: str = "preview"  # auto | preview | strict | dry-run
    max_script_lines: int = 500
    max_execution_time: int = 60
    allowed_read_dirs: list[str] = Field(default_factory=lambda: ["~/Pictures", "~/Documents/Projects"])
    allowed_write_dirs: list[str] = Field(default_factory=lambda: ["~/Pictures/PixelPilot_Output"])


class FeedbackSettings(BaseModel):
    auto_screenshot: bool = True
    auto_correct: bool = False
    max_retries: int = 3
    screenshot_resolution: list[int] = Field(default_factory=lambda: [512, 384])
    vision_enabled: bool = True


class RAGSettings(BaseModel):
    db_path: str = "~/.config/pixelpilot/chromadb"
    top_k_procedures: int = 8
    top_k_examples: int = 2
    rebuild_on_update: bool = True


class SessionSettings(BaseModel):
    history_file: str = "~/.config/pixelpilot/history.json"
    max_history_turns: int = 5
    summarize_after: int = 5
    auto_save_scripts: bool = True
    script_output_dir: str = "~/.config/pixelpilot/scripts"


class Settings(BaseModel):
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    editor: EditorSettings = Field(default_factory=EditorSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    feedback: FeedbackSettings = Field(default_factory=FeedbackSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)


_ENV_PREFIX = "PIXELPILOT_"


def config_dir() -> Path:
    """Return the platform-appropriate PixelPilot config directory."""
    override = os.environ.get("PIXELPILOT_CONFIG_DIR")
    if override:
        return Path(override).expanduser()

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_DIR_NAME

    return Path.home() / ".config" / APP_DIR_NAME


def default_config_path() -> Path:
    return config_dir() / "config.yaml"


def _expand_path(value: object) -> object:
    if isinstance(value, str) and value.startswith("~"):
        return str(Path(value).expanduser())
    if isinstance(value, list):
        return [_expand_path(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_path(v) for k, v in value.items()}
    return value


def load_settings(path: Path | None = None, env_overrides: bool = True) -> Settings:
    """Load settings from ``path`` (or the default location), then apply env overrides."""
    cfg_path = Path(path).expanduser() if path else default_config_path()

    data: dict = {}
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        data = raw if isinstance(raw, dict) else {}

    if env_overrides:
        _apply_env_overrides(data)

    data = _expand_path(data)  # type: ignore[assignment]
    return Settings.model_validate(data)


def _apply_env_overrides(data: dict) -> None:
    """Merge ``PIXELPILOT_A_B_C`` env vars into the nested dict as ``data[A][B]=C``."""
    for key, value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        rest = key[len(_ENV_PREFIX):]
        parts = [p.lower() for p in rest.split("_")]
        if not parts:
            continue
        section = parts[0]
        field = "_".join(parts[1:])
        if not field:
            continue
        node = data.setdefault(section, {})
        if isinstance(node, dict):
            node[field] = value


def ensure_config_file() -> Path:
    """Write a default config file if none exists; returns the path."""
    path = default_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        settings = Settings()
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                settings.model_dump(),
                fh,
                default_flow_style=False,
                sort_keys=False,
            )
    return path
