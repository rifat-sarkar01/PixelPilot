"""Entry point and top-level command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pixelpilot import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixelpilot",
        description="Local Ollama-powered photo editor controller (GIMP/Krita).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to config YAML file")
    parser.add_argument("--editor", type=str, choices=["gimp", "krita"], default=None,
                        help="Target editor (overrides config)")
    parser.add_argument("--model", type=str, default=None, help="Code/coding LLM model to use (overrides config)")
    parser.add_argument("--vision-model", type=str, default=None, dest="vision_model",
                        help="Vision LLM model to use (overrides config)")
    parser.add_argument("--mode", type=str, choices=["auto", "preview", "strict", "dry-run"],
                        default=None, help="Safety confirmation mode")
    parser.add_argument("--no-vision", action="store_true", help="Disable vision feedback")
    parser.add_argument("--think", action="store_true", default=None,
                        help="Enable thinking/reasoning pass for hybrid models (e.g. qwen3)")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Install custom Modelfiles into Ollama (pulls base models)")
    sub.add_parser("init-knowledge", help="Build the local RAG index over the bundled knowledge base")
    sub.add_parser("models", help="List installed Ollama models and recommended selection")
    return parser


def _cmd_setup(args: argparse.Namespace) -> int:
    from pixelpilot.config import load_settings
    from pixelpilot.ollama.modelfiles import install_modelfiles

    settings = load_settings(args.config)
    install_modelfiles(settings.ollama.base_url)
    return 0


def _cmd_init_knowledge(args: argparse.Namespace) -> int:
    from pixelpilot.config import load_settings
    from pixelpilot.rag.indexer import build_index

    settings = load_settings(args.config)
    report = build_index(settings)
    print(report)
    return 0


def _cmd_models(args: argparse.Namespace) -> int:
    from pixelpilot.config import load_settings
    from pixelpilot.ollama.client import OllamaClient
    from pixelpilot.ollama.models import list_installed_models, recommend_models

    settings = load_settings(args.config)
    client = OllamaClient(settings.ollama.base_url)
    models = list_installed_models(client)
    print("Installed models:")
    for model in models:
        size_gb = model.size / (1024 ** 3) if model.size else 0.0
        print(f"  - {model.name:<32} {size_gb:6.2f} GB")
    print()
    rec = recommend_models(models, settings)
    if rec.code_model:
        print(f"Recommended code model:  {rec.code_model}")
    if rec.vision_model:
        print(f"Recommended vision model: {rec.vision_model}")
    print(f"Embedding model:         {rec.embed_model}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from pixelpilot.ui.cli import run_cli

    return run_cli(args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from pixelpilot.ollama.client import OllamaAPIError, OllamaConnectionError

    try:
        if args.command == "setup":
            return _cmd_setup(args)
        if args.command == "init-knowledge":
            return _cmd_init_knowledge(args)
        if args.command == "models":
            return _cmd_models(args)
        return _cmd_run(args)
    except OllamaConnectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("Is Ollama running? Start it (e.g. `ollama serve`) and try again.", file=sys.stderr)
        return 1
    except OllamaAPIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
