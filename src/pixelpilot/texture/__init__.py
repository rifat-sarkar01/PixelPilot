"""Texture post-processing pipeline (Phase 3).

Provides GIMP-headless texture application for objects with ``fill=textured``.
The pipeline:
  1. mask_export — export per-object alpha masks from the base render.
  2. gimp_batch  — invoke GIMP headless to apply preset filters constrained to masks.
  3. presets     — maps texture names to concrete GIMP Script-Fu recipes.
"""
