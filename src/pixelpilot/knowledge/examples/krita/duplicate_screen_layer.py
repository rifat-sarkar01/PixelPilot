"""Duplicate the active layer and set the copy to screen blend mode at 70% opacity."""
from krita import Krita


def run_pixelpilot():
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        raise RuntimeError("No active document open")
    source = doc.activeNode()
    if source is None:
        raise RuntimeError("No active node")

    copy = source.duplicate()
    copy.setName("Glow copy")
    copy.setBlendingMode("screen")
    copy.setOpacity(0.7)
    source.parentNode().addChildNode(copy, source)
    doc.setActiveNode(copy)
    doc.refreshProjection()


run_pixelpilot()
