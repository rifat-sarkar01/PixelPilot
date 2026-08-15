# PixelPilot — Local Ollama-Powered Photo Editor Controller

> **A fully offline, privacy-first AI image editing system. Local Ollama models translate natural-language intent into executable drawing/editing commands for GIMP and Krita. No cloud. No API keys. No data leaves your machine.**

---

## 1. Vision & Problem Statement

### 1.1 The Problem
Creative professionals and hobbyists face a steep learning curve with professional photo editors. GIMP has 400+ procedures in its PDB (Procedure Database); Krita exposes hundreds of Python API calls. Users must memorize menu paths, parameter orders, blending modes, and scripting syntax. This creates a massive barrier between *creative intent* and *execution*.

### 1.2 The Vision
**PixelPilot** bridges that gap. A user says *what* they want — a local Ollama LLM figures out *how* to do it. The entire pipeline runs on your machine:

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
   Rendered Image (visual output)
       ↓
   Feedback Loop (screenshot → Ollama vision model for refinement)
```

### 1.3 Why Fully Local?
| Principle | Rationale |
|---|---|
| **Privacy** | Your images, prompts, and creative work never leave your machine. No telemetry, no cloud logging. |
| **Zero Cost** | No API keys, no per-token billing, no subscription fees. Download a model and go. |
| **Offline** | Works on airplanes, in restricted environments, behind firewalls. No internet required after initial model download. |
| **Latency** | No network round-trips. With a decent GPU, responses come in under 2 seconds. |
| **Control** | You choose exactly which model runs, at what quantization, with what system prompt. Full transparency. |

### 1.4 Why Both GIMP and Krita?
| Aspect | GIMP | Krita |
|---|---|---|
| **Strength** | Photo manipulation, retouching, compositing | Digital painting, illustration, concept art |
| **Scripting** | Script-Fu (Scheme), Python-Fu | Python (PyKrita) |
| **Use Case** | Editing existing photos | Creating art from scratch |
| **Plugin Model** | Mature, large ecosystem | Modern, artist-focused |

Supporting both creates a **complete** image tool — one that can *edit* photographs **and** *create* original artwork — all driven by natural language, all running locally.

---

## 2. Ollama Infrastructure

> [!IMPORTANT]
> Ollama is the **only** LLM backend. This is not a provider-agnostic system. Every design decision optimizes for the Ollama REST API, local model management, and GPU-constrained environments.

### 2.1 Ollama Overview

Ollama is a local LLM runtime that:
- Downloads and manages GGUF-quantized models
- Serves an OpenAI-compatible REST API at `http://localhost:11434`
- Supports streaming, tool/function calling, multimodal (vision) input
- Handles GPU/CPU offloading, context management, and model loading automatically
- Runs on Windows, macOS, and Linux

**PixelPilot communicates exclusively via Ollama's REST API:**
```
POST http://localhost:11434/api/chat     → Conversational inference
POST http://localhost:11434/api/generate → Single-shot generation
POST http://localhost:11434/api/embed    → Text embeddings (for RAG)
GET  http://localhost:11434/api/tags     → List installed models
POST http://localhost:11434/api/show     → Model info & capabilities
POST http://localhost:11434/api/pull     → Download a model
```

### 2.2 Hardware Tiers & Model Recommendations

> [!IMPORTANT]
> The quality of generated scripts depends heavily on model size. Bigger models = better code. The table below maps hardware to the best usable model.

| Tier | GPU VRAM | RAM | Recommended Code Model | Recommended Vision Model | Experience |
|---|---|---|---|---|---|
| **Tier 1: Minimal** | No GPU / 4GB | 16GB | `qwen2.5-coder:7b` | `llava:7b` | Functional but slow. Simple edits only. Expect errors that need retries. |
| **Tier 2: Capable** | 8GB (RTX 3060/4060) | 16GB | `qwen2.5-coder:14b` | `llava:13b` | Good for most photo editing. Handles multi-step workflows. |
| **Tier 3: Strong** | 12–16GB (RTX 3080/4070 Ti) | 32GB | `qwen2.5-coder:32b` | `llama3.2-vision:11b` | Excellent code generation. Reliable complex workflows. |
| **Tier 4: Optimal** | 24GB (RTX 3090/4090) | 32GB+ | `qwen2.5-coder:32b-q8_0` | `llama3.2-vision:11b` | Near-cloud quality. Handles advanced compositing, batch ops. |
| **Tier 5: Workstation** | 48GB+ (dual GPU / A6000) | 64GB+ | `llama3.1:70b-q4_K_M` or `qwen2.5:72b` | `llama3.2-vision:90b` | Best possible local quality. Complex multi-step art pipelines. |

### 2.3 Model Selection Matrix

PixelPilot uses **two model slots** simultaneously:

| Slot | Purpose | Requirements | Default Model |
|---|---|---|---|
| **Code Model** | Generates Python scripts for GIMP/Krita | Strong code generation, instruction following, structured output | `qwen2.5-coder:14b` |
| **Vision Model** | Analyzes canvas screenshots for feedback loop | Multimodal input (text + image), visual reasoning | `llama3.2-vision:11b` |

**Why two models instead of one?**
- Dedicated code models (Qwen2.5-Coder, CodeLlama, DeepSeek-Coder) produce significantly better scripts than general-purpose models
- Vision models (LLaVA, Llama 3.2 Vision) are specialized for image understanding
- Ollama can swap models efficiently (warm model stays in VRAM; cold model loads from disk)
- Users with limited VRAM can disable the vision model and use text-only feedback

**Full Model Compatibility List:**

| Model | Size Options | Code Quality | Vision | Tool Calling | Notes |
|---|---|---|---|---|---|
| `qwen2.5-coder` | 1.5b, 3b, 7b, 14b, 32b | ★★★★★ | ✗ | ✓ | **Best code model for this use case.** Purpose-built for code generation. |
| `deepseek-coder-v2` | 16b, 236b | ★★★★★ | ✗ | ✓ | Excellent code, but large. Use if VRAM allows. |
| `codestral` | 22b | ★★★★☆ | ✗ | ✓ | Mistral's code model. Strong alternative. |
| `llama3.1` | 8b, 70b, 405b | ★★★★☆ | ✗ | ✓ | General purpose, very solid code gen at 70B+. |
| `qwen2.5` | 0.5b–72b | ★★★★☆ | ✗ | ✓ | General purpose. Good code at 14B+. |
| `mistral` | 7b | ★★★☆☆ | ✗ | ✓ | Decent for simple scripts. Fast. |
| `phi3` | 3.8b, 14b | ★★★☆☆ | ✗ | ✓ | Microsoft. Good quality/size ratio. |
| `llama3.2-vision` | 11b, 90b | ★★★☆☆ | ✓ | ✓ | **Best vision model.** Use for feedback loop. |
| `llava` | 7b, 13b, 34b | ★★☆☆☆ | ✓ | ✗ | Good vision, weaker code. Vision-only slot. |
| `moondream` | 1.8b | ★☆☆☆☆ | ✓ | ✗ | Tiny vision model. For minimal-VRAM vision fallback. |

### 2.4 Quantization Strategy

| Quantization | Size vs. Base | Quality Loss | When to Use |
|---|---|---|---|
| `q2_K` | ~30% | Significant | Absolute minimum VRAM. Last resort. |
| `q4_K_M` | ~45% | Minor | **Default.** Best quality/size balance. |
| `q5_K_M` | ~55% | Minimal | When VRAM allows. Noticeably better than q4. |
| `q6_K` | ~65% | Very slight | Near-lossless. Worth it if you have the VRAM. |
| `q8_0` | ~80% | Negligible | High VRAM systems. Almost no quality difference from f16. |
| `f16` | 100% | None | Only for workstation GPUs. Full precision. |

**PixelPilot auto-selects quantization:** On first run, it queries `ollama show <model>` to detect the loaded quantization and adjusts its prompt strategy accordingly (more explicit instructions for smaller quants).

### 2.5 Custom Modelfile for PixelPilot

PixelPilot ships with optimized Ollama Modelfiles that tune models specifically for script generation:

```dockerfile
# Modelfile.pixelpilot-coder
FROM qwen2.5-coder:14b

# Optimized parameters for code generation
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_predict 4096
PARAMETER num_ctx 8192
PARAMETER stop "<|endoftext|>"
PARAMETER stop "```\n\n"

SYSTEM """You are PixelPilot, an expert AI assistant that generates executable Python scripts for GIMP and Krita image editors.

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
10. If you're unsure about an API call, say so — don't guess."""
```

```dockerfile
# Modelfile.pixelpilot-vision
FROM llama3.2-vision:11b

PARAMETER temperature 0.3
PARAMETER num_predict 2048
PARAMETER num_ctx 4096

