"""Add a soft vignette to the photo."""
from gimpfu import *

image = gimp.image_list()[0]
drawable = image.active_drawable

pdb.gimp_image_undo_group_start(image)
try:
    # 1. Duplicate the active layer for the vignette.
    copy = pdb.gimp_layer_copy(drawable, 1)
    pdb.gimp_image_insert_layer(image, copy, None, -1)
    pdb.gimp_item_set_name(copy, "Vignette")

    # 2. Select an oval in the middle, feather it, then invert so only the
    #    edges are selected.
    x = int(drawable.width * 0.5) - int(drawable.width * 0.4)
    y = int(drawable.height * 0.5) - int(drawable.height * 0.4)
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_REPLACE, x, y,
                                  int(drawable.width * 0.8),
                                  int(drawable.height * 0.8))
    pdb.gimp_selection_feather(image, 150.0)
    pdb.gimp_selection_invert(image)

    # 3. Darken only the selected edges.
    pdb.gimp_brightness_contrast(copy, -60, 0)
    pdb.gimp_selection_none(image)

    pdb.gimp_displays_flush()
finally:
    pdb.gimp_image_undo_group_end(image)
