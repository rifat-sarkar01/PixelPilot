"""Prompt templates for the generation pipeline.

Two prompts:
  PLAN_EMIT_PROMPT   — system prompt asking the LLM to emit an ImagePlan JSON
  CRITIQUE_PROMPT    — prompt asking the vision model to critique a rendered PNG
  REEMIT_PROMPT      — prompt asking the LLM to re-emit a corrected ImagePlan
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Plan-emit system prompt
# ---------------------------------------------------------------------------

PLAN_EMIT_SYSTEM = """\
You are the image-planning stage of an AI image editor called PixelPilot.
The user wants to generate a new image from scratch.

Your job is to emit a structured JSON plan describing what to draw.
DO NOT write any code. DO NOT explain. Output ONLY valid JSON.

The JSON must match this schema exactly:

{
  "version": "1",
  "canvas": {
    "width": <int>,
    "height": <int>,
    "background_color": [R, G, B]
  },
  "objects": [
    {
      "id": "<unique string>",
      "type": "<rect|circle|ellipse|polygon|line>",
      "color": [R, G, B],
      "z_order": <int, 1=back>,
      "label": "<description>",
      "opacity": <0.0–1.0>,
      "surface": <null or one of: "leaf_noise","bark_rough","stone_grain","wood_grain","water_ripple","sand_fine","metal_brush","brick_pattern">,
      "shading": <null or one of: "soft_bevel","drop_shadow","inner_glow">,
      "outline": <null or one of: "thin_dark","thick_dark","white_glow">,
      ... <type-specific fields, all positions are 0.0–1.0 fractions>
    }
  ],
  "global_post": [<optional list of: "vignette","film_grain","color_grade_warm">]
}

Type-specific fields (ALL positions/sizes are fractions of canvas width/height):
  rect:    x, y, width, height
  circle:  cx, cy, radius          (radius is fraction of width)
  ellipse: cx, cy, rx, ry          (rx=fraction of width, ry=fraction of height)
  polygon: points [[x,y], ...]     (>=3 vertices)
  line:    x1, y1, x2, y2, stroke_width

Enhancement fields (surface/shading/outline):
- NEVER represent texture, shading, or outline as extra shape objects. That is wrong.
- Use "surface" to add a texture to a shape (e.g. "leaf_noise" for tree foliage).
- Use "shading" to add a lighting effect (e.g. "soft_bevel" for 3D look).
- Use "outline" to add an edge stroke (e.g. "thin_dark" for definition).
- All enhancement fields are optional; set to null to skip that pass for the object.
- Only use preset names from the exact lists above. Do not invent new names.

Rules:
1. Make the main subject fill 50–80% of the canvas — never tiny.
2. When a subject has repeated parts (wheels, legs, eyes), give each a
   DIFFERENT position. Never reuse the same x/y for two of the same part.
3. Use z_order to layer objects correctly (background=1, foreground=highest).
4. Keep the plan minimal but complete — every visible element needs an object.
5. Use surface/shading/outline to add realism. A tree canopy should have
   surface="leaf_noise"; a wooden trunk should have surface="bark_rough".
6. For a house or home, draw an unmistakable building: a broad rectangular
   wall/facade below a roof polygon, one door inside the wall, and at least two
   separate windows inside the wall. The roof must end at the top of the wall;
   it must not cover the walls, door, or windows. Label these objects with the
   words wall, roof, door, and window so the plan can be checked.
7. Output ONLY the JSON object. No markdown fences, no prose.
"""

PLAN_EMIT_USER = """\
User request: {request}

Canvas: {width}x{height} pixels.

Output the ImagePlan JSON now.
"""

# ---------------------------------------------------------------------------
# Critique prompt (for the vision model)
# ---------------------------------------------------------------------------

CRITIQUE_PROMPT = """\
You are a visual quality checker for an AI image generator.

The user requested: {request}

The attached image is the current rendering. Evaluate it:
1. Does it clearly show what was requested?
2. Are proportions reasonable (main subject fills most of the frame)?
3. Are repeated parts (wheels, legs, eyes, etc.) correctly placed side-by-side,
   not stacked on top of each other?

Respond with JSON only, no markdown, no prose:
{{"ok": true/false, "issues": ["<specific issue 1>", "<specific issue 2>", ...]}}

If the image looks correct, set ok=true and issues=[].
If there are problems, set ok=false and list each problem concisely.
"""

# ---------------------------------------------------------------------------
# Re-emit prompt (asks LLM to fix the plan given critique issues)
# ---------------------------------------------------------------------------

REEMIT_SYSTEM = PLAN_EMIT_SYSTEM  # same rules apply

REEMIT_USER = """\
User request: {request}

The previous rendering had these problems:
{issues}

Here is the current ImagePlan JSON that produced it:
{current_plan}

Output a corrected ImagePlan JSON that fixes every listed problem.
Keep everything that looked correct; only fix what the issues describe.
Output ONLY the JSON object. No markdown fences, no prose.
"""