SYSTEM """You are PixelPilot Vision, an AI that analyzes images from photo editing software.
When shown a screenshot of a canvas, describe:
1. What the current state of the image looks like
2. Whether the last editing operation achieved the intended result
3. What specific adjustments would improve the result
Be precise about colors, positions, and visual qualities. Reference specific regions (top-left, center, etc.)."""
```

**Installation command PixelPilot runs automatically:**
```bash
ollama create pixelpilot-coder -f Modelfile.pixelpilot-coder
ollama create pixelpilot-vision -f Modelfile.pixelpilot-vision
```

### 2.6 Ollama Connection Management

```
OllamaManager:
  connect()                          → Verify Ollama is running at configured URL
  ensure_model(model_name)           → Check if model is pulled; pull if not
  get_loaded_models()                → Which models are currently in VRAM
  get_model_info(model_name)         → Size, quant, context length, capabilities
  estimate_vram(model_name)          → Estimated VRAM usage
  
  generate(prompt, model, images?)   → Single-shot generation
  chat(messages, model, images?)     → Multi-turn conversation
  embed(texts, model)                → Generate embeddings for RAG
  
  health_check()                     → Is Ollama responding?
  auto_select_models()               → Pick best code + vision models for available VRAM
```

**Auto-Model Selection Logic:**
```
1. Query system GPU VRAM (via nvidia-smi / Ollama API)
2. Query installed models (ollama list)
3. From installed models, pick the largest code model that fits in VRAM
4. If VRAM remains, pick the largest vision model
5. If no vision model fits, disable vision feedback (text-only mode)
6. If no models installed, prompt user to pull recommended models
```

### 2.7 Context Window Budget

Local models have smaller context windows than cloud models. Every token counts.

| Component | Token Budget | Strategy |
|---|---|---|
| **System prompt (core)** | ~500 tokens | Fixed. Identity, rules, output format. |
| **API reference (dynamic)** | ~1500 tokens | RAG-retrieved. Only inject relevant procedures. |
| **Canvas state** | ~200 tokens | Structured JSON snapshot. Compact. |
| **Few-shot examples** | ~800 tokens | 1–2 relevant examples max (not 3). |
| **Conversation history** | ~2000 tokens | Aggressive summarization. Keep last 3–5 turns. |
| **User message** | ~200 tokens | Current request. |
| **Reserved for output** | ~2000 tokens | Model's generation space. |
| **Total budget** | ~7200 tokens | Fits in 8K context. Scale up for 32K+ models. |

**Context Window Scaling:**
- 4K models (tiny): Minimize everything. 1 example. No history. Bare API docs.
- 8K models (standard): Default budget above.
- 16K models: More history (10 turns), more examples (3), fuller API docs.
- 32K+ models: Full API section injection, complete history, 5 examples.

---

## 3. Core Architecture

### 3.1 High-Level System Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      USER INTERFACE LAYER                     │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │  CLI / REPL  │  │  Web UI      │  │  Editor Plugin UI   │  │
│  │  (Day 1)     │  │  (Phase 2)   │  │  (GIMP/Krita dock)  │  │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬───────────┘  │
│         └─────────────────┼─────────────────────┘              │
│                           ↓                                    │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              ORCHESTRATION LAYER (Python)               │    │
│  │                                                         │    │
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │    │
│  │  │ Session Mgr  │  │ Conversation │  │  Task Planner │  │    │
│  │  │ (state, ctx) │  │   Memory     │  │  (multi-step) │  │    │
│  │  └──────────────┘  └──────────────┘  └───────────────┘  │    │
│  │                                                         │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │           OLLAMA INTERFACE (direct REST API)     │    │    │
│  │  │  Code Model:   qwen2.5-coder:14b                │    │    │
│  │  │  Vision Model:  llama3.2-vision:11b              │    │    │
│  │  │  Embed Model:   nomic-embed-text                 │    │    │
│  │  │  Endpoint:      http://localhost:11434            │    │    │
│  │  └──────────────────────┬──────────────────────────┘    │    │
│  │                         ↓                                │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │         COMMAND TRANSLATION ENGINE               │    │    │
│  │  │  ┌──────────────┐  ┌───────────────────────┐    │    │    │
│  │  │  │ GIMP Codegen │  │ Krita Codegen         │    │    │    │
│  │  │  │ (Python-Fu)  │  │ (PyKrita / libkis)    │    │    │    │
│  │  │  └──────────────┘  └───────────────────────┘    │    │    │
│  │  │  ┌──────────────────────────────────────────┐   │    │    │
│  │  │  │ Safety Validator & Sandboxer              │   │    │    │
│  │  │  └──────────────────────────────────────────┘   │    │    │
│  │  └──────────────────────┬──────────────────────────┘    │    │
│  └─────────────────────────┼───────────────────────────────┘    │
│                            ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                 EDITOR BRIDGE LAYER                      │    │
│  │  ┌──────────────────┐    ┌────────────────────────┐     │    │
│  │  │  GIMP Bridge     │    │  Krita Bridge          │     │    │
│  │  │  • D-Bus IPC     │    │  • TCP/Unix Socket     │     │    │
│  │  │  • Script-Fu     │    │  • PyKrita Plugin      │     │    │
│  │  │    console pipe  │    │  • Krita --script      │     │    │
│  │  │  • Batch mode    │    │  • Batch mode           │     │    │
│  │  └──────────────────┘    └────────────────────────┘     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                            ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              FEEDBACK & OBSERVATION LAYER                │    │
│  │  • Screenshot capture after each command batch           │    │
│  │  • Ollama vision model analyzes result                   │    │
│  │  • Error capture & retry logic                           │    │
│  │  • Text-only fallback (canvas state description)         │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Design Principles

1. **Ollama-Native** — Every LLM interaction goes through Ollama's REST API. No abstraction layers for providers that don't exist. Direct, efficient, purpose-built.
2. **Editor-Agnostic Core** — The orchestration layer never speaks "GIMP" or "Krita" directly. It speaks an intermediate representation (IR) that the codegen backends translate.
3. **Safety-First Execution** — No generated script touches the filesystem, network, or OS outside the sandbox. All generated code is validated before execution.
4. **Iterative Refinement** — The vision model sees the *result* of commands (via screenshot) and the code model can self-correct in a feedback loop.
5. **100% Offline** — After initial `ollama pull`, the entire pipeline runs without internet. Forever.
6. **VRAM-Aware** — Automatically adapts model selection, quantization, context budget, and features to available GPU resources.

---

## 4. Component Deep Dives

### 4.1 Ollama Interface Layer

#### 4.1.1 Direct REST API Integration

PixelPilot communicates with Ollama via its native REST API — no wrapper libraries, no abstractions:

```
OllamaClient:
  __init__(base_url="http://localhost:11434")
  
  # Core inference
  chat(model, messages, stream=True, tools=None, images=None)
  generate(model, prompt, stream=True, images=None)
  
  # Embeddings (for RAG)
  embed(model, input_texts) → List[List[float]]
  
  # Model management
  list_models() → List[ModelInfo]
  show_model(name) → ModelDetail (size, quant, ctx_len, families)
  pull_model(name, stream=True) → progress updates
  create_model(name, modelfile) → create custom Modelfile
  
  # Health
  ping() → bool
  ps() → running models & VRAM usage
```

**Why no wrapper library (like `litellm`, `langchain`, etc.)?**
- Ollama's API is simple (5 endpoints). A wrapper adds complexity for zero benefit.
- Direct HTTP calls via `httpx` give full control over streaming, timeouts, retries.
- No dependency on third-party LLM libraries that may break or lag behind Ollama updates.
- Fewer dependencies = easier install = better for open-source contributors.

#### 4.1.2 Three-Model Architecture

PixelPilot runs up to three Ollama models, each with a dedicated role:

```
┌─────────────────────────────────────────────────────┐
│                    OLLAMA SERVER                      │
│                 localhost:11434                       │
│                                                      │
│  ┌─────────────────┐  ┌──────────────────────────┐  │
│  │  CODE MODEL      │  │  VISION MODEL             │  │
│  │  qwen2.5-coder   │  │  llama3.2-vision          │  │
│  │  :14b             │  │  :11b                     │  │
│  │                   │  │                            │  │
│  │  Used for:        │  │  Used for:                 │  │
│  │  • Script gen     │  │  • Screenshot analysis     │  │
│  │  • Error fixing   │  │  • Visual verification     │  │
│  │  • Task planning  │  │  • Self-correction         │  │
│  └─────────────────┘  └──────────────────────────┘  │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │  EMBEDDING MODEL                                 │ │
│  │  nomic-embed-text (137MB)                        │ │
│  │                                                   │ │
│  │  Used for:                                        │ │
│  │  • Semantic search over GIMP PDB / Krita API     │ │
│  │  • Few-shot example retrieval                     │ │
│  │  • Matching user intent to relevant procedures    │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Model Lifecycle:**
1. On startup, PixelPilot checks which models are installed (`ollama list`)
2. If required models are missing, it prompts to download them (`ollama pull`)
3. The code model is loaded first (primary use case)
4. The vision model is loaded on-demand when a screenshot needs analysis
5. The embedding model is tiny (137MB) and stays loaded for instant RAG queries
6. Ollama automatically manages VRAM — unloading cold models when VRAM is needed

