"""Create a new 1200x800 canvas and paint a sunset sky gradient."""
from krita import Krita


def run_pixelpilot():
    app = Krita.instance()
    doc = app.createDocument(1200, 800, "Sunset", "RGBA", "U8", "", 72.0)
    doc.setColorSpace("RGBA", "U8", "")
    root = doc.rootNode()
    layer = doc.createNode("Sky gradient", "paintlayer")
    root.addChildNode(layer, None)
    doc.setActiveNode(layer)

    # Fill the layer with a warm-to-purple vertical gradient by setting pixels.
    bounds = layer.bounds()
    w, h = bounds.width(), bounds.height()
    pixels = bytearray(w * h * 4)
    top = (255, 128, 0)      # warm orange
    bottom = (75, 0, 130)    # deep purple
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(w):
            idx = (y * w + x) * 4
            pixels[idx] = b      # BGRA byte order
            pixels[idx + 1] = g
            pixels[idx + 2] = r
            pixels[idx + 3] = 255
    layer.setPixelData(bytes(pixels), bounds.x(), bounds.y(), w, h)
    doc.refreshProjection()


run_pixelpilot()
