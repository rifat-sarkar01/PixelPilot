# PixelPilot Architecture Migration — Planning Prompt

## Context
PixelPilot is a fully offline, privacy-first AI image editor. Natural language instructions currently go: **user prompt → local Ollama LLM (Qwen3 14B) → generated GIMP/Krita Python-Fu/Script-Fu code → direct execution**.

This works reasonably for photo-editing operations (crop, color-adjust, filters, layers) but produces poor results for **illustration/drawing-from-scratch** requests (e.g. "draw a car," "draw a tree") — output is crude, badly-proportioned shape composition. Root cause: the LLM writes code blind, with no chance to inspect the rendered result, and freeform code generation introduces bugs on top of that.

## Target architecture
Split the pipeline by intent:

1. **Editing intents** (existing photo, modify it) → unchanged, keep the current GIMP/Krita scripting path.
2. **Generation intents** (draw/illustrate from nothing) → new path:
   - LLM emits a **structured image plan** (JSON, not code) describing objects: shape type, position, size, color, z-order.
   - A **deterministic executor** (plain code, not LLM-written) walks the plan and renders it — evaluate SVG as the intermediate format (LLMs handle SVG-like structured output well and it's cheap to validate/rasterize) vs. rendering straight to raster.
   - A **render → critique → re-emit plan** loop: render the plan, pass the image to a vision-capable model, ask for corrections against the original instruction, patch the plan, re-render (1–2 iterations).

## Constraints
- Offline/local stays the default path; the editing path must not change.
- Any cloud API use (e.g. a free-tier vision model) should be an opt-in, pluggable backend for the critique step specifically — never a hard dependency.
- Keep the plan schema minimal at first (rect, circle, polygon primitives; position, size, color, z-order) — extensibility over completeness for v1.

## What I need from you
Don't write implementation code yet. First, produce a plan:

1. Inspect the current PixelPilot repo structure (LLM call sites, script generation/execution modules, prompt templates) and summarize how it's currently wired.
2. Propose a concrete JSON schema for the "image plan" (objects, shape types, required/optional fields).
3. Design the executor module: inputs, outputs, where it lives, and your SVG-vs-direct-raster decision with reasoning.
4. Design the intent router: how "edit" vs "generate" gets classified before dispatch.
5. Design the critique loop: what triggers it, how many iterations, how a "correction" is expressed and merged back into the plan (full re-emit vs. patch/diff).
6. List every existing file that needs to change and every new file to add.
7. Flag risks/unknowns (e.g. local model's reliability at emitting valid JSON, SVG rasterization dependencies, latency of a multi-round loop).
8. Propose a phased rollout order — what to build/test first, what can ship incrementally. The editing path must never break.

Output this as a numbered implementation plan, not code. I'll review it before anything gets built.