#### 4.1.3 Tool Calling with Ollama

Many Ollama models now support tool/function calling. PixelPilot uses this for structured output:

```json
// Request to Ollama with tool definitions
{
  "model": "pixelpilot-coder",
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "execute_gimp_script",
        "description": "Execute a Python-Fu script in GIMP",
        "parameters": {
          "type": "object",
          "properties": {
            "script": { "type": "string", "description": "Valid Python-Fu code" },
            "explanation": { "type": "string", "description": "What this script does" },
            "expected_result": { "type": "string", "description": "Expected visual outcome" }
          },
          "required": ["script", "explanation"]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "execute_krita_script",
        "description": "Execute a PyKrita script in Krita",
        "parameters": {
          "type": "object",
          "properties": {
            "script": { "type": "string", "description": "Valid Krita Python code" },
            "explanation": { "type": "string", "description": "What this script does" },
            "expected_result": { "type": "string", "description": "Expected visual outcome" }
          },
          "required": ["script", "explanation"]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "ask_user",
        "description": "Ask the user a clarifying question before proceeding",
        "parameters": {
          "type": "object",
          "properties": {
            "question": { "type": "string" }
          },
          "required": ["question"]
        }
      }
    }
  ]
}
```

**Fallback for models without tool calling:**
- Parse fenced ```python code blocks from raw text output
- Use regex extraction with validation
- Works with any model, just less structured

#### 4.1.4 Prompt Engineering System

**System Prompt Architecture:**
```
┌─────────────────────────────────────────────────┐
│  LAYER 1: Core Identity & Rules                  │
│  "You are PixelPilot, an AI image editing        │
│   assistant. You generate executable scripts     │
│   for GIMP/Krita..."                             │
│  (Baked into custom Modelfile — 0 runtime tokens)│
├─────────────────────────────────────────────────┤
│  LAYER 2: Editor API Reference (dynamic, via RAG)│
│  Retrieved via nomic-embed-text similarity search│
│  Contains: only the 5-10 most relevant procedures│
├─────────────────────────────────────────────────┤
│  LAYER 3: Current Canvas State                   │
│  Image dimensions, layer count, active layer,    │
│  color mode, selection status, tool state.        │
│  (Compact JSON — ~200 tokens)                    │
├─────────────────────────────────────────────────┤
│  LAYER 4: Conversation History                   │
│  Last 3–5 turns only. Older turns summarized.    │
│  (Aggressive compression for local ctx limits)   │
├─────────────────────────────────────────────────┤
│  LAYER 5: Retrieved Few-Shot Example             │
│  1–2 examples semantically matched to request.   │
│  (Quality > quantity for local models)           │
└─────────────────────────────────────────────────┘
```

> [!TIP]
> **Key difference from cloud LLM approach:** Local models have smaller context windows (8K–32K vs. 128K+). Every token injected into context must earn its place. The system prompt is baked into a Modelfile (costing 0 runtime context tokens), RAG retrieves only the most relevant API docs, and conversation history is aggressively summarized.

**API Reference Injection Strategy:**
- GIMP has ~680 PDB procedures — far too many for local model contexts. Solution:
  - **Embed all procedure docstrings** using `nomic-embed-text` → store in local ChromaDB
  - **On each user message**, embed the user's request → retrieve top-5 most relevant procedures
  - **Always inject the 10 most common procedures** as a baseline (create layer, set color, apply filter, etc.)
  - **Total injection: ~15 procedures per request** (~1500 tokens)
- Krita's API is object-oriented (Document, Node, View, etc.) → same embedding + retrieval strategy

**Prompt Optimization for Local Models:**
1. **Be explicit** — Local models need more precise instructions than GPT-4. State exactly what format to output.
2. **Avoid ambiguity** — "Generate a Python script" not "Could you maybe write some code?"
3. **One task per prompt** — Don't ask the model to plan AND code in one turn. Split into steps.
4. **Provide the exact function signature** — Don't just name the API call; show the full signature with parameter types.
5. **Use XML/JSON structured prompts** — Local models follow structured prompts more reliably than free-form instructions.

**Few-Shot Example Strategy:**
- Maintain a curated library of 50–100 high-quality script examples per editor
- Categorize by operation type
- Embed all examples using `nomic-embed-text`
- Dynamically select 1–2 most relevant examples per user query (not more — context is precious)
- Include both the natural language instruction and the correct script
- **Quality over quantity** — One perfect example teaches better than three mediocre ones for local models

#### 4.1.5 Context Window Management

| Strategy | Description |
|---|---|
| **Baked system prompt** | Core rules in Modelfile — costs 0 runtime tokens |
| **Sliding window** | Keep last 3–5 turns of conversation (not 20+) |
| **Aggressive summarization** | After 5 turns, summarize older history to ~200 tokens |
| **Canvas state snapshot** | Instead of replaying all commands, capture current state as compact JSON |
| **RAG for API docs** | Retrieve only top-5 relevant procedures per query via embedding search |
| **Image context** | For vision model: downscale screenshots to 512×384 before encoding |
| **Adaptive budget** | Detect model's ctx_len from `ollama show`; scale all budgets proportionally |

---

### 4.2 Local RAG System (Semantic API Retrieval)

Since we can't stuff all 680+ GIMP PDB procedures into a local model's 8K context, we use a **fully local RAG pipeline**:

```
┌──────────────────────────────────────────────┐
│  OFFLINE RAG PIPELINE (runs entirely local)   │
│                                               │
│  ┌─────────────────────────────────────────┐ │
│  │  1. KNOWLEDGE BASE (pre-built)          │ │
│  │     • GIMP PDB: 680 procedures          │ │
│  │     • Krita API: 200+ methods           │ │
│  │     • Few-shot examples: 100+ scripts   │ │
│  │     • Common patterns & gotchas         │ │
│  └──────────────────┬──────────────────────┘ │
│                     ↓                         │
│  ┌─────────────────────────────────────────┐ │
│  │  2. EMBEDDING (on first run / update)   │ │
│  │     Model: nomic-embed-text (137MB)     │ │
│  │     via: ollama embed                   │ │
│  │     Store: ChromaDB (local, embedded)   │ │
│  └──────────────────┬──────────────────────┘ │
│                     ↓                         │
│  ┌─────────────────────────────────────────┐ │
│  │  3. RETRIEVAL (per user query)          │ │
│  │     Embed user message → similarity     │ │
│  │     search → top-K relevant docs        │ │
│  │     Latency: <50ms (local ChromaDB)     │ │
│  └──────────────────┬──────────────────────┘ │
│                     ↓                         │
│  ┌─────────────────────────────────────────┐ │
│  │  4. INJECTION (into LLM context)        │ │
│  │     Top-5 procedures + 1-2 examples     │ │
│  │     formatted as structured reference   │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

**Why `nomic-embed-text`?**
- Supported natively by Ollama (`ollama pull nomic-embed-text`)
- Only 137MB — fits alongside any code model
- 768-dimensional embeddings — good quality, fast
- Runs on CPU, doesn't compete for GPU VRAM with inference models
- No external API needed — 100% local

---

### 4.3 Command Translation Engine

#### 4.3.1 Intermediate Representation (IR)

Before generating editor-specific code, the LLM (or a translation layer) produces an **editor-agnostic IR**:

```
Operation:
  type: "filter.blur.gaussian"
  params:
    radius: 5.0
    target: "active_layer"
  
Operation:
  type: "layer.new"
  params:
    name: "Highlights"
    blend_mode: "screen"
    opacity: 0.7

Operation:
  type: "selection.by_color"
  params:
    color: [255, 0, 0]
    threshold: 15
```

**Benefits of IR:**
- Same user intent → different backend code for GIMP vs. Krita
- Easier to validate and sandbox (no raw code to parse at the IR level)
- Enables "record and replay" across editors
- Makes testing deterministic

**When IR is bypassed:**
- Complex, multi-step workflows where the LLM needs to generate raw scripts with control flow (loops, conditionals)
- Editor-specific features with no cross-editor equivalent (e.g., GIMP's "Curves" dialog specifics vs. Krita's brush engine presets)
- In these cases, the LLM generates raw Python directly, but it still passes through the Safety Validator

#### 4.3.2 GIMP Code Generator

