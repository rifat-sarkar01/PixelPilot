"""Blur the background of the active photo to create a shallow depth-of-field look."""
from gimpfu import *


def run_pixelpilot():
    images = gimp.image_list()
    if not images:
        raise RuntimeError("No open images.")
    image = images[0]
    drawable = image.active_drawable

    pdb.gimp_image_undo_group_start(image)
    try:
        # Duplicate so we can blur only the copy, keeping the original intact.
        copy = pdb.gimp_layer_copy(drawable, 1)
        pdb.gimp_image_insert_layer(image, copy, None, -1)
        pdb.gimp_item_set_name(copy, "Background blur")

        # Blur the copy - the subject region should be masked out separately.
        pdb.plug_in_gauss(image, copy, 8.0, 8.0, 0)

        pdb.gimp_displays_flush()
    finally:
        pdb.gimp_image_undo_group_end(image)


run_pixelpilot()
