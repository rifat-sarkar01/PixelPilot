"""Desaturate the active layer."""
from krita import Krita


def run_pixelpilot():
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        raise RuntimeError("No active document open")
    node = doc.activeNode()

    filter = app.filters()["desaturate"]
    info = filter.configuration()
    info.setProperty("type", 0)  # 0 = luminosity
    filter.apply(node, info, 0, 0, node.bounds().width(), node.bounds().height())
    doc.refreshProjection()


run_pixelpilot()