**Target scripting languages:**

| Language | Pros | Cons | Use When |
|---|---|---|---|
| **Python-Fu** (primary) | Modern, full Python stdlib, best LLM affinity | Requires GIMP's Python console/plugin | Default for all operations |
| **Script-Fu** (secondary) | Built-in, no extra deps, lightweight | Scheme syntax, LLMs less reliable | Simple batch operations, fallback |
| **GIMP 3.0 GObject Introspection** | Future-proof, proper Python bindings | GIMP 3.x only (newer) | Forward-looking builds |

**GIMP PDB Knowledge Base:**
- Exhaustively catalog all PDB procedures with:
  - Name, description, parameter types, return types
  - Usage examples (curated, human-verified)
  - Common pitfalls and gotchas
  - Category tags for retrieval
- Store as structured JSON, embedded via `nomic-embed-text` into ChromaDB
- Include GIMP version compatibility flags

**Common GIMP Script Patterns to teach the LLM:**
```
Category: Layer Operations
  - Create, duplicate, merge, flatten, reorder
  - Set opacity, blend mode, visibility
  - Layer groups and nesting

Category: Selections
  - By color, by path, by threshold, fuzzy select
  - Grow, shrink, feather, invert, save to channel

Category: Color & Tone
  - Curves, levels, brightness-contrast, hue-saturation
  - Color balance, threshold, posterize, desaturate

Category: Filters
  - Blur (Gaussian, motion, lens), sharpen (unsharp mask)
  - Distort, noise, edge detect, emboss
  - Light and shadow effects

Category: Drawing & Painting
  - Brush strokes along paths
  - Fill, gradient, pencil, airbrush
  - Text rendering and manipulation

Category: Transform
  - Scale, rotate, flip, perspective, cage transform
  - Align, distribute

Category: I/O
  - Open, export (PNG, JPEG, TIFF, PSD, WebP)
  - Batch processing patterns
```

#### 4.3.3 Krita Code Generator

**Target: PyKrita (Python 3)**

Krita's API is object-oriented and revolves around:
```
Krita (Application singleton)
  ├── Document
  │   ├── Node (layers, groups, masks)
  │   │   ├── PaintLayer
  │   │   ├── GroupLayer
  │   │   ├── FilterMask
  │   │   └── TransparencyMask
  │   ├── Selection
  │   └── FileLayer
  ├── View
  ├── Window
  ├── Canvas
  ├── Brush / Preset
  ├── Palette
  └── Filter (via InfoObject)
```

**Krita-Specific Capabilities to Teach:**
```
Category: Brush Engine (Krita's superpower)
  - Preset selection and modification
  - Brush tip shape, dynamics (pressure, tilt, speed)
  - Programmatic brush strokes (painting via scripting)
  - Textured brushes, custom brush tips

Category: Layer Operations
  - Paint layers, vector layers, group layers
  - Filter layers (non-destructive)
  - Transform masks, transparency masks
  - Clone layers, file layers

Category: Painting & Drawing
  - Freehand, line, rectangle, ellipse, polygon
  - Fill tool, gradient tool
  - Bezier curves, calligraphy tool

Category: Color Management
  - Color spaces (RGB, CMYK, LAB, Grayscale)
  - ICC profiles
  - Gamut warnings

Category: Animation
  - Frame-by-frame animation
  - Onion skinning
  - Timeline manipulation
  - Export to video/GIF

Category: Filters & Effects
  - Blur, sharpen, edge detection
  - Color adjustment (levels, curves, HSV)
  - Artistic filters (oil paint, pixelize)
  - G'MIC integration
```

#### 4.3.4 Safety Validator & Sandboxer

> [!CAUTION]
> **LLM-generated code is untrusted by default.** Local models hallucinate more than large cloud models — the Safety Validator is even more critical here.

**Static Analysis (before execution):**
1. **AST Parsing** — Parse generated Python into an AST. Reject if parsing fails.
2. **Allowlist enforcement:**
   - Only allow imports from: `gimp`, `gimpfu`, `krita`, `math`, `random`, `colorsys`, `json`, `re`, `struct` (curated safe list)
   - Block: `os`, `sys`, `subprocess`, `socket`, `http`, `urllib`, `pathlib.write`, `shutil`, `eval`, `exec`, `compile`, `__import__`
3. **Filesystem access control:**
   - Allow reads only from user-specified input directories
   - Allow writes only to user-specified output directories
   - Block all other filesystem access
4. **Resource limits:**
   - Max script length (e.g., 500 lines)
   - Max execution time (configurable timeout, default 60s)
   - Max memory allocation (if enforceable)

**Runtime Sandboxing:**
- Execute scripts in a restricted Python environment
- Use GIMP's/Krita's own scripting sandbox where available
- Optionally: run in a container/VM for maximum isolation (advanced mode)

**User Confirmation Modes:**
| Mode | Behavior |
|---|---|
| `auto` | Execute immediately. Appropriate since everything is local and sandboxed. |
| `preview` | Show script to user, execute on approval. **(default)** |
| `strict` | Show script + safety analysis report, require explicit confirmation. |
| `dry-run` | Generate script but never execute; user copies manually. |

> [!TIP]
> Since everything is local, `auto` mode is more reasonable than with cloud LLMs — there's no data exfiltration risk to external servers. The main risks are filesystem damage (sandboxed) and bad edits (undo groups protect against this).

---

### 4.4 Editor Bridge Layer

#### 4.4.1 GIMP Bridge

**Communication Methods (in order of preference):**

1. **PixelPilot GIMP Plugin (custom — recommended)**
   - A lightweight GIMP plugin that:
     - Opens a local socket/named pipe
     - Listens for commands from PixelPilot
     - Executes them in GIMP's Python environment
     - Returns results, errors, and screenshots
   - Installed as a standard GIMP plugin
   - **This is the recommended approach for best UX**

2. **GIMP 3.x: GObject Introspection + D-Bus**
   - GIMP 3.0+ exposes a proper D-Bus interface
   - Send Python commands over D-Bus for real-time execution
   - Can query canvas state, layer info, etc.
   - Best for interactive, real-time workflows

3. **GIMP 2.x/3.x: Python-Fu Console Socket**
   - GIMP's Python-Fu console can be accessed via a TCP socket
   - Enable via: `Filters → Python-Fu → Console` (or command-line flag)
   - Send Python statements; receive results
   - Good for interactive sessions

4. **GIMP Batch Mode**
   - `gimp -i -b '(python-fu-eval 0 "...")'`
   - or `gimp -i --batch-interpreter python-fu-eval -b 'script.py'`
   - Best for non-interactive, headless processing
   - No real-time feedback during execution

#### 4.4.2 Krita Bridge

**Communication Methods (in order of preference):**

1. **PyKrita Plugin (primary)**
   - A Krita plugin (Python) that:
     - Registers a dock widget (UI panel inside Krita)
     - Opens a local TCP/Unix socket for IPC
     - Receives commands from PixelPilot core
     - Executes via Krita's Python API
     - Returns results and canvas snapshots
   - Most integrated experience
   - Access to full Krita API including brush engine

2. **Krita `--script` flag**
   - `krita --script script.py`
   - Runs a Python script at startup
   - Good for batch processing
   - Limited interactivity

3. **Krita's built-in Scripter plugin**
   - Manual execution of scripts via `Tools → Scripts → Scripter`
   - Not suitable for automation, but useful for testing

#### 4.4.3 Unified Bridge Interface

Both bridges implement a common interface:

```
EditorBridge (abstract):
  connect()                    → Establish connection to editor
  disconnect()                 → Clean up
  is_connected() → bool        → Check connection status
  
  execute_script(code: str)    → Execute raw script, return result
  get_canvas_state()           → Return structured canvas info
  capture_screenshot()         → Return current canvas as image bytes
  
  get_image_info()             → Dimensions, color mode, DPI, etc.
  get_layers()                 → List of layers with properties
  get_active_layer()           → Current active layer info
  get_selection()              → Selection bounds and mask
  get_history()                → Undo history (if available)
  
  undo()                       → Undo last operation
  redo()                       → Redo
```

---

### 4.5 Feedback & Observation Layer

This layer is what makes PixelPilot **intelligent** rather than just a script generator.

#### 4.5.1 Visual Feedback Loop (with Ollama Vision)

```
User: "Make the sky more dramatic"
  ↓
Code model generates script (curves adjustment, contrast boost on sky selection)
  ↓
Script executes in GIMP/Krita
  ↓
Screenshot captured automatically → downscaled to 512×384
  ↓
Screenshot sent to Ollama vision model (llama3.2-vision):
  "I applied a curves adjustment and contrast boost to the sky region.
   Here is the result. Does it look like a 'dramatic sky'?
   If not, what specific adjustments should I make?
   Respond with a JSON: {\"success\": true/false, \"assessment\": \"...\", \"fixes\": [...]}"
  ↓
Vision model evaluates and returns assessment
  ↓
If not successful:
  → Assessment fed to code model: "The vision model says: [assessment]. Generate a corrective script."
  → Code model generates fix
  → Retry (max 3 iterations)
```

