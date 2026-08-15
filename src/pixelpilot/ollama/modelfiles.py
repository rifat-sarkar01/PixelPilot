"""Custom Modelfile creation & management.

Bundles the PixelPilot-tuned Modelfiles (see ``implementation_plan.md`` §2.5) and
installs them into Ollama via ``POST /api/create``.
"""

from __future__ import annotations

from rich.console import Console

from pixelpilot.ollama.client import OllamaClient

CODER_MODELFILE = """FROM qwen2.5-coder:14b

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_predict 4096
PARAMETER num_ctx 8192
PARAMETER stop "<|endoftext|>"
PARAMETER stop "```\\n\\n"

SYSTEM \"\"\"You are PixelPilot, an expert AI assistant that generates executable Python scripts for GIMP and Krita image editors.

RULES:
1. Output ONLY valid, executable Python code inside a single fenced ```python code block.
2. Include inline comments explaining each step.
3. NEVER import os, sys, subprocess, socket, http, urllib, shutil, or pathlib.
4. ONLY import from: gimp, gimpfu, Krita, math, random, colorsys, json, re, struct.
5. Always check if layers/images exist before operating on them.
6. Use non-destructive techniques when possible (new layers, masks).
7. After modifying pixels, call the appropriate display refresh function.
8. Wrap multi-step operations in undo groups.
9. Handle errors gracefully with try/except.
10. If you're unsure about an API call, say so — don't guess.\"\"\"
"""

VISION_MODELFILE = """FROM llama3.2-vision:11b

PARAMETER temperature 0.3
PARAMETER num_predict 2048
PARAMETER num_ctx 4096

SYSTEM \"\"\"You are PixelPilot Vision, an AI that analyzes images from photo editing software.
When shown a screenshot of a canvas, describe:
1. What the current state of the image looks like
2. Whether the last editing operation achieved the intended result
3. What specific adjustments would improve the result
Be precise about colors, positions, and visual qualities. Reference specific regions (top-left, center, etc.).\"\"\"
"""

CUSTOM_MODELS: list[str] = ["pixelpilot-coder", "pixelpilot-vision"]


def coder_modelfile_text() -> str:
    return CODER_MODELFILE


def vision_modelfile_text() -> str:
    return VISION_MODELFILE


def _create_with_progress(client: OllamaClient, name: str, modelfile: str, console: Console) -> None:
    console.print(f"  → creating [bold]{name}[/bold] ...")
    stream = client.create_model(name, modelfile, stream=True)
    for chunk in stream:
        if chunk.get("error"):
            raise RuntimeError(f"Failed to create {name}: {chunk['error']}")
        status = chunk.get("status", "")
        if status:
            console.print(f"    {status}")
    console.print(f"    ✓ [green]{name}[/green] ready")


def install_modelfiles(base_url: str = "http://localhost:11434") -> None:
    """Create both custom PixelPilot models in Ollama (streaming progress)."""
    console = Console()
    console.rule("PixelPilot model setup")

    client = OllamaClient(base_url)
    client.health_check()
    console.print(f"    ✓ Ollama reachable at [cyan]{base_url}[/cyan]")

    _create_with_progress(client, "pixelpilot-coder", CODER_MODELFILE, console)
    _create_with_progress(client, "pixelpilot-vision", VISION_MODELFILE, console)

    console.rule()
    console.print("  [green]Done.[/green] Models: pixelpilot-coder, pixelpilot-vision")
    console.print("  Run:  pixelpilot --editor gimp")
