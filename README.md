# PixelPilot

A fully offline, privacy-first AI image editing system. Local [Ollama](https://ollama.com)
models translate natural-language intent into executable Python scripts for **GIMP** and
**Krita**. No cloud. No API keys. No data leaves your machine.

```
User Intent (natural language)
       ↓
   Ollama LLM (local reasoning + code generation)
       ↓
   Command Translator (script generation + safety validation)
       ↓
   Editor Bridge (GIMP / Krita IPC)
       ↓
   Photo Editor (executes commands)
       ↓
   Feedback Loop (screenshot -> Ollama vision model for refinement)
```

## Status

**Phase 1 MVP scaffold.** This repository currently provides the full package skeleton plus
working, unit-tested implementations of the core building blocks:

- Ollama REST API client (direct `httpx`, no wrapper libraries)
- Auto model selection (VRAM-aware)
- Custom Modelfile management
- Layered prompt builder with context-budget enforcement
- Local RAG (semantic API-procedure retrieval, `nomic-embed-text`)
- Safety validator (AST analysis + import allowlisting + API hallucination detection)
- Intermediate representation + GIMP/Krita code generators
- Editor bridge interface with canvas-state tracking
- Feedback modules (vision + text-only fallback + error recovery)
- Rich-based CLI / REPL
- GIMP & Krita plugin skeletons

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running on `http://localhost:11434`
- Recommended models (see `implementation_plan.md` §2.2–2.4):
  - Code: `qwen2.5-coder:14b` (default)
  - Vision: `llama3.2-vision:11b` (optional)
  - Embeddings: `nomic-embed-text`

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
# Create and install the custom Modelfiles (also pulls base models)
pixelpilot setup

# Build the RAG index over the bundled knowledge base
pixelpilot init-knowledge

# Start the interactive CLI
pixelpilot --editor gimp
```

If Ollama isn't running, the CLI falls back to a **demo mode** so you can still explore the
validation, RAG, and IR pipeline with canned output.

If GIMP isn't already running with the PixelPilot bridge plugin, `pixelpilot --editor gimp`
now finds your GIMP 2.10 install, deploys the plugin, and launches GIMP for you (this can
take up to ~90s the first time). If it can't find GIMP automatically, set
`editor.gimp.binary_path` in your config, or run `/connect` inside the CLI to retry after
opening GIMP yourself. Krita still needs to be started manually with the PixelPilot plugin
enabled in Krita's plugin manager.

## Configuration

Typed config lives at `~/.config/pixelpilot/config.yaml` (auto-generated on first run).
See `implementation_plan.md` §7.2 for the full schema. Environment variables prefixed with
`PIXELPILOT_` override YAML values. Relevant to launching the editor:

```yaml
editor:
  gimp:
    binary_path: null      # e.g. "C:\Program Files\GIMP 2\bin\gimp-2.10.exe" if auto-detect fails
    auto_launch: true      # set false to manage GIMP yourself
    launch_timeout: 90.0   # seconds to wait for the bridge to come up
```

## Project Layout

```
src/pixelpilot/
├── ollama/        # Direct REST API client, model management, streaming
├── prompts/       # Layered prompt builder + context budget manager
├── rag/           # Local semantic retrieval (indexer/retriever/store)
├── codegen/       # IR, GIMP/Krita generators, safety validator, sandbox
├── bridge/        # Editor bridge abstraction + canvas state tracking
├── feedback/      # Vision analysis, text fallback, error recovery
├── knowledge/     # GIMP PDB / Krita API catalog + few-shot examples
└── ui/            # CLI / REPL
```

## Testing

```bash
pytest
```

All unit tests run without Ollama, GIMP, or Krita installed.

## License

MIT. PixelPilot communicates with GIMP/Krita over IPC (it does not link against them).

See [implementation_plan.md](./implementation_plan.md) for the full design document.