**Vision model VRAM management:**
- After analysis, the vision model can be unloaded from VRAM (`ollama stop <model>`)
- This frees VRAM for the code model
- Adds ~5s latency to load the vision model each time, but saves VRAM on constrained systems
- Configurable: `keep_vision_loaded: true` for systems with enough VRAM

#### 4.5.2 Text-Only Fallback (No Vision Model)

For systems without enough VRAM for a vision model:

```
Script executes in GIMP/Krita
  ↓
Canvas state queried programmatically:
  - Layer histogram (color distribution)
  - Pixel sampling at key regions (corners, center, thirds)
  - Selection bounds and coverage percentage
  - Layer opacity/blend mode changes
  ↓
State description constructed as text:
  "After applying curves: Average brightness increased from 128 to 156.
   Red channel boosted in highlights (+23). Contrast ratio changed from
   1.8:1 to 2.4:1. Sky region (top 40% of image) now shows dominant
   warm tones (orange-yellow). Shadow detail preserved."
  ↓
Text description sent to code model for evaluation
```

#### 4.5.3 Error Recovery

```
Script execution fails
  ↓
Error message captured (traceback, GIMP/Krita error)
  ↓
Error + original script sent back to code model:
  "The following script failed with this error: [error].
   The canvas state is: [state].
   Please fix the script. Output ONLY the corrected code."
  ↓
Code model generates corrected script
  ↓
Retry (max 3 attempts, then ask user)
```

> [!NOTE]
> Local models are more likely to hallucinate API calls than cloud models. The error recovery loop is therefore more important. The safety validator's API-call checking (against the PDB/API catalog) catches many hallucinations before execution.

#### 4.5.4 Canvas State Tracking

Maintain a **structured representation** of the canvas state that persists across turns:

```
CanvasState:
  image_path: "photo.jpg"
  dimensions: [1920, 1080]
  color_mode: "RGB"
  bit_depth: 8
  dpi: 300
  layers:
    - name: "Background"
      type: "raster"
      visible: true
      opacity: 100
      blend_mode: "normal"
      locked: false
    - name: "Retouching"
      type: "raster"
      visible: true
      opacity: 85
      blend_mode: "normal"
  active_layer: "Retouching"
  has_selection: false
  selection_bounds: null
  undo_depth: 12
```

This state is injected into the LLM context so it always knows what it's working with.

---

### 4.6 User Interface Layer

#### 4.6.1 Phase 1: CLI / REPL (MVP)

```
$ pixelpilot --editor gimp

PixelPilot v0.1.0
  Ollama:  localhost:11434 ✓
  Code:    qwen2.5-coder:14b (Q4_K_M, 8K ctx) ✓
  Vision:  llama3.2-vision:11b ✓
  RAG:     nomic-embed-text (680 GIMP procs indexed) ✓
  Editor:  GIMP 3.0 (plugin bridge) ✓
  Canvas:  photo.jpg (1920×1080, RGB, 3 layers)

You: make the background layer black and white but keep the subject in color

PixelPilot: I'll create a selective desaturation effect:
  1. Duplicate the background layer
  2. Desaturate the duplicate (luminosity method)
  3. Add a layer mask to the desaturated layer
  4. Paint white on the mask over the subject to reveal the color beneath

[Script Preview — 23 lines, Python-Fu]
  ... (code shown) ...

[Safety: ✓ passed | Imports: gimp, gimpfu | No filesystem access]

Execute? [Y/n/edit]: y

Executing... Done. (4 operations, 1.2s)
Analyzing result... The desaturation was applied successfully. ✓

You: the mask needs to be more precise around the hair

PixelPilot: I'll refine the mask edge using feathering and
a smaller brush. Adjusting...
```

#### 4.6.2 Phase 2: Web UI

- Chat-style interface with image preview (runs on localhost)
- Side-by-side: chat panel + canvas preview
- Script editor with syntax highlighting (for power users who want to edit before execution)
- Layer panel showing current canvas state
- History timeline with thumbnails
- Model status indicator (which model is loaded, VRAM usage)
- Settings: model selection from installed Ollama models, editor selection, safety mode

#### 4.6.3 Phase 3: Native Editor Plugins

**GIMP Dock Panel:**
- A dockable dialog inside GIMP
- Chat input at the bottom
- Response/script display area
- "Execute" / "Undo" buttons
- Ollama model status indicator
- Settings gear icon

**Krita Docker:**
- A docker panel inside Krita
- Same chat interface
- Integrated with Krita's UI paradigm
- Access to brush presets for painting commands
- Ollama connection status

---

## 5. Key Workflows & Use Cases

### 5.1 Photo Editing Workflows (GIMP-primary)

| Workflow | Example Prompt | Generated Operations |
|---|---|---|
| **Background Removal** | "Remove the background and make it transparent" | Select subject (by color/foreground select) → invert selection → delete → flatten alpha |
| **Color Grading** | "Give this a warm, golden hour look" | Curves (boost reds/yellows in highlights) → color balance (warm shadows) → slight vignette |
| **Retouching** | "Remove the blemishes on the face" | Clone stamp / healing tool operations on detected regions |
| **Compositing** | "Put this person on a beach background" | Open both images → scale subject → extract (mask) → paste as new layer → match lighting/color |
| **Batch Processing** | "Resize all images in this folder to 800×600 and add a watermark" | Script with glob → open → scale → add text layer → flatten → export |
| **HDR / Tone Mapping** | "Bring out the details in the shadows without blowing highlights" | Curves → shadow/highlight recovery → local contrast enhancement |

### 5.2 Digital Art Workflows (Krita-primary)

| Workflow | Example Prompt | Generated Operations |
|---|---|---|
| **Concept Sketching** | "Draw a rough sketch of a medieval castle on a hill" | Create canvas → select pencil brush → draw shapes via stroke paths |
| **Character Design** | "Create a base figure with gesture lines for a running pose" | Line tool / bezier strokes for gesture → body mass shapes |
| **Environment Painting** | "Paint a sunset sky gradient from warm orange to deep purple" | Gradient tool → add cloud texture layer → brush in details |
| **Inking** | "Ink over the sketch layer with clean, variable-width lines" | New layer → select ink brush preset → trace paths with pressure sim |
| **Coloring** | "Flat color the character — skin tone, blue shirt, brown pants" | Flood fill by regions → new layers per color group |
| **Effects** | "Add a glow effect around the magic orb" | Duplicate orb → Gaussian blur → set to Screen blend mode → adjust opacity |

### 5.3 Cross-Editor Workflows

| Workflow | Description |
|---|---|
| **Photo → Art** | Load photo in GIMP → extract/manipulate → export → open in Krita → paint over / stylize |
| **Art → Composite** | Create elements in Krita → export layers → composite in GIMP with photo elements |
| **Batch Art Generation** | LLM generates a series of Krita scripts to create variations of a design |

---

## 6. Multi-Step Task Planning

For complex requests, the code model should **plan before executing**:

```
User: "Create a movie poster with the person from photo.jpg, 
       a dark cityscape background, dramatic lighting, 
       and bold title text 'SHADOWS'"

PixelPilot (code model plans):
  Step 1: Open photo.jpg and extract the person (foreground selection)
  Step 2: Create a new canvas (24"×36" at 300 DPI)
  Step 3: Generate/place a dark cityscape background
  Step 4: Place the extracted person, scale and position
  Step 5: Apply dramatic lighting (dodge/burn, color grading)
  Step 6: Add title text "SHADOWS" with cinematic typography
  Step 7: Add final effects (vignette, grain, color tone)

Shall I proceed with this plan? [Y/n/modify]
```

Each step generates and executes a separate script, with visual feedback between steps. This is critical for local models because:
- Smaller context windows can't hold a massive multi-step script
- Breaking into steps allows error recovery at each step
- The vision model can verify each step before proceeding
- The user can intervene and redirect at any point

---

## 7. Data Architecture

### 7.1 Project Structure

