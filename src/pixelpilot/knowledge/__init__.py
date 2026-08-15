"""Loaders for the bundled API knowledge base.

Knowledge is stored as structured JSON (see ``knowledge/``). These loaders return
plain lists of dicts that the RAG indexer embeds and the safety validator consults.
"""

from __future__ import annotations

import json
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent

_CACHE: dict[str, object] = {}


def _load_json(name: str) -> list:
    if name in _CACHE:
        return list(_CACHE[name])  # type: ignore[arg-type]
    path = KNOWLEDGE_DIR / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Support both bare lists and {"meta":..., "items":[...]} wrappers.
    if isinstance(data, dict):
        result = None
        for key in ("procedures", "methods", "items"):
            if isinstance(data.get(key), list):
                result = data[key]
                break
        data = result if result is not None else []
    _CACHE[name] = data
    return list(data)


def load_gimp_pdb() -> list:
    """Return the GIMP PDB catalog as a list of procedure dicts."""
    return _load_json("gimp_pdb.json")


def load_krita_api() -> list:
    """Return the Krita API catalog as a list of method dicts."""
    return _load_json("krita_api.json")


def load_examples(editor: str = "gimp") -> list[dict]:
    """Load curated few-shot examples for an editor from ``knowledge/examples/``."""
    editor_dir = KNOWLEDGE_DIR / "examples" / editor
    examples: list[dict] = []
    if not editor_dir.exists():
        return examples
    for path in sorted(editor_dir.glob("*.py")):
        code = path.read_text(encoding="utf-8")
        examples.append(
            {
                "prompt": _example_prompt(path),
                "code": code,
                "category": path.stem.split("_")[0],
                "file": path.name,
            }
        )
    return examples


def _example_prompt(path: Path) -> str:
    """Extract the natural-language prompt from an example file's docstring."""
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    for quote in ('"""', "'''"):
        if stripped.startswith(quote):
            end = stripped.find(quote, len(quote))
            if end != -1:
                return stripped[len(quote) : end].strip()
    return f"(example: {path.name})"


def get_procedure_by_name(name: str, editor: str = "gimp") -> dict | None:
    """Look up a procedure by name in the catalog (used by the API validator)."""
    catalog = load_gimp_pdb() if editor == "gimp" else load_krita_api()
    for entry in catalog:
        if entry.get("name") == name:
            return entry
        for key in ("legacy_name", "gimp3_name"):
            if entry.get(key) == name:
                return entry
    return None


def known_api_names(editor: str = "gimp") -> set:
    """All known procedure/API tokens for an editor.

    Returns a permissive set so the validator can match the many spellings scripts use:
    ``gimp-image-list``, ``gimp_image_list``, ``gimp.image_list()``, ``pdb.gimp_image_list``,
    ``image_list``, and Krita ``Document.refreshProjection`` / ``refreshProjection``.
    """
    catalog = load_gimp_pdb() if editor == "gimp" else load_krita_api()
    names = set()
    for entry in catalog:
        raw = {entry.get("name"), entry.get("legacy_name"), entry.get("gimp3_name")}
        raw.discard(None)
        for name in raw:
            if not name:
                continue
            names.add(name)
            names.add(name.replace("-", "_"))
            if "." in name:
                names.add(name.split(".")[-1])
        leaf = entry.get("name", "")
        names.add(leaf.split(".")[-1].replace("-", "_"))
    return names
