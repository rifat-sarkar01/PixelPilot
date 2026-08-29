# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PixelPilot
# Build with:  .venv\Scripts\pyinstaller.exe pixelpilot.spec

import sys
from pathlib import Path

src = Path("src/pixelpilot")

a = Analysis(
    ["src/pixelpilot/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        # Knowledge base (JSON + example scripts)
        (str(src / "knowledge" / "gimp_pdb.json"),      "pixelpilot/knowledge"),
        (str(src / "knowledge" / "krita_api.json"),     "pixelpilot/knowledge"),
        (str(src / "knowledge" / "examples" / "gimp"),  "pixelpilot/knowledge/examples/gimp"),
        (str(src / "knowledge" / "examples" / "krita"), "pixelpilot/knowledge/examples/krita"),
        # Prompt templates
        (str(src / "prompts" / "templates"),            "pixelpilot/prompts/templates"),
    ],
    hiddenimports=[
        # Lazy-imported modules that PyInstaller can miss
        "pixelpilot.feedback.vision",
        "pixelpilot.feedback.vision_planner",
        "pixelpilot.feedback.error_recovery",
        "pixelpilot.feedback.text_fallback",
        "pixelpilot.ollama.streaming",
        "pixelpilot.ollama.models",
        "pixelpilot.ollama.modelfiles",
        "pixelpilot.rag.indexer",
        "pixelpilot.rag.retriever",
        "pixelpilot.codegen",
        "pixelpilot.prompts.system",
        "yaml",
        "pydantic",
        "rich",
        "prompt_toolkit",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional packages not needed at runtime
        "chromadb",
        "torch",
        "tensorflow",
        "matplotlib",
        "scipy",
        "numpy",  # only exclude if your code doesn't need it directly
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pixelpilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # Keep True - PixelPilot is a console REPL
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Optional: set an icon if you have one
    # icon="assets/pixelpilot.ico",
)
