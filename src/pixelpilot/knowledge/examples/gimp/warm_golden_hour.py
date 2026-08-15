"""Give this photo a warm, golden-hour look."""
from gimpfu import *


def run_pixelpilot():
    images = gimp.image_list()
    if not images:
        raise RuntimeError("No open images.")
    image = images[0]
    drawable = image.active_drawable

    pdb.gimp_image_undo_group_start(image)
    try:
        # 1. Boost reds/yellows in the highlights with a levels curve.
        pdb.gimp_levels(drawable, HISTOGRAM_VALUE, 0, 255, 1.15, 0, 255)

        # 2. Warm the shadows with color balance: +red, +yellow.
        pdb.gimp_color_balance(drawable, COLOR_BALANCE_SHADOWS, 1, True, 15, -5, -15)
        pdb.gimp_color_balance(drawable, COLOR_BALANCE_HIGHLIGHTS, 1, True, 10, 0, -10)

        # 3. Slight saturation lift.
        pdb.gimp_hue_saturation(drawable, HUE_RANGE_ALL, 0, 8, 0)

        pdb.gimp_displays_flush()
    finally:
        pdb.gimp_image_undo_group_end(image)


run_pixelpilot()