```
pixelpilot/
├── pyproject.toml                 # Package config, dependencies
├── README.md
├── LICENSE                        # Open-source license (MIT/Apache-2.0)
│
├── modelfiles/                    # Custom Ollama Modelfiles
│   ├── Modelfile.pixelpilot-coder
│   ├── Modelfile.pixelpilot-vision
│   └── setup_models.sh           # Script to create custom models
│
├── src/
│   └── pixelpilot/
│       ├── __init__.py
│       ├── main.py                # Entry point, CLI
│       ├── config.py              # Configuration management
│       │
│       ├── ollama/                # Ollama Interface (direct REST)
│       │   ├── __init__.py
│       │   ├── client.py          # HTTP client for Ollama REST API
│       │   ├── models.py          # Model management, auto-selection
│       │   ├── streaming.py       # Streaming response handler
│       │   └── modelfiles.py      # Modelfile creation & management
│       │
│       ├── prompts/               # Prompt Engineering
│       │   ├── __init__.py
│       │   ├── system.py          # System prompt builder
│       │   ├── gimp.py            # GIMP-specific prompt components
│       │   ├── krita.py           # Krita-specific prompt components
│       │   ├── context.py         # Context window budget manager
│       │   └── templates/         # Jinja2/string templates
│       │
│       ├── rag/                   # Local RAG System
│       │   ├── __init__.py
│       │   ├── indexer.py         # Embed & index API docs + examples
│       │   ├── retriever.py       # Semantic search over ChromaDB
│       │   └── store.py           # ChromaDB wrapper
│       │
│       ├── codegen/               # Command Translation Engine
│       │   ├── __init__.py
│       │   ├── ir.py              # Intermediate representation
│       │   ├── gimp_codegen.py    # GIMP script generator
│       │   ├── krita_codegen.py   # Krita script generator
│       │   ├── validator.py       # Safety validator (AST analysis)
│       │   └── sandbox.py         # Execution sandboxing
│       │
│       ├── bridge/                # Editor Bridge Layer
│       │   ├── __init__.py
│       │   ├── base.py            # Abstract bridge
│       │   ├── gimp_bridge.py     # GIMP communication
│       │   ├── krita_bridge.py    # Krita communication
│       │   └── state.py           # Canvas state tracking
│       │
│       ├── feedback/              # Feedback & Observation
│       │   ├── __init__.py
│       │   ├── screenshot.py      # Canvas capture & downscaling
│       │   ├── vision.py          # Ollama vision model analysis
│       │   ├── text_fallback.py   # Text-only canvas analysis
│       │   └── error_recovery.py  # Error handling & retry
│       │
│       ├── knowledge/             # API Knowledge Base
│       │   ├── __init__.py
│       │   ├── gimp_pdb.json      # GIMP PDB catalog (680 procedures)
│       │   ├── krita_api.json     # Krita API catalog (200+ methods)
│       │   └── examples/          # Few-shot examples
│       │       ├── gimp/          # 50+ GIMP script examples
│       │       └── krita/         # 50+ Krita script examples
│       │
│       └── ui/                    # User Interfaces
│           ├── cli.py             # CLI / REPL
│           └── web/               # Web UI (Phase 2, localhost only)
│
├── plugins/                       # Editor plugins
│   ├── gimp/
│   │   └── pixelpilot_gimp/      # GIMP plugin
│   │       ├── __init__.py
│   │       └── plugin.py
│   └── krita/
│       └── pixelpilot_krita/     # Krita plugin
│           ├── __init__.py
│           ├── plugin.py
│           └── pixelpilot.desktop # Krita plugin descriptor
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/                  # Test images, expected outputs
│
├── docs/
│   ├── architecture.md
│   ├── user-guide.md
│   ├── hardware-guide.md          # GPU/VRAM requirements & recommendations
│   ├── model-guide.md             # Which Ollama models to use & why
│   ├── developer-guide.md
│   └── prompt-engineering.md
│
└── examples/                      # Example workflows
    ├── photo_editing/
    ├── digital_art/
    └── batch_processing/
```

### 7.2 Configuration Schema

```yaml
# ~/.config/pixelpilot/config.yaml

ollama:
  base_url: "http://localhost:11434"   # Ollama API endpoint
  code_model: "pixelpilot-coder"       # Custom Modelfile (or any installed model)
  vision_model: "pixelpilot-vision"    # Custom Modelfile (or any installed model)
  embed_model: "nomic-embed-text"      # For RAG embeddings
  
  # Inference parameters (overrides Modelfile if set)
  temperature: 0.2                     # Low temp for code generation
  num_predict: 4096                    # Max output tokens
  num_ctx: 8192                        # Context window size
  
  # VRAM management
  keep_vision_loaded: false            # Unload vision model after analysis to save VRAM
  auto_select_models: true             # Auto-pick best models for available VRAM
  
  # Streaming
  stream: true                         # Stream responses for real-time feedback

editor:
  default: "gimp"                      # gimp | krita
  gimp:
    binary_path: null                  # Auto-detected if on PATH
    connection: "plugin"               # plugin | dbus | socket | batch
    host: "localhost"
    port: 10010
  krita:
    binary_path: null                  # Auto-detected if on PATH
    connection: "plugin"               # plugin | script | batch
    host: "localhost"
    port: 10020

safety:
  mode: "preview"                      # auto | preview | strict | dry-run
  max_script_lines: 500
  max_execution_time: 60               # seconds
  allowed_read_dirs:
    - "~/Pictures"
    - "~/Documents/Projects"
  allowed_write_dirs:
    - "~/Pictures/PixelPilot_Output"

feedback:
  auto_screenshot: true                # Capture after each command batch
  auto_correct: false                  # Vision model triggers auto-correction
  max_retries: 3                       # Max error recovery attempts
  screenshot_resolution: [512, 384]    # Downscale for vision model efficiency
  vision_enabled: true                 # Set false if no VRAM for vision model

rag:
  db_path: "~/.config/pixelpilot/chromadb"   # Local ChromaDB storage
  top_k_procedures: 5                         # Retrieve top-K API procedures
  top_k_examples: 2                           # Retrieve top-K few-shot examples
  rebuild_on_update: true                      # Re-index when knowledge base changes

session:
  history_file: "~/.config/pixelpilot/history.json"
  max_history_turns: 5                 # Aggressive for local context limits
  summarize_after: 5                   # Summarize history after N turns
  auto_save_scripts: true
  script_output_dir: "~/.config/pixelpilot/scripts"
```

---

## 8. GIMP API Knowledge Base — Critical Details

### 8.1 GIMP Version Strategy

| Version | Status | Script Approach | Notes |
|---|---|---|---|
| **GIMP 2.10.x** | Legacy stable (widely used) | Python-Fu (Python 2.7!), Script-Fu | Python 2 is EOL but GIMP 2.x ships with it |
| **GIMP 3.0.x** | New stable (released 2025) | Python 3 via GObject Introspection | Modern, recommended target |

> [!IMPORTANT]
> **Target GIMP 3.0+ as primary**, with GIMP 2.10 compatibility as a secondary goal. The codegen should detect the GIMP version and generate appropriate code.

### 8.2 Key GIMP PDB Categories to Catalog

```
gimp-image-*         → Image operations (create, flatten, merge, resize, crop, rotate)
gimp-layer-*         → Layer operations (new, copy, scale, resize, offset, set-*)
gimp-drawable-*      → Drawable operations (common to layers, channels, masks)
gimp-edit-*          → Clipboard operations (copy, cut, paste, fill, stroke)
gimp-selection-*     → Selection operations (all, none, invert, by-color, float)
gimp-colors-*        → Color adjustments (curves, levels, brightness-contrast, hue-sat)
gimp-item-*          → Item properties (name, visible, linked, position)
gimp-display-*       → Display/view operations
gimp-context-*       → Tool context (set foreground/background color, brush, opacity)
gimp-brush-*         → Brush operations
gimp-gradient-*      → Gradient operations
gimp-palette-*       → Palette operations
gimp-text-*          → Text operations
gimp-vectors-*       → Path/vector operations
plug-in-*            → Filter plugins (blur, sharpen, distort, etc.)
python-fu-*          → Python-Fu specific
file-*               → File I/O (load, save, export various formats)
```

### 8.3 GIMP Gotchas to Encode in Prompts

1. **Display refresh**: After operations, call `gimp.displays_flush()` or the image won't update
2. **Floating selections**: After paste, you get a floating selection — must anchor or create new layer
3. **Color mode**: Many filters only work in RGB mode — check and convert if needed
4. **Layer boundaries**: Layer dimensions ≠ canvas dimensions. Use `gimp-layer-resize-to-image-size` to match
5. **Selection state**: Many operations only affect the selected region. Always be intentional about selection
6. **Undo groups**: Wrap multi-step operations in `gimp.image.undo_group_start()` / `undo_group_end()`
7. **GIMP 3 API changes**: Many function signatures changed from GIMP 2.x to 3.x

---

## 9. Krita API Knowledge Base — Critical Details

### 9.1 Krita Scripting Model

Krita uses a **document-centric object model**:

