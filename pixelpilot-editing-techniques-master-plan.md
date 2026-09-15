# PixelPilot — Master Plan: Editing Techniques for Surface Quality

## Core principle

**The plan owns structure. Editing owns surface.**

The LLM should never be asked to represent texture, shading, gloss, or outline as *objects*. Those are pixel-level operations on a region, not shapes. The plan generator only picks a preset **name** per object (enum-constrained); a fixed, non-LLM executor turns that name into real GIMP/Krita operations, masked to the object's silhouette. This is what your two sample images were missing — texture was being resolved as more plan objects instead of triggering this separate stage.

---

## Full pipeline

```
NL prompt
   │
   ▼
[Intent Router] ──edit──► existing GIMP/Krita edit path (unchanged)
   │ generate
   ▼
[Plan Generator] → objects with structural fields (shape/pos/size)
   │                + enhancement fields (surface/shading/outline — enum only)
   ▼
[Resolver] → attachments, constraint clamping
   ▼
[SVG Builder] → base.svg (structure only, enhancement fields ignored here)
   ▼
[Rasterizer] → base.png
   ▼
[Mask Exporter] → per-object silhouette masks
   ▼
[Technique Executor] (single batched GIMP/Krita invocation)
   → applies surface → shading → outline recipes, each masked to its object
   ▼
[Global Post Pass] (optional: vignette / grain / color grade, whole canvas)
   ▼
final PNG
   ▼
[Critic] (optional, vision model) → patches → back to Resolver
```

---

## 1. Plan schema — add enhancement fields

```json
{
  "id": "canopy",
  "type": "ellipse",
  "cx": 400, "cy": 380, "rx": 180, "ry": 140,
  "color": "#228B22",
  "z": 2,
  "surface": "leaf_noise",
  "shading": "soft_bevel",
  "outline": "thin_dark"
}
```

`surface`, `shading`, `outline` are each **either null or a name from a fixed enum** defined in the technique registry below. The LLM is never shown a way to draw texture as shapes — that field simply doesn't exist in the schema. If a field is null, that stage is skipped entirely for that object (fast path for simple flat shapes).

---

## 2. Technique registry (the actual "editing techniques" layer)

A declarative recipe library — YAML or JSON — mapping preset name → ordered list of GIMP/Krita PDB operations. This is what makes the system reliable: the LLM never authors operations, it only selects a name.

```yaml
surface:
  leaf_noise:
    - op: plug-in-hsv-noise
      params: {holdness: 2, hue: 10, saturation: 20, value: 15}
  bark_rough:
    - op: plug-in-plasma
      params: {seed: random, turbulence: 3.0}
    - op: gimp-curves-spline
      params: {channel: value, control_points: [0,40, 128,90, 255,160]}
  stone_grain:
    - op: plug-in-plasma
      params: {seed: random, turbulence: 1.5}

shading:
  soft_bevel:
    - op: plug-in-bump-map
      params: {azimuth: 135, elevation: 45, depth: 3}
  drop_shadow:
    - op: plug-in-drop-shadow
      params: {offset_x: 6, offset_y: 6, blur: 8, opacity: 60}

outline:
  thin_dark:
    - op: select-grow-subtract   # grow selection 1–2px, subtract original, fill dark
      params: {width: 2, color: "#00000080"}
```

Start with 3–5 presets per category. Adding a new look later means adding a recipe entry, never touching the LLM prompt beyond widening the enum.

---

## 3. Mask export

For every object with any enhancement field set:
- Re-render just that object's path in isolation (reuse the SVG Builder, hide all other objects) → rasterize to an alpha-only PNG mask.
- Store as `masks/{object_id}.png`, same canvas dimensions as `base.png` so masks and base align pixel-for-pixel.

---

## 4. Technique executor — batch, don't spawn-per-object

Spawning a GIMP process per object is the latency risk flagged earlier. Instead, build **one** Script-Fu/Python-Fu batch script per image that:

1. Loads `base.png`.
2. For each object, in order — `surface` → `shading` → `outline`:
   - `gimp-image-select-item` using the object's mask (alpha-to-selection)
   - Run the recipe's operations in sequence, constrained to that selection
   - `gimp-selection-none`
3. Flattens all layers.
4. Exports final PNG.
5. Single `gimp -i -b '(...)' -b '(gimp-quit 0)'` invocation for the whole image, not one per object.

```scheme
; one operation from a recipe, applied inside a masked selection
(gimp-image-select-item image CHANNEL-OP-REPLACE canopy-mask-layer)
(plug-in-hsv-noise RUN-NONINTERACTIVE image drawable 2 10 20 15)
(gimp-selection-none image)
```

If Krita is preferred for a given operation (some filters are nicer in Krita's engine), the same registry entry can point to a Krita Python-API script instead — the executor just needs a `backend: gimp|krita` field per recipe.

---

## 5. Global post pass (optional)

Same recipe mechanism, applied once to the whole canvas after all per-object passes: vignette, film grain, overall color grade. Skippable by default; opt-in per plan.

---

## Updated file layout

```
pixelpilot/
  intent/router.py
  plan/schema.py            # now includes surface/shading/outline enums
  plan/generator.py
  plan/resolver.py
  render/svg_builder.py     # structure only
  render/rasterize.py
  render/mask_export.py     # NEW — per-object silhouette masks
  technique/registry.py     # NEW — loads recipe YAML
  technique/executor.py     # NEW — builds + runs the single batched GIMP script
  technique/recipes.yaml    # NEW — the preset library
  critique/critic.py
  critique/patch.py
  backends/ollama_backend.py
  backends/cloud_backend.py
  edit/                     # existing GIMP/Krita editing path — untouched
```

---

## Testing

- **Recipe regression**: fixed mask + preset name → run executor → pixel-diff against a stored reference PNG. Catches recipe/executor breakage independent of the LLM.
- **Schema**: enum validation rejects any `surface`/`shading`/`outline` value not in the registry.
- **Batch correctness**: verify multi-object plans apply operations in the right order and don't bleed outside their mask (check pixels just outside each mask boundary are untouched).
- **Prompt regression set**: same ~10–15 fixed prompts as before, now checked specifically for "does texture look like texture" rather than scattered shapes.

---

## Rollout order

1. Schema fields + registry with 2–3 presets (one per category) — wire executor for a single hardcoded test object first, not through the full LLM path.
2. Mask export + batched executor working end-to-end on one real generated plan (e.g. the tree).
3. Expand preset library once the mechanism is proven.
4. Add `backend: krita` support only if/when a specific effect needs it.
5. Global post pass, last — lowest priority, purely cosmetic.

---

## Risks

| Risk | Mitigation |
|---|---|
| Mask misalignment with base.png (off-by-pixel) | Render masks from the exact same SVG/coordinate system as the base, same canvas size, no separate scaling step |
| LLM picks a preset name that doesn't exist | Schema enum validation catches this before execution; retry with error feedback, same pattern as Phase 1 |
| Recipe order matters and gets it wrong (e.g. outline drawn before shading) | Fixed order enforced by the executor (surface → shading → outline), not configurable per-plan |
| GIMP batch script complexity grows with object count | Generate the Script-Fu script programmatically from the recipe list rather than hand-writing it — executor is a template, not bespoke code per image |
