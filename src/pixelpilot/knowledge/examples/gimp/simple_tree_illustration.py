"""Draw a simple tree illustration (trunk + rounded canopy) on the canvas."""
from gimpfu import *

# 1. Work on the currently open image - never guess its size, read it.
image = gimp.image_list()[0]
drawable = image.active_drawable
width = pdb.gimp_image_width(image)
height = pdb.gimp_image_height(image)

pdb.gimp_image_undo_group_start(image)
try:
    # 2. Sky background fills the whole canvas first (bottom of the stack).
    pdb.gimp_image_select_rectangle(image, CHANNEL_OP_REPLACE, 0, 0, width, height)
    pdb.gimp_context_set_foreground((135, 206, 235))   # sky blue
    pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)   # clear before the next shape - see rule 14

    # 3. Ground band across the bottom third (bot-left/bot-mid/bot-right of the grid).
    ground_y = int(height * 0.75)
    pdb.gimp_image_select_rectangle(image, CHANNEL_OP_REPLACE, 0, ground_y, width, height - ground_y)
    pdb.gimp_context_set_foreground((97, 156, 66))     # grass green
    pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)

    # 4. Trunk: a narrow rectangle centered horizontally, spanning from the ground
    #    line up into the middle of the canvas (mid-mid into bot-mid of the grid).
    trunk_w = int(width * 0.08)
    trunk_h = int(height * 0.30)
    trunk_x = int(width * 0.5 - trunk_w * 0.5)
    trunk_y = ground_y - trunk_h
    pdb.gimp_image_select_rectangle(image, CHANNEL_OP_REPLACE, trunk_x, trunk_y, trunk_w, trunk_h)
    pdb.gimp_context_set_foreground((92, 58, 33))      # brown bark
    pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)   # required - the canopy fill below would otherwise
                                      # be clipped to whatever is left of the trunk selection

    # 5. Canopy: three overlapping ellipses unioned with CHANNEL_OP_ADD so the
    #    foliage reads as one rounded mass instead of a single flat oval. Sits in
    #    the top-mid / center of the grid, overlapping the top of the trunk.
    canopy_cx = int(width * 0.5)
    canopy_cy = trunk_y + int(trunk_h * 0.15)
    canopy_r = int(width * 0.16)
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_REPLACE,
                                  canopy_cx - canopy_r, canopy_cy - canopy_r,
                                  canopy_r * 2, canopy_r * 2)
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_ADD,
                                  canopy_cx - int(canopy_r * 1.5), canopy_cy + int(canopy_r * 0.3),
                                  int(canopy_r * 1.4), int(canopy_r * 1.4))
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_ADD,
                                  canopy_cx + int(canopy_r * 0.1), canopy_cy + int(canopy_r * 0.3),
                                  int(canopy_r * 1.4), int(canopy_r * 1.4))
    pdb.gimp_context_set_foreground((34, 110, 40))     # foliage green
    pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)

    pdb.gimp_displays_flush()
finally:
    pdb.gimp_image_undo_group_end(image)