```
Krita.instance()                    → Application singleton
  .activeDocument()                 → Current Document
    .rootNode()                     → Root layer group
      .childNodes()                 → [Node, Node, ...]
        .type()                     → "paintlayer", "grouplayer", etc.
        .setPixelData(bytes, x, y, w, h)  → Raw pixel manipulation
    .width(), .height()             → Dimensions
    .resolution()                   → DPI
    .colorModel(), .colorDepth()    → Color info
    .selection()                    → Current Selection object
    .setSelection(Selection)        → Set selection
    .refreshProjection()            → Update display
    .exportImage(path, InfoObject)  → Export to file
  .activeWindow()                   → Current Window
    .activeView()                   → Current View
  .filters()                        → Available filter list
  .resources("preset")              → Available brush presets
```

### 9.2 Krita Gotchas to Encode in Prompts

1. **refreshProjection()**: Must call after pixel operations or changes won't display
2. **Pixel data format**: `setPixelData()` expects raw bytes in the document's color space — order matters (BGRA for 8-bit RGBA)
3. **Byte order**: Krita uses BGRA, not RGBA — a common source of color channel bugs
4. **Batch mode limitations**: Some GUI-dependent operations don't work in batch/headless mode
5. **Document must exist**: Can't manipulate without an active document — create one first
6. **Thread safety**: Krita's API is not fully thread-safe — execute from main thread
7. **Filter application**: Filters need `InfoObject` for parameters and must be applied to a specific node

---

## 10. Security & Safety

### 10.1 Threat Model

| Threat | Risk | Local-Specific Notes | Mitigation |
|---|---|---|---|
| **LLM generates malicious code** | High | Local models hallucinate more; higher chance of accidental harmful code | AST validation, import allowlisting, filesystem restrictions |
| **LLM hallucinating API calls** | High | **More common with local models** than cloud — smaller models invent plausible but wrong function names | Validate every API call against PDB/Krita catalog before execution |
| **Denial of service (infinite loop)** | Medium | Could freeze the editor and waste GPU time | Execution timeout, resource limits |
| **Overwriting important files** | High | Local execution = real filesystem access | Write-only to designated output directories |
| **Prompt injection via image metadata** | Low | No external server to exfiltrate to, but could cause unwanted edits | Strip EXIF/metadata before sending to LLM; sanitize inputs |
| **Data exfiltration** | Very Low | Everything is local — no network calls by design | Block all network imports as defense-in-depth |

### 10.2 Security Layers

```
Layer 1: LLM Output Parsing
  → Extract code from response (tool call JSON or fenced block)
  → Reject if no valid code block found

Layer 2: Static Analysis (AST)
  → Parse to AST; reject syntax errors
  → Walk AST for forbidden patterns:
    - Forbidden imports
    - Forbidden builtins (eval, exec, compile, __import__)
    - Filesystem writes outside allowed dirs
    - Network operations
    - Shell execution

Layer 3: API Validation (critical for local models)
  → Check ALL GIMP/Krita API calls against known-good catalog
  → Warn on unknown procedures (likely hallucination)
  → Suggest closest valid procedure name if hallucination detected

Layer 4: User Confirmation
  → Show generated script + safety analysis
  → User approves or rejects

Layer 5: Runtime Sandbox
  → Restricted globals/builtins in exec() environment
  → Timeout enforcement
  → Resource monitoring

Layer 6: Undo Safety Net
  → Wrap all operations in undo groups
  → User can always undo with a single action
```

---

## 11. Development Phases

### Phase 0: Research & Prototyping (Weeks 1–3)

| Task | Description | Deliverable |
|---|---|---|
| Ollama model benchmarking | Test qwen2.5-coder (7b/14b/32b), codestral, deepseek-coder generating GIMP/Krita scripts. Measure accuracy, speed, hallucination rate. | Model comparison report, recommended defaults |
| GIMP scripting deep-dive | Test all communication methods (D-Bus, socket, batch, plugin) with GIMP 3.0 | Working GIMP IPC prototype |
| Krita scripting deep-dive | Test PyKrita plugin development, socket IPC, batch mode | Working Krita IPC prototype |
| PDB/API cataloging | Extract and structure all GIMP PDB + Krita API docs | JSON knowledge base files |
| RAG prototype | Index API docs with nomic-embed-text + ChromaDB, test retrieval quality | Working RAG pipeline |
| Prompt engineering R&D | Develop and test system prompts, few-shot examples, Modelfiles | Prompt template library + Modelfiles |
| Vision model testing | Test llama3.2-vision / llava analyzing editor screenshots | Vision feedback prototype |

### Phase 1: Core MVP — CLI + GIMP + Ollama (Weeks 4–8)

| Task | Description | Priority |
|---|---|---|
| Ollama client | Direct REST API client (httpx), streaming, model management | P0 |
| Auto model selection | Detect VRAM, select best code/vision models from installed | P0 |
| Custom Modelfiles | Build and install pixelpilot-coder, pixelpilot-vision | P0 |
| Local RAG system | ChromaDB + nomic-embed-text for API doc retrieval | P0 |
| Prompt system | System prompt builder with dynamic API injection, context budgeting | P0 |
| GIMP bridge | Plugin-based IPC with GIMP | P0 |
| Safety validator | AST-based static analysis + API hallucination detection | P0 |
| CLI / REPL interface | Interactive command-line chat with Rich UI | P0 |
| Canvas state tracking | Query and maintain canvas state | P1 |
| Error recovery | Retry logic with error context fed back to model | P1 |
| Configuration system | YAML config, CLI args | P1 |

**MVP milestone**: User can chat with CLI → Ollama generates Python-Fu → validated → executes in GIMP → user sees result. All local.

### Phase 2: Krita Support + Vision Feedback (Weeks 9–13)

| Task | Description | Priority |
|---|---|---|
| Krita bridge | PyKrita plugin-based IPC | P0 |
| Krita codegen | Krita-specific prompt templates and few-shot examples | P0 |
| Vision feedback loop | Screenshot → llama3.2-vision analysis → code model correction | P0 |
| Text-only fallback | Histogram/pixel-sampling feedback for no-VRAM-for-vision systems | P0 |
| VRAM management | Smart model loading/unloading, keep_alive settings | P1 |
| Multi-step task planning | Plan → execute → verify → next step (one step per inference) | P1 |
| Few-shot example library | 50+ curated examples per editor, embedded for RAG | P1 |
| Cross-editor workflows | Chain GIMP and Krita in single workflow | P2 |

### Phase 3: Web UI + Polish (Weeks 14–18)

| Task | Description | Priority |
|---|---|---|
| Web UI | Localhost chat interface with canvas preview | P0 |
| Script editor | Syntax-highlighted code preview/edit before execution | P1 |
| History & project management | Save/load sessions, undo timelines | P1 |
| Batch processing mode | Process multiple images with single instruction | P1 |
| Model management UI | Pull, switch, delete models from web UI | P1 |
| Plugin UIs | Dock panels inside GIMP and Krita | P2 |
| User documentation | Guides, tutorials, hardware guide, model guide | P0 |

### Phase 4: Advanced Features (Weeks 19+)

| Task | Description | Priority |
|---|---|---|
| Macro recording | Record user actions in GIMP/Krita → teach LLM new patterns | P1 |
| Custom tool definitions | Users define new "tools" via natural language | P2 |
| Community script sharing | Share and import community-created workflows | P2 |
| Animation support | Krita animation scripting via Ollama | P2 |
| Style transfer workflows | Complex multi-step artistic transformations | P2 |
| Fine-tuning pipeline | Fine-tune a small model on curated GIMP/Krita script pairs (LoRA/QLoRA) | P2 |
| Model quantization guide | Help users quantize custom models for their hardware | P2 |

---

## 12. Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| **Language** | Python 3.11+ | GIMP 3.x and Krita both use Python; keeps everything in one language |
| **Package Manager** | `uv` (preferred) or `pip` | Fast, modern Python packaging |
| **LLM Runtime** | Ollama (sole backend) | Local-only, simple API, handles GPU offload, model management |
| **HTTP Client** | `httpx` | Async support, streaming, lightweight (no heavy LLM wrapper libs) |
| **Vector Store** | `chromadb` (embedded, local) | No server needed, SQLite-backed, Python-native |
| **Embeddings** | `nomic-embed-text` via Ollama | Fully local, 137MB, runs on CPU, great quality |
| **CLI Framework** | `rich` + `prompt_toolkit` | Beautiful terminal UI with autocomplete, syntax highlighting |
| **Web UI** | FastAPI + WebSocket + htmx (or Svelte) | Lightweight localhost-only web interface |
| **Config** | `pydantic-settings` | Typed configuration with validation |
| **Testing** | `pytest` + `pytest-asyncio` | Async test support for IPC and streaming |
| **Image Processing** | `Pillow` | Screenshot handling, downscaling for vision model |
| **IPC** | `asyncio` + TCP sockets / named pipes | Editor communication |
| **AST Analysis** | Python `ast` module (stdlib) | Script safety validation — zero dependencies |
| **Documentation** | MkDocs + Material theme | Beautiful docs site |
| **GPU Detection** | `nvidia-smi` parsing / `pynvml` | For auto model selection based on available VRAM |

