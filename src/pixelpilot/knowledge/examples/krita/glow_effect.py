"""Add a glow effect around the subject using a gaussian-blurred duplicate."""
from krita import Krita


def run_pixelpilot():
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        raise RuntimeError("No active document open")
    node = doc.activeNode()

    # 1. Duplicate the subject layer.
    glow = node.duplicate()
    glow.setName("Glow")
    node.parentNode().addChildNode(glow, node)
    doc.setActiveNode(glow)

    # 2. Apply gaussian blur to the duplicate.
    filter = app.filters()["gaussian blur"]
    info = filter.configuration()
    info.setProperty("horizRadius", 20)
    info.setProperty("vertRadius", 20)
    filter.apply(glow, info, 0, 0, glow.bounds().width(), glow.bounds().height())

    # 3. Screen blend + lower opacity for the glow effect.
    glow.setBlendingMode("screen")
    glow.setOpacity(0.8)
    doc.refreshProjection()


run_pixelpilot()
