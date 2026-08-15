"""Draw a simple cartoon car illustration with a body, two windows and two wheels."""
from gimpfu import *

# 1. Work on the currently open image - PixelPilot guarantees one exists.
image = gimp.image_list()[0]
drawable = image.active_drawable
width = pdb.gimp_image_width(image)
height = pdb.gimp_image_height(image)

pdb.gimp_image_undo_group_start(image)
try:
    # 2. Body: a wide rectangle across the middle band of the canvas (mid-left
    #    through mid-right of the grid). Sized generously - about 60% of the
    #    canvas width - so the subject actually reads as the main illustration
    #    instead of a small accent in the middle of empty space.
    body_w = int(width * 0.60)
    body_h = int(height * 0.18)
    body_x = int(width * 0.5 - body_w * 0.5)
    body_y = int(height * 0.55)

    pdb.gimp_image_select_rectangle(image, CHANNEL_OP_REPLACE, body_x, body_y, body_w, body_h)
    pdb.gimp_context_set_foreground((178, 34, 34))     # firebrick red
    # gimp_image_select_rectangle returns None - always fill `drawable`, never
    # its return value.
    pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)   # clear before the next shape - see rule 14

    # 3. Windows: two rectangles on top of the body, side by side (different x
    #    offsets - one left-of-center, one right-of-center).
    window_w = int(body_w * 0.22)
    window_h = int(body_h * 0.5)
    window_y = body_y - int(window_h * 0.6)   # sits astride the top edge of the body

    window_left_x = body_x + int(body_w * 0.12)
    window_right_x = body_x + int(body_w * 0.62)

    pdb.gimp_image_select_rectangle(image, CHANNEL_OP_REPLACE, window_left_x, window_y, window_w, window_h)
    pdb.gimp_image_select_rectangle(image, CHANNEL_OP_ADD, window_right_x, window_y, window_w, window_h)
    pdb.gimp_context_set_foreground((176, 224, 230))   # pale blue glass
    pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)

    # 4. Wheels: two circles along the bottom edge of the body, at DIFFERENT x
    #    offsets (left third and right third) so they sit side by side rather
    #    than stacked on top of each other at the same x.
    wheel_d = int(body_h * 0.9)
    wheel_y = body_y + body_h - int(wheel_d * 0.5)

    wheel_left_x = body_x + int(body_w * 0.18)
    wheel_right_x = body_x + int(body_w * 0.82)

    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_REPLACE,
                                  wheel_left_x - wheel_d // 2, wheel_y - wheel_d // 2,
                                  wheel_d, wheel_d)
    pdb.gimp_image_select_ellipse(image, CHANNEL_OP_ADD,
                                  wheel_right_x - wheel_d // 2, wheel_y - wheel_d // 2,
                                  wheel_d, wheel_d)
    pdb.gimp_context_set_foreground((40, 40, 40))      # dark tire gray
    pdb.gimp_edit_fill(drawable, FOREGROUND_FILL)
    pdb.gimp_selection_none(image)

    pdb.gimp_displays_flush()
finally:
    pdb.gimp_image_undo_group_end(image)