> [!NOTE]
> **Deliberately excluded:** `litellm`, `langchain`, `llama-index`, `openai` SDK. These add complexity and dependencies for cloud providers we don't use. Direct `httpx` calls to Ollama's REST API are simpler, faster, and more maintainable.

---

## 13. Testing Strategy

### 13.1 Unit Tests
- Ollama client (mock HTTP responses, test streaming, error handling)
- Prompt builder (template rendering, context injection, budget enforcement)
- Safety validator (test against known-good and known-bad scripts)
- API hallucination detector (test against PDB/Krita catalog)
- IR generation and translation
- Canvas state parsing
- RAG retrieval quality (does "blur the background" retrieve gaussian blur procedures?)

### 13.2 Integration Tests
- Ollama → script generation → validation pipeline (requires running Ollama with a small model like phi3:3.8b)
- GIMP bridge communication (requires GIMP running)
- Krita bridge communication (requires Krita running)
- RAG indexing → retrieval → injection pipeline
- Screenshot capture → vision model analysis loop
- Full pipeline: user prompt → Ollama → script → GIMP → screenshot → vision feedback

### 13.3 Golden Tests
- Curated set of 50 natural-language prompts → expected script outputs
- Run against multiple Ollama model sizes (7b, 14b, 32b) to measure quality degradation
- Visual regression tests: compare output images against golden references
- Track success rate per model per task category

### 13.4 Security Tests
- Fuzz the safety validator with adversarial scripts
- Test with prompts designed to make the model inject harmful code
- Verify filesystem sandboxing
- Test API hallucination detection with intentionally wrong function names

### 13.5 Performance Benchmarks
- Time-to-first-token per model size
- Total script generation time per task complexity
- Vision model analysis latency
- Model swap time (unload code model → load vision model → unload → reload code model)
- End-to-end latency: user prompt → visible result in editor

---

## 14. First-Run Setup Experience

The installer should make the first-run experience as smooth as possible:

```
$ pip install pixelpilot    # or: uv pip install pixelpilot

$ pixelpilot setup

╔══════════════════════════════════════════════════════╗
║  PixelPilot Setup Wizard                              ║
╠══════════════════════════════════════════════════════╣
║                                                       ║
║  Step 1: Checking Ollama installation...              ║
║    ✓ Ollama v0.5.x found at /usr/local/bin/ollama    ║
║    ✓ Ollama server running on localhost:11434         ║
║                                                       ║
║  Step 2: Detecting GPU...                             ║
║    ✓ NVIDIA RTX 4070 Ti — 12GB VRAM                  ║
║    → Tier 3 (Strong): Recommended models below       ║
║                                                       ║
║  Step 3: Pulling recommended models...                ║
║    ⬇ qwen2.5-coder:14b        (8.9GB)  [████░░] 67% ║
║    ⬇ llama3.2-vision:11b      (6.8GB)  [queued]      ║
║    ⬇ nomic-embed-text          (274MB)  [queued]      ║
║                                                       ║
║  Step 4: Creating custom Modelfiles...                ║
║    → pixelpilot-coder (optimized for script gen)     ║
║    → pixelpilot-vision (optimized for image analysis) ║
║                                                       ║
║  Step 5: Building RAG index...                        ║
║    ✓ Indexed 680 GIMP PDB procedures                 ║
║    ✓ Indexed 237 Krita API methods                   ║
║    ✓ Indexed 104 few-shot examples                   ║
║                                                       ║
║  Step 6: Detecting editors...                         ║
║    ✓ GIMP 3.0.2 found                               ║
║    ✓ Krita 5.2.6 found                              ║
║    → Installing PixelPilot GIMP plugin...  ✓         ║
║    → Installing PixelPilot Krita docker... ✓         ║
║                                                       ║
║  ✅ Setup complete! Run: pixelpilot                   ║
╚══════════════════════════════════════════════════════╝
```

---

## 15. Open Questions & Design Decisions

> [!IMPORTANT]
> **Q1: GIMP Version Priority**
> Should we target GIMP 2.10 (widespread, Python 2 scripting) or GIMP 3.0+ only (modern, Python 3)? Supporting both doubles the codegen work. **Recommendation**: GIMP 3.0+ only, since 2.10 uses EOL Python 2.

> [!IMPORTANT]
> **Q2: Minimum Model Size**
> Should the minimum supported model be 7B (runs on most hardware, but produces weaker scripts) or 14B (better quality, needs 8GB VRAM)? **Recommendation**: Support 7B as minimum, but clearly document that 14B+ is recommended for reliable results.

> [!IMPORTANT]
> **Q3: IR Layer — Worth the Complexity?**
> The intermediate representation adds an abstraction layer but enables cross-editor portability. Should we build it from Day 1, or start with direct LLM → editor-specific code and add IR later? **Recommendation**: Start with direct codegen (Phase 1–2), introduce IR in Phase 3 when cross-editor patterns are better understood.

> [!NOTE]
> **Q4: Licensing**
> GIMP is GPL-licensed; Krita is GPL-licensed. PixelPilot itself should be permissively licensed (MIT or Apache-2.0) since it communicates with editors via IPC, not linking. Confirm legal compatibility.

> [!NOTE]
> **Q5: Fine-Tuning Pathway**
> Should we plan for a PixelPilot-specific fine-tuned model (LoRA on qwen2.5-coder trained on GIMP/Krita script pairs)? This would dramatically improve script quality for small models. **Recommendation**: Yes, add to Phase 4. Collect successful script executions as training data from Phase 1 onward.

> [!NOTE]
> **Q6: Ollama Remote Support**
> Should we support connecting to Ollama running on a different machine (e.g., a powerful GPU server on the LAN)? The architecture supports it (just change `base_url`), but it technically breaks the "everything local" principle. **Recommendation**: Support it via config, but don't advertise it as a primary use case.

---

## 16. Success Criteria

### MVP (Phase 1)
- [ ] User can describe an image editing task in natural language
- [ ] Ollama code model generates a valid, executable GIMP Python-Fu script
- [ ] Script is validated for safety (AST + API hallucination check) and presented to user
- [ ] Script executes in GIMP and produces the expected visual result
- [ ] Works with qwen2.5-coder at 7b and 14b sizes
- [ ] RAG retrieves relevant API procedures for each query
- [ ] 70%+ success rate on a curated benchmark of 50 common editing tasks (14b model)
- [ ] 50%+ success rate on same benchmark with 7b model
- [ ] End-to-end latency under 5 seconds for simple tasks on Tier 2 hardware
- [ ] Setup wizard pulls models and configures everything automatically

### Full Product (Phase 3)
- [ ] Both GIMP and Krita fully supported
- [ ] Vision feedback loop enables self-correcting workflows (3 retry iterations)
- [ ] Multi-step task planning for complex creative projects
- [ ] Web UI provides localhost chat + canvas experience
- [ ] Text-only fallback works for systems without vision model VRAM
- [ ] Comprehensive documentation: user guide, hardware guide, model guide
- [ ] Active open-source community contributing examples and improvements
- [ ] 85%+ success rate on benchmark (32b model with vision feedback)

---

## 17. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|---|---|---|---|
| **Local models generate incorrect/broken scripts** | High | **Very High** | Strong few-shot examples, error recovery loop, vision feedback, API validation, hallucination detection |
| **API hallucination (inventing function names)** | High | **High for 7b models** | Validate every API call against PDB/Krita catalog; suggest closest valid name |
| **VRAM insufficient for useful model** | High | Medium | Support CPU-only inference (slow but works), document minimum hardware, quantization guide |
| **GIMP/Krita API changes break bridge** | Medium | Medium | Version detection, compatibility layer, CI testing against multiple versions |
| **Security vulnerability in generated code** | Medium | Medium | Multi-layer safety validation, sandboxing, user confirmation (lower risk than cloud since no exfiltration) |
| **Context window overflow** | Medium | **High for 7b–14b** | Aggressive context budgeting, RAG instead of stuffing, history summarization |
| **Ollama server not running** | Medium | Medium | Health check on startup, clear error message, offer to start Ollama |
| **Model download time discourages users** | Medium | Medium | Show progress, suggest starting with small model first, pre-built docker images |
| **Scope creep into full AI art generator** | Medium | High | Clear scope boundaries; PixelPilot is a *controller*, not a *generator* |

---

> **This document is a living plan. It should be revisited and updated as research findings from Phase 0 inform technical decisions — especially the Ollama model benchmarking results.**
