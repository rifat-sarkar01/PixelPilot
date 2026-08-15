"""Generate a sunset landscape photo from scratch on a new canvas."""
from gimpfu import *

# 1. Create a brand new canvas (no open image required).
width = 1200
height = 800
image = pdb.gimp_image_new(width, height, RGB)
pdb.gimp_image_undo_group_start(image)
try:
    # 2. Sky layer: vertical gradient, warm near the horizon.
    sky = pdb.gimp_layer_new(image, width, height, RGBA_IMAGE, "Sky", 100.0, NORMAL_MODE)
    pdb.gimp_image_insert_layer(image, sky, None, 0)
    pdb.gimp_context_set_foreground((255, 140, 0))     # warm orange (bottom)
    pdb.gimp_context_set_background((255, 210, 120))   # pale yellow (top)
    pdb.gimp_edit_blend(sky, BLEND_FG_BG_RGB, 0, GRADIENT_LINEAR, 100, 0,
                        REPEAT_NONE, True, False, 3, 0, 0, width, height, 0, 0)

    # 3. Sun layer: a soft red disc that will sit behind the hills.
    sun = pdb.gimp_layer_new(image, width, height, RGBA_IMAGE, "Sun", 100.0, NORMAL_MODE)
    pdb.gimp_image_insert_layer(image, sun, None, 0)
    sun_d = int(width * 0.20)
    cx, cy = int(width * 0.65), int(height * 0.55)
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_REPLACE,
                                  cx - sun_d // 2, cy - sun_d // 2, sun_d, sun_d)
    pdb.gimp_selection_feather(image, 6.0)
    pdb.gimp_context_set_foreground((230, 60, 20))     # red
    pdb.gimp_edit_fill(sun, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)

    # 4. Ground layer: dark earth band covering the lower part.
    ground = pdb.gimp_layer_new(image, width, int(height * 0.38), RGBA_IMAGE,
                                "Ground", 100.0, NORMAL_MODE)
    pdb.gimp_image_insert_layer(image, ground, None, 0)
    pdb.gimp_layer_set_offsets(ground, 0, int(height * 0.62))
    pdb.gimp_context_set_foreground((60, 40, 30))      # dark earth
    pdb.gimp_drawable_fill(ground, FOREGROUND_FILL)

    # 5. Mountains layer: filled purple silhouette built by unioning overlapping
    #    shapes (CHANNEL_OP_ADD) so the ridge reads as solid hills.
    mountains = pdb.gimp_layer_new(image, width, height, RGBA_IMAGE,
                                   "Mountains", 100.0, NORMAL_MODE)
    pdb.gimp_image_insert_layer(image, mountains, None, 0)
    ridge_y = int(height * 0.62)
    pdb.gimp_image_select_rectangle(image, CHANNEL_OP_REPLACE,
                                    0, ridge_y, width, height - ridge_y)
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_ADD,
                                  int(width * 0.02), int(height * 0.44),
                                  int(width * 0.34), int(height * 0.28))
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_ADD,
                                  int(width * 0.28), int(height * 0.38),
                                  int(width * 0.40), int(height * 0.34))
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_ADD,
                                  int(width * 0.60), int(height * 0.46),
                                  int(width * 0.36), int(height * 0.26))
    pdb.gimp_context_set_foreground((74, 36, 96))      # deep purple
    pdb.gimp_edit_fill(mountains, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)

    pdb.gimp_display_new(image)
    pdb.gimp_displays_flush()
finally:
    pdb.gimp_image_undo_group_end(image)
