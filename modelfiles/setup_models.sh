#!/usr/bin/env bash
# Create the PixelPilot custom Ollama models.
#
#   ./setup_models.sh
#
# Pulls the base models (if missing) and builds:
#   pixelpilot-coder   (from Modelfile.pixelpilot-coder)
#   pixelpilot-vision  (from Modelfile.pixelpilot-vision)
#
# Requires a running Ollama server (http://localhost:11434).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CODER_BASE="qwen2.5-coder:14b"
VISION_BASE="llama3.2-vision:11b"
EMBED_BASE="nomic-embed-text"

echo "==> Ensuring base models are available"
for model in "$CODER_BASE" "$VISION_BASE" "$EMBED_BASE"; do
  if ollama list | grep -q "^${model%:*}\s"; then
    echo "    ✓ $model already present"
  else
    echo "    ↓ pulling $model"
    ollama pull "$model"
  fi
done

echo "==> Creating custom Modelfiles"
ollama create pixelpilot-coder -f "$DIR/Modelfile.pixelpilot-coder"
ollama create pixelpilot-vision -f "$DIR/Modelfile.pixelpilot-vision"

echo "==> Done."
echo "    Models: pixelpilot-coder, pixelpilot-vision"
echo "    Run:    pixelpilot --editor gimp"
