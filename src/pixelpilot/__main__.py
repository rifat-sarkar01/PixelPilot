"""Allow ``python -m pixelpilot``."""

import sys

from pixelpilot.main import main

if __name__ == "__main__":
    sys.exit(main())
