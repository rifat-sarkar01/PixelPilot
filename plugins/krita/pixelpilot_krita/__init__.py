"""PixelPilot Krita plugin package.

Krita's pykrita loader imports this package and calls ``setup()`` at startup.
The setup function starts the TCP bridge socket and registers the docker panel.

Installation
------------
Automatic: run  pixelpilot --editor krita  (the CLI deploys and starts Krita).

Manual:
  1. Copy this directory to  %APPDATA%/krita/pykrita/pixelpilot_krita/
  2. Copy  pixelpilot_krita.desktop  to  %APPDATA%/krita/pykrita/
  3. Open Krita → Settings → Configure Krita → Python Plugin Manager
  4. Enable "PixelPilot" and restart Krita.
"""

from .plugin import PixelPilotDocker, start_bridge


def setup():
    """Called by Krita's pykrita loader on startup."""
    from .plugin import _register  # noqa: PLC0415
    try:
        _register()
    except Exception:  # noqa: BLE001 - never crash Krita startup
        import traceback
        traceback.print_exc()


# Start bridge at import time: pykrita imports this module during plugin
# scanning but never calls setup() for third-party plugins.  Starting the
# bridge here ensures it is available as soon as Krita loads the module.
try:
    start_bridge()
except Exception:  # noqa: BLE001
    pass
