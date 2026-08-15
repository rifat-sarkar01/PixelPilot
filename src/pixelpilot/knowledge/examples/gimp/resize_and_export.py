"""Resize the image to 800x600 and export it as PNG."""
from gimpfu import *


def run_pixelpilot():
    images = gimp.image_list()
    if not images:
        raise RuntimeError("No open images.")
    image = images[0]
    drawable = image.active_drawable

    pdb.gimp_image_undo_group_start(image)
    try:
        pdb.gimp_image_scale_full(image, 800, 600, INTERPOLATION_CUBIC)
        pdb.gimp_file_save(image, drawable, "output.png", "output.png")
        pdb.gimp_displays_flush()
    finally:
        pdb.gimp_image_undo_group_end(image)


run_pixelpilot()
