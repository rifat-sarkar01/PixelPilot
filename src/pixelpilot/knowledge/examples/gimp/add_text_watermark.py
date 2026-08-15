"""Add a text watermark in the bottom-right corner."""
from gimpfu import *


def run_pixelpilot():
    images = gimp.image_list()
    if not images:
        raise RuntimeError("No open images.")
    image = images[0]

    pdb.gimp_image_undo_group_start(image)
    try:
        # Create the text layer.
        text_layer = pdb.gimp_text_layer_new(
            image, "PixelPilot", "Sans", 48, 0
        )
        pdb.gimp_image_insert_layer(image, text_layer, None, -1)

        # Set white text with 70% opacity.
        pdb.gimp_context_set_foreground((255, 255, 255, 255))
        pdb.gimp_text_layer_set_color(text_layer, (255, 255, 255, 255))
        pdb.gimp_layer_set_opacity(text_layer, 70.0)

        # Move to the bottom-right corner with padding.
        width, height = pdb.gimp_image_width(image), pdb.gimp_image_height(image)
        text_w, text_h = pdb.gimp_text_layer_get_width(text_layer), pdb.gimp_text_layer_get_height(text_layer)
        pdb.gimp_layer_set_offsets(text_layer, width - text_w - 20, height - text_h - 20)

        pdb.gimp_displays_flush()
    finally:
        pdb.gimp_image_undo_group_end(image)


run_pixelpilot()
