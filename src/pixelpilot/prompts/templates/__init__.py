"""Jinja2-free string templates for prompt composition."""

from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent

_TEMPLATE_CACHE: dict = {}


def render(template_name: str, **variables: object) -> str:
    """Render a template from this directory using ``string.Template`` ($name syntax)."""
    import string

    if template_name not in _TEMPLATE_CACHE:
        path = TEMPLATE_DIR / template_name
        if not path.exists():
            raise FileNotFoundError(f"Unknown prompt template: {template_name}")
        _TEMPLATE_CACHE[template_name] = path.read_text(encoding="utf-8")
    return string.Template(_TEMPLATE_CACHE[template_name]).safe_substitute(**variables)
