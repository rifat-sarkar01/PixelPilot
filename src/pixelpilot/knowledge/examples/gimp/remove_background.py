"""Remove the background of the current image using fuzzy selection from corners."""
from gimpfu import *

image = gimp.image_list()[0]
drawable = image.active_drawable
width = pdb.gimp_image_width(image)
height = pdb.gimp_image_height(image)

pdb.gimp_image_undo_group_start(image)
try:
    # Step 1: Add alpha channel so clearing produces transparency, not white.
    pdb.gimp_layer_add_alpha(drawable)

    # Step 2: Fuzzy-select the background from all four corners.
    # CHANNEL_OP_REPLACE for the first, CHANNEL_OP_ADD for the rest.
    pdb.gimp_fuzzy_select(drawable, 0, 0, 30, CHANNEL_OP_REPLACE, True, False, 0, False)
    pdb.gimp_fuzzy_select(drawable, width - 1, 0, 30, CHANNEL_OP_ADD, True, False, 0, False)
    pdb.gimp_fuzzy_select(drawable, 0, height - 1, 30, CHANNEL_OP_ADD, True, False, 0, False)
    pdb.gimp_fuzzy_select(drawable, width - 1, height - 1, 30, CHANNEL_OP_ADD, True, False, 0, False)

    # Step 3: Clear the selected background to transparency.
    pdb.gimp_edit_clear(drawable)

    # Step 4: Remove the selection.
    pdb.gimp_selection_none(image)

    pdb.gimp_displays_flush()
finally:
    pdb.gimp_image_undo_group_end(image)
