"""Desaturate the background of the photo but keep the subject in color."""
from gimpfu import *


def run_pixelpilot():
    images = gimp.image_list()
    if not images:
        raise RuntimeError("No open images.")
    image = images[0]
    drawable = image.active_drawable

    pdb.gimp_image_undo_group_start(image)
    try:
        # 1. Duplicate the active layer.
        copy = pdb.gimp_layer_copy(drawable, 1)
        pdb.gimp_image_insert_layer(image, copy, None, -1)
        pdb.gimp_item_set_name(copy, "Desaturated background")

        # 2. Desaturate the duplicate (luminosity method).
        pdb.gimp_desaturate_full(copy, 0)

        # 3. Add a white layer mask (fully opaque: the desaturated copy covers color).
        mask = pdb.gimp_layer_create_mask(copy, ADD_WHITE_MASK)
        pdb.gimp_layer_add_mask(copy, mask)

        # 4. Paint black on the mask over the subject to reveal the color beneath.
        pdb.gimp_context_set_foreground((0, 0, 0, 255))
        pdb.gimp_edit_fill(mask, FOREGROUND_FILL)  # subject region must be selected first

        pdb.gimp_displays_flush()
    finally:
        pdb.gimp_image_undo_group_end(image)


run_pixelpilot()
